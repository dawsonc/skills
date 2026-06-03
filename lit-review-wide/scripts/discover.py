#!/usr/bin/env python3
"""discover.py — multi-source paper discovery for literature reviews.

Queries Semantic Scholar, OpenAlex, and arXiv; deduplicates by DOI / arXiv ID /
fuzzy title; emits normalised JSON to stdout. Also generates BibTeX stubs.

Subcommands:
  keyword   Search by query string (all three sources, deduplicated).
  lookup    Fetch metadata for a specific paper by DOI or arXiv ID.
  refs      Backward citations (references) of a seed paper.
  cites     Forward citations (papers that cite a seed paper).
  to-bibtex Convert JSON records (with optional `annote` field) to BibTeX.

All discovery output uses this normalised schema:
  {
    "title": str,
    "authors": [{"name": str}, ...],
    "year": int | None,
    "venue": str | None,
    "doi": str | None,
    "arxiv_id": str | None,
    "s2_id": str | None,
    "openalex_id": str | None,
    "abstract": str | None,
    "citation_count": int | None,
    "url": str | None,
    "open_access_pdf_url": str | None,
    "sources": [str, ...]
  }

Stdlib only. APIs are keyless; respects rate limits via simple delays.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from xml.etree import ElementTree as ET

# Polite identifier for OpenAlex "polite pool". Override with --mailto.
DEFAULT_MAILTO = "lit-review-skill@example.org"

S2_BASE = "https://api.semanticscholar.org/graph/v1"
OPENALEX_BASE = "https://api.openalex.org"
ARXIV_BASE = "http://export.arxiv.org/api/query"

S2_FIELDS = (
    "title,authors,year,venue,externalIds,abstract,"
    "citationCount,openAccessPdf,url"
)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _get_json(url: str, timeout: int = 30, retries: int = 3) -> dict[str, Any]:
    """GET a URL and parse JSON; retry on 429/5xx with backoff."""
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "lit-review-skill/1.0"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"GET {url} failed after {retries} attempts: {last_err}")


def _get_text(url: str, timeout: int = 30) -> str:
    """GET a URL and return text body (for arXiv's Atom feed)."""
    req = urllib.request.Request(url, headers={"User-Agent": "lit-review-skill/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


# ---------------------------------------------------------------------------
# Source-specific search
# ---------------------------------------------------------------------------


def search_s2(query: str, limit: int, year_from: int | None, year_to: int | None
              ) -> list[dict[str, Any]]:
    """Search Semantic Scholar Graph API by relevance."""
    params = {"query": query, "limit": str(min(limit, 100)), "fields": S2_FIELDS}
    if year_from or year_to:
        params["year"] = f"{year_from or ''}-{year_to or ''}"
    url = f"{S2_BASE}/paper/search?{urllib.parse.urlencode(params)}"
    try:
        data = _get_json(url)
    except Exception as e:
        print(f"# s2 search failed: {e}", file=sys.stderr)
        return []
    return [_normalise_s2(p) for p in data.get("data", [])]


def search_openalex(query: str, limit: int, year_from: int | None,
                    year_to: int | None, mailto: str) -> list[dict[str, Any]]:
    """Search OpenAlex Works by full-text search."""
    filters = []
    if year_from:
        filters.append(f"from_publication_date:{year_from}-01-01")
    if year_to:
        filters.append(f"to_publication_date:{year_to}-12-31")
    params = {
        "search": query,
        "per-page": str(min(limit, 200)),
        "mailto": mailto,
    }
    if filters:
        params["filter"] = ",".join(filters)
    url = f"{OPENALEX_BASE}/works?{urllib.parse.urlencode(params)}"
    try:
        data = _get_json(url)
    except Exception as e:
        print(f"# openalex search failed: {e}", file=sys.stderr)
        return []
    return [_normalise_openalex(w) for w in data.get("results", [])]


def search_arxiv(query: str, limit: int) -> list[dict[str, Any]]:
    """Search arXiv via its Atom API. No native date filter on free-text queries."""
    params = {
        "search_query": f"all:{query}",
        "start": "0",
        "max_results": str(limit),
        "sortBy": "relevance",
    }
    url = f"{ARXIV_BASE}?{urllib.parse.urlencode(params)}"
    try:
        body = _get_text(url)
    except Exception as e:
        print(f"# arxiv search failed: {e}", file=sys.stderr)
        return []
    return _parse_arxiv_atom(body)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def _normalise_s2(p: dict[str, Any]) -> dict[str, Any]:
    ext = p.get("externalIds") or {}
    oapdf = p.get("openAccessPdf") or {}
    return {
        "title": (p.get("title") or "").strip(),
        "authors": [{"name": a.get("name", "")} for a in (p.get("authors") or [])],
        "year": p.get("year"),
        "venue": p.get("venue"),
        "doi": (ext.get("DOI") or "").lower() or None,
        "arxiv_id": ext.get("ArXiv"),
        "s2_id": p.get("paperId"),
        "openalex_id": None,
        "abstract": p.get("abstract"),
        "citation_count": p.get("citationCount"),
        "url": p.get("url"),
        "open_access_pdf_url": oapdf.get("url"),
        "sources": ["semantic_scholar"],
    }


def _normalise_openalex(w: dict[str, Any]) -> dict[str, Any]:
    venue = ((w.get("primary_location") or {}).get("source") or {}).get(
        "display_name"
    )
    oa = w.get("open_access") or {}
    doi = (w.get("doi") or "").replace("https://doi.org/", "").lower() or None
    return {
        "title": (w.get("title") or "").strip(),
        "authors": [
            {"name": (a.get("author") or {}).get("display_name", "")}
            for a in (w.get("authorships") or [])
        ],
        "year": w.get("publication_year"),
        "venue": venue,
        "doi": doi,
        "arxiv_id": _extract_arxiv_from_openalex(w),
        "s2_id": None,
        "openalex_id": w.get("id"),
        "abstract": _reconstruct_openalex_abstract(w.get("abstract_inverted_index")),
        "citation_count": w.get("cited_by_count"),
        "url": w.get("id"),
        "open_access_pdf_url": oa.get("oa_url"),
        "sources": ["openalex"],
    }


def _extract_arxiv_from_openalex(w: dict[str, Any]) -> str | None:
    for loc in w.get("locations") or []:
        landing = (loc.get("landing_page_url") or "")
        if "arxiv.org" in landing:
            m = re.search(r"arxiv\.org/abs/([\w.\-/]+)", landing)
            if m:
                return m.group(1)
    return None


def _reconstruct_openalex_abstract(inv: dict[str, list[int]] | None) -> str | None:
    """OpenAlex returns abstracts as inverted indices; rebuild the text."""
    if not inv:
        return None
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions) or None


def _parse_arxiv_atom(body: str) -> list[dict[str, Any]]:
    ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    root = ET.fromstring(body)
    out: list[dict[str, Any]] = []
    for entry in root.findall("a:entry", ns):
        arxiv_url = (entry.findtext("a:id", default="", namespaces=ns) or "").strip()
        arxiv_id = arxiv_url.rsplit("/", 1)[-1] if arxiv_url else None
        # Strip version suffix for dedup parity.
        arxiv_id_bare = re.sub(r"v\d+$", "", arxiv_id) if arxiv_id else None
        published = entry.findtext("a:published", default="", namespaces=ns) or ""
        year = int(published[:4]) if published[:4].isdigit() else None
        title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
        title = re.sub(r"\s+", " ", title)
        summary = (entry.findtext("a:summary", default="", namespaces=ns) or "").strip()
        authors = [
            {"name": (a.findtext("a:name", default="", namespaces=ns) or "").strip()}
            for a in entry.findall("a:author", ns)
        ]
        doi_el = entry.find("arxiv:doi", ns)
        doi = doi_el.text.lower() if doi_el is not None and doi_el.text else None
        pdf_url = None
        for link in entry.findall("a:link", ns):
            if link.attrib.get("title") == "pdf":
                pdf_url = link.attrib.get("href")
        out.append({
            "title": title,
            "authors": authors,
            "year": year,
            "venue": "arXiv",
            "doi": doi,
            "arxiv_id": arxiv_id_bare,
            "s2_id": None,
            "openalex_id": None,
            "abstract": summary or None,
            "citation_count": None,
            "url": arxiv_url or None,
            "open_access_pdf_url": pdf_url,
            "sources": ["arxiv"],
        })
    return out


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def _norm_title(t: str) -> str:
    t = t.lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def dedupe(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge records that share a DOI, arXiv ID, or normalised title."""
    out: list[dict[str, Any]] = []
    by_doi: dict[str, int] = {}
    by_arxiv: dict[str, int] = {}
    by_title: dict[str, int] = {}

    for r in records:
        idx: int | None = None
        if r.get("doi") and r["doi"] in by_doi:
            idx = by_doi[r["doi"]]
        elif r.get("arxiv_id") and r["arxiv_id"] in by_arxiv:
            idx = by_arxiv[r["arxiv_id"]]
        else:
            nt = _norm_title(r.get("title") or "")
            if nt and nt in by_title:
                idx = by_title[nt]

        if idx is None:
            out.append(r)
            j = len(out) - 1
            if r.get("doi"):
                by_doi[r["doi"]] = j
            if r.get("arxiv_id"):
                by_arxiv[r["arxiv_id"]] = j
            nt = _norm_title(r.get("title") or "")
            if nt:
                by_title[nt] = j
        else:
            _merge(out[idx], r)

    return out


def _merge(dst: dict[str, Any], src: dict[str, Any]) -> None:
    """Fill missing fields in dst from src; union the sources list."""
    for k in ("doi", "arxiv_id", "s2_id", "openalex_id", "venue", "year",
             "abstract", "citation_count", "url", "open_access_pdf_url"):
        if not dst.get(k) and src.get(k):
            dst[k] = src[k]
    if len(src.get("authors") or []) > len(dst.get("authors") or []):
        dst["authors"] = src["authors"]
    dst["sources"] = sorted(set((dst.get("sources") or []) + (src.get("sources") or [])))


# ---------------------------------------------------------------------------
# Citation chasing (Semantic Scholar)
# ---------------------------------------------------------------------------


def _s2_paper_id(identifier: str) -> str:
    """Map DOI / arXiv ID / raw S2 ID into the form S2 accepts."""
    if identifier.lower().startswith("10."):
        return f"DOI:{identifier}"
    if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", identifier):
        return f"arXiv:{identifier}"
    return identifier


def get_refs_or_cites(identifier: str, direction: str, limit: int
                      ) -> list[dict[str, Any]]:
    """Fetch backward references or forward citations via Semantic Scholar."""
    assert direction in ("references", "citations")
    pid = _s2_paper_id(identifier)
    nested = "citedPaper" if direction == "references" else "citingPaper"
    fields = ",".join(f"{nested}.{f}" for f in S2_FIELDS.split(","))
    url = (f"{S2_BASE}/paper/{urllib.parse.quote(pid, safe=':')}/{direction}"
           f"?limit={min(limit, 1000)}&fields={fields}")
    data = _get_json(url)
    out: list[dict[str, Any]] = []
    for item in data.get("data", []):
        paper = item.get(nested)
        if paper:
            out.append(_normalise_s2(paper))
    return out


# ---------------------------------------------------------------------------
# BibTeX generation
# ---------------------------------------------------------------------------

_CITEKEY_STOP = {
    "a", "an", "the", "of", "on", "in", "for", "to", "and", "or", "with",
    "by", "from", "via", "using", "towards", "toward", "into", "as", "at",
    "is", "are", "be", "this", "that", "we", "our",
}


def make_citekey(record: dict[str, Any], existing: set[str]) -> str:
    """authorYEARword, lowercase alnum, disambiguated against existing keys."""
    authors = record.get("authors") or []
    first = authors[0]["name"] if authors else "anon"
    last = first.split()[-1] if first else "anon"
    last = re.sub(r"[^A-Za-z]", "", last).lower() or "anon"

    year = record.get("year")
    year_str = str(year) if year else "nd"

    title = record.get("title") or ""
    word = ""
    for tok in re.findall(r"[A-Za-z]+", title):
        tl = tok.lower()
        if tl not in _CITEKEY_STOP and len(tl) > 2:
            word = tl
            break
    word = word or "paper"

    base = f"{last}{year_str}{word}"
    key = base
    n = 1
    while key in existing:
        n += 1
        key = f"{base}{chr(ord('a') + n - 1)}"  # base, baseb, basec, ...
    return key


def _bib_escape(s: str | None) -> str:
    if not s:
        return ""
    # Preserve braces and special chars; let the user clean up unicode if needed.
    return s.replace("\\", "\\textbackslash{}").replace("{", "\\{").replace("}", "\\}")


def to_bibtex_entry(record: dict[str, Any], citekey: str,
                    annote: str | None = None) -> str:
    """Render one BibTeX entry. abstract → `abstract`, summary → `annote`."""
    entry_type = "article" if record.get("venue") else "misc"
    if record.get("venue") and any(
        kw in (record["venue"] or "").lower()
        for kw in ("conference", "proceedings", "neurips", "icml", "iclr",
                   "cdc", "acc", "icra", "iros", "rss", "corl", "l4dc")
    ):
        entry_type = "inproceedings"
    if record.get("venue") == "arXiv":
        entry_type = "misc"

    fields: list[tuple[str, str]] = []
    authors = " and ".join(a["name"] for a in (record.get("authors") or []) if a.get("name"))
    if authors:
        fields.append(("author", _bib_escape(authors)))
    if record.get("title"):
        fields.append(("title", "{" + _bib_escape(record["title"]) + "}"))
    if record.get("venue") and entry_type == "inproceedings":
        fields.append(("booktitle", _bib_escape(record["venue"])))
    elif record.get("venue") and entry_type == "article":
        fields.append(("journal", _bib_escape(record["venue"])))
    if record.get("year"):
        fields.append(("year", str(record["year"])))
    if record.get("doi"):
        fields.append(("doi", record["doi"]))
    if record.get("arxiv_id"):
        fields.append(("eprint", record["arxiv_id"]))
        fields.append(("archivePrefix", "arXiv"))
    if record.get("url"):
        fields.append(("url", record["url"]))
    if record.get("abstract"):
        fields.append(("abstract", "{" + _bib_escape(record["abstract"]) + "}"))
    if annote:
        fields.append(("annote", "{" + _bib_escape(annote) + "}"))

    lines = [f"@{entry_type}{{{citekey},"]
    for k, v in fields:
        lines.append(f"  {k} = {{{v}}}," if not v.startswith("{") else f"  {k} = {v},")
    lines.append("}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_keyword(args: argparse.Namespace) -> None:
    results: list[dict[str, Any]] = []
    if "s2" in args.sources:
        results += search_s2(args.query, args.limit, args.year_from, args.year_to)
        time.sleep(1.0)
    if "openalex" in args.sources:
        results += search_openalex(args.query, args.limit, args.year_from,
                                   args.year_to, args.mailto)
        time.sleep(0.5)
    if "arxiv" in args.sources:
        results += search_arxiv(args.query, args.limit)
        time.sleep(3.0)
    json.dump(dedupe(results), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def _cmd_refs_or_cites(args: argparse.Namespace) -> None:
    direction = "references" if args.subcommand == "refs" else "citations"
    results = get_refs_or_cites(args.id, direction, args.limit)
    json.dump(dedupe(results), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def _cmd_lookup(args: argparse.Namespace) -> None:
    pid = _s2_paper_id(args.id)
    url = f"{S2_BASE}/paper/{urllib.parse.quote(pid, safe=':')}?fields={S2_FIELDS}"
    data = _get_json(url)
    json.dump(_normalise_s2(data), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def _cmd_to_bibtex(args: argparse.Namespace) -> None:
    """Read JSON list from stdin or --input; write BibTeX to stdout.

    Each record may carry an optional `citekey` and `annote` field; otherwise
    a citekey is generated and annote is omitted.
    """
    raw = (open(args.input).read() if args.input else sys.stdin.read())
    records = json.loads(raw)
    if not isinstance(records, list):
        records = [records]

    existing: set[str] = set()
    if args.existing_bib:
        with open(args.existing_bib) as f:
            for m in re.finditer(r"^@\w+\{([^,]+),", f.read(), re.MULTILINE):
                existing.add(m.group(1).strip())

    out_entries: list[str] = []
    for r in records:
        key = r.get("citekey") or make_citekey(r, existing)
        existing.add(key)
        out_entries.append(to_bibtex_entry(r, key, r.get("annote")))
    sys.stdout.write("\n\n".join(out_entries) + "\n")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="subcommand", required=True)

    pk = sub.add_parser("keyword", help="Keyword search across S2/OpenAlex/arXiv.")
    pk.add_argument("query")
    pk.add_argument("--limit", type=int, default=25)
    pk.add_argument("--year-from", type=int)
    pk.add_argument("--year-to", type=int)
    pk.add_argument("--sources", nargs="+",
                    default=["s2", "openalex", "arxiv"],
                    choices=["s2", "openalex", "arxiv"])
    pk.add_argument("--mailto", default=DEFAULT_MAILTO)
    pk.set_defaults(func=_cmd_keyword)

    for name, help_text in (("refs", "Backward references of a seed paper."),
                            ("cites", "Forward citations of a seed paper.")):
        pc = sub.add_parser(name, help=help_text)
        pc.add_argument("id", help="DOI, arXiv ID, or S2 paper ID.")
        pc.add_argument("--limit", type=int, default=100)
        pc.set_defaults(func=_cmd_refs_or_cites)

    pl = sub.add_parser("lookup", help="Fetch one paper by DOI or arXiv ID.")
    pl.add_argument("id")
    pl.set_defaults(func=_cmd_lookup)

    pb = sub.add_parser("to-bibtex", help="Convert JSON records to BibTeX entries.")
    pb.add_argument("--input", help="JSON file; default stdin.")
    pb.add_argument("--existing-bib",
                    help="Existing .bib file; used to avoid citekey collisions.")
    pb.set_defaults(func=_cmd_to_bibtex)

    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
