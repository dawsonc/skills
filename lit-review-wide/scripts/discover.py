#!/usr/bin/env python3
"""discover.py -- multi-database paper discovery for literature reviews.

A thin bridge over findpapers (https://github.com/jonatasgrosman/findpapers),
pinned to one immutable commit by findpapers.pin and installed once by
bootstrap.sh. Do not run this with the system interpreter; go through run.sh,
which selects the pinned venv and loads API keys:

    bash run.sh discover.py search '[safe reinforcement learning] AND [Lyapunov]'

Eight databases are reachable through one query: arXiv, CrossRef, IEEE Xplore,
OpenAlex, PubMed, Scopus, Semantic Scholar, Web of Science. IEEE, Scopus and
Web of Science need an API key; the rest work keyless.

Subcommands:
  search    Boolean query across every database a key is available for.
  get       Fetch one paper by DOI or landing-page URL.
  snowball  Backward/forward citation traversal (BFS) from a seed DOI.
  similar   Content-similar papers around a seed DOI.
  download  Best-effort PDF fetch for one paper, named by citekey.
  to-bibtex Convert JSON records (with optional `annote`) to BibTeX.

Query syntax is findpapers', not free text. Terms go in square brackets and
are joined with AND / OR / AND NOT; see the skill's SKILL.md or
https://github.com/jonatasgrosman/findpapers/blob/main/docs/query-syntax.md.
A bare unbracketed string is treated as ONE literal phrase, which will
silently narrow a search -- always bracket.

Discovery subcommands write a JSON array to stdout in this normalised schema:
  {
    "title": str,
    "authors": [{"name": str, "affiliation": str | None}, ...],
    "year": int | None,
    "venue": str | None,
    "publisher": str | None,
    "issn": str | None,
    "doi": str | None,
    "arxiv_id": str | None,
    "url": str | None,
    "open_access_pdf_url": str | None,
    "abstract": str | None,
    "citation_count": int | None,
    "keywords": [str, ...],
    "entry_type": str | None,      # BibTeX type, from findpapers' paper_type
    "is_open_access": bool | None,
    "is_retracted": bool | None,
    "language": str | None,
    "references": [doi, ...],      # works this paper cites
    "cited_by": [doi, ...],        # works citing this paper
    "sources": [str, ...]          # databases the paper was found in
  }

A one-line run summary (databases answered, skipped, failed; per-database
counts) goes to stderr, so stdout stays a clean pipe into to-bibtex.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import findpapers
except ModuleNotFoundError:  # pragma: no cover - the wrapper normally prevents this
    sys.exit(
        "discover.py: findpapers is not importable.\n"
        "Run this through run.sh, or install it once with bootstrap.sh."
    )

# Databases that can answer a keyword search. CrossRef is enrichment- and
# backward-snowball-only, so it is not a valid `search` target.
SEARCHABLE = [
    "arxiv",
    "ieee",
    "openalex",
    "pubmed",
    "scopus",
    "semantic_scholar",
    "wos",
]
# Databases usable for enrichment and single-paper lookup.
ENRICHABLE = [*SEARCHABLE, "crossref", "web_scraping"]
# Databases that can drive snowball BFS.
SNOWBALLABLE = ["crossref", "openalex", "semantic_scholar"]
# Databases that can answer a similarity query.
SIMILARABLE = ["semantic_scholar", "pubmed", "openalex"]

KEY_ENV = {
    "ieee": "FINDPAPERS_IEEE_API_TOKEN",
    "scopus": "FINDPAPERS_SCOPUS_API_TOKEN",
    "wos": "FINDPAPERS_WOS_API_TOKEN",
}


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def build_engine() -> Any:
    """Construct an Engine. Keys and email come from FINDPAPERS_* env vars."""
    return findpapers.Engine()


def available_databases(requested: list[str] | None) -> list[str]:
    """Resolve the database list, dropping key-gated ones with no key set.

    findpapers raises MissingApiKeyError for a database it cannot authenticate,
    which would abort a whole sweep. Filtering here keeps a partial sweep
    working and lets the run summary say what was skipped and why.
    """
    dbs = list(requested) if requested else list(SEARCHABLE)
    return [db for db in dbs if db not in KEY_ENV or os.environ.get(KEY_ENV[db])]


def skipped_for_keys(requested: list[str] | None) -> list[str]:
    """Databases dropped from this run because their API key is not set."""
    dbs = list(requested) if requested else list(SEARCHABLE)
    return [db for db in dbs if db in KEY_ENV and not os.environ.get(KEY_ENV[db])]


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

_ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([\w.\-/]+?)(?:v\d+)?(?:\.pdf)?$", re.I)


def _extract_arxiv_id(*urls: str | None) -> str | None:
    """Pull a bare arXiv ID out of any arxiv.org URL.

    findpapers has no arxiv_id field, but the deep skill's deep_ops.py fetches
    arXiv PDFs from the `eprint` field of a .bib entry, so the ID has to
    survive into the BibTeX.
    """
    for url in urls:
        if not url:
            continue
        m = _ARXIV_RE.search(url.strip())
        if m:
            return m.group(1)
    return None


def normalise(paper: Any) -> dict[str, Any]:
    """Map a findpapers Paper onto the schema in this module's docstring."""
    source = getattr(paper, "source", None)
    pub_date = getattr(paper, "publication_date", None)
    paper_type = getattr(paper, "paper_type", None)
    url = getattr(paper, "url", None)
    pdf_url = getattr(paper, "pdf_url", None)

    return {
        "title": (getattr(paper, "title", "") or "").strip(),
        "authors": [
            {"name": a.name, "affiliation": getattr(a, "affiliation", None)}
            for a in (getattr(paper, "authors", None) or [])
            if getattr(a, "name", None)
        ],
        "year": pub_date.year if pub_date else None,
        "venue": getattr(source, "title", None) if source else None,
        "publisher": getattr(source, "publisher", None) if source else None,
        "issn": getattr(source, "issn", None) if source else None,
        "doi": (getattr(paper, "doi", None) or "").lower() or None,
        "arxiv_id": _extract_arxiv_id(url, pdf_url),
        "url": url,
        "open_access_pdf_url": pdf_url,
        "abstract": getattr(paper, "abstract", None) or None,
        "citation_count": getattr(paper, "citations", None),
        "keywords": sorted(getattr(paper, "keywords", None) or []),
        "entry_type": getattr(paper_type, "value", None),
        "is_open_access": getattr(paper, "is_open_access", None),
        "is_retracted": getattr(paper, "is_retracted", None),
        "language": getattr(paper, "language", None),
        "references": list(getattr(paper, "references", None) or []),
        "cited_by": list(getattr(paper, "cited_by", None) or []),
        "sources": sorted(getattr(paper, "found_in", None) or []),
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def emit(records: list[dict[str, Any]]) -> None:
    json.dump(records, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def summarise(
    label: str,
    records: list[dict[str, Any]],
    *,
    queried: list[str] | None = None,
    failed: list[str] | None = None,
    key_skipped: list[str] | None = None,
    runtime: float | None = None,
    extra: str | None = None,
) -> None:
    """Write the run summary to stderr.

    findpapers silently drops a database that cannot express a query's filter
    code or wildcard, so 'how many papers came back' is not interpretable
    without knowing which databases actually answered. Read this, do not assume.
    """
    per_db = Counter(src for r in records for src in r["sources"])
    retracted = sum(1 for r in records if r.get("is_retracted"))
    lines = [f"# {label}: {len(records)} papers"]
    if queried:
        lines.append(f"#   requested:  {', '.join(queried)}")
    if per_db:
        lines.append(
            "#   answered:   "
            + ", ".join(f"{db}={n}" for db, n in sorted(per_db.items()))
        )
    silent = sorted(set(queried or []) - set(per_db)) if queried else []
    if silent:
        lines.append(
            f"#   no results: {', '.join(silent)}"
            "  (no matches; on a search, also suspect an unsupported"
            " filter code or wildcard)"
        )
    if failed:
        lines.append(f"#   FAILED:     {', '.join(failed)}")
    if key_skipped:
        lines.append(
            f"#   no API key: {', '.join(key_skipped)}"
            "  (set FINDPAPERS_*_API_TOKEN to include)"
        )
    if retracted:
        lines.append(f"#   RETRACTED:  {retracted} paper(s) flagged is_retracted")
    if runtime is not None:
        lines.append(f"#   runtime:    {runtime:.1f}s")
    if extra:
        lines.append(f"#   {extra}")
    print("\n".join(lines), file=sys.stderr)


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


def resolve_dates(args: argparse.Namespace) -> tuple[Any, Any]:
    """Turn --year-from/--year-to/--since/--until into date bounds."""
    since = until = None
    if getattr(args, "since", None):
        since = datetime.date.fromisoformat(args.since)
    elif getattr(args, "year_from", None):
        since = datetime.date(args.year_from, 1, 1)
    if getattr(args, "until", None):
        until = datetime.date.fromisoformat(args.until)
    elif getattr(args, "year_to", None):
        until = datetime.date(args.year_to, 12, 31)
    return since, until


# ---------------------------------------------------------------------------
# BibTeX generation
# ---------------------------------------------------------------------------

_CITEKEY_STOP = {
    "a", "an", "the", "of", "on", "in", "for", "to", "and", "or", "with",
    "by", "from", "via", "using", "towards", "toward", "into", "as", "at",
    "is", "are", "be", "this", "that", "we", "our",
}


def make_citekey(record: dict[str, Any], existing: set[str]) -> str:
    """authorYEARword, lowercase alnum, disambiguated against existing keys.

    Carried over unchanged from the pre-findpapers script: citekeys are a hard
    contract with deep.bib, the summaries, and the user's manuscript.
    """
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


_PROCEEDINGS_HINTS = (
    "conference", "proceedings", "symposium", "workshop", "neurips", "icml",
    "iclr", "cdc", "acc", "icra", "iros", "rss", "corl", "l4dc",
)


def _entry_type(record: dict[str, Any]) -> str:
    """BibTeX entry type. findpapers' paper_type wins; heuristic is the fallback."""
    declared = (record.get("entry_type") or "").strip().lower()
    if declared:
        return declared
    venue = (record.get("venue") or "").lower()
    if not venue or venue == "arxiv":
        return "misc"
    if any(kw in venue for kw in _PROCEEDINGS_HINTS):
        return "inproceedings"
    return "article"


def to_bibtex_entry(
    record: dict[str, Any], citekey: str, annote: str | None = None
) -> str:
    """Render one BibTeX entry. abstract -> `abstract`, summary -> `annote`."""
    entry_type = _entry_type(record)

    fields: list[tuple[str, str]] = []
    authors = " and ".join(
        a["name"] for a in (record.get("authors") or []) if a.get("name")
    )
    if authors:
        fields.append(("author", _bib_escape(authors)))
    if record.get("title"):
        fields.append(("title", "{" + _bib_escape(record["title"]) + "}"))
    venue = record.get("venue")
    if venue and entry_type in ("inproceedings", "incollection", "inbook"):
        fields.append(("booktitle", _bib_escape(venue)))
    elif venue and entry_type == "article":
        fields.append(("journal", _bib_escape(venue)))
    elif venue and venue.lower() != "arxiv":
        fields.append(("howpublished", _bib_escape(venue)))
    if record.get("publisher"):
        fields.append(("publisher", _bib_escape(record["publisher"])))
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
    if record.get("is_retracted"):
        # Loud on purpose: a retracted paper must not be cited by accident.
        fields.append(("note", "{RETRACTED -- flagged by findpapers enrichment}"))
    elif entry_type == "unpublished":
        # @unpublished requires a note in the standard styles; preprints
        # (arXiv and friends) come back from findpapers as `unpublished`.
        fields.append(("note", "{Preprint}"))
    if annote:
        fields.append(("annote", "{" + _bib_escape(annote) + "}"))

    lines = [f"@{entry_type}{{{citekey},"]
    for k, v in fields:
        lines.append(f"  {k} = {{{v}}}," if not v.startswith("{") else f"  {k} = {v},")
    lines.append("}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def _cmd_search(args: argparse.Namespace) -> None:
    since, until = resolve_dates(args)
    dbs = available_databases(args.databases)
    if not dbs:
        sys.exit("discover.py: no searchable databases available (check API keys)")
    engine = build_engine()
    result = engine.search(
        args.query,
        databases=dbs,
        max_papers_per_database=args.limit,
        since=since,
        until=until,
        num_workers=args.workers,
        show_progress=False,
        enrichment_databases=[] if args.no_enrich else None,
    )
    records = [normalise(p) for p in result.papers]
    emit(records)
    summarise(
        f"search {args.query!r}",
        records,
        queried=dbs,
        failed=list(getattr(result, "failed_databases", None) or []),
        key_skipped=skipped_for_keys(args.databases),
        runtime=getattr(result, "runtime_seconds", None),
    )


def _seed_paper(engine: Any, identifier: str) -> Any:
    """Resolve a DOI or URL to a Paper, or exit with a useful message."""
    paper = engine.get(identifier)
    if paper is None:
        sys.exit(f"discover.py: could not resolve {identifier!r} to a paper")
    if not getattr(paper, "doi", None):
        sys.exit(
            f"discover.py: {identifier!r} resolved to a paper with no DOI; "
            "snowball and similar both require one"
        )
    return paper


def _cmd_get(args: argparse.Namespace) -> None:
    engine = build_engine()
    paper = engine.get(args.id, databases=args.databases)
    if paper is None:
        sys.exit(f"discover.py: no paper found for {args.id!r}")
    records = [normalise(paper)]
    emit(records)
    summarise(f"get {args.id}", records)


def _cmd_snowball(args: argparse.Namespace) -> None:
    since, until = resolve_dates(args)
    engine = build_engine()
    seed = _seed_paper(engine, args.id)
    result = engine.snowball(
        seed,
        max_depth=args.max_depth,
        direction=args.direction,
        max_papers_per_level=args.max_papers_per_level,
        max_expansion_per_level=args.max_expansion_per_level,
        databases=args.databases,
        since=since,
        until=until,
        num_workers=args.workers,
        show_progress=False,
    )
    papers = list(result.papers)
    if args.include_seed:
        papers.insert(0, result.seed_paper)
    records = [normalise(p) for p in papers]
    emit(records)
    summarise(
        f"snowball {args.direction} depth={args.max_depth} from {args.id}",
        records,
        extra=f"seed: {(seed.title or '')[:70]!r}",
    )


def _cmd_similar(args: argparse.Namespace) -> None:
    since, until = resolve_dates(args)
    engine = build_engine()
    seed = _seed_paper(engine, args.id)
    result = engine.similar(
        seed,
        databases=args.databases,
        max_papers_per_database=args.limit,
        since=since,
        until=until,
        num_workers=args.workers,
        show_progress=False,
    )
    records = [normalise(p) for p in result.papers]
    emit(records)
    summarise(
        f"similar to {args.id}",
        records,
        queried=args.databases or ["semantic_scholar", "pubmed"],
        extra=f"seed: {(seed.title or '')[:70]!r}",
    )


def _cmd_download(args: argparse.Namespace) -> None:
    """Best-effort PDF fetch for one paper, saved as <name>.pdf.

    findpapers tries every URL it knows for the paper and follows HTML landing
    pages to resolve the real PDF link. It does not defeat authentication: a
    paywalled paper simply fails, and belongs in the deep skill's requests.md.
    """
    engine = build_engine()
    paper = engine.get(args.id)
    if paper is None:
        sys.exit(f"discover.py: no paper found for {args.id!r}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in out_dir.glob("*.pdf")}

    metrics = engine.download(
        [paper], str(out_dir), timeout=args.timeout, show_progress=False
    )
    new = sorted(p for p in out_dir.glob("*.pdf") if p.name not in before)

    if not new:
        print(
            f"# download {args.id}: FAILED (no PDF retrieved); "
            f"see {out_dir / 'download_log.txt'}",
            file=sys.stderr,
        )
        sys.exit(1)

    # findpapers names files YEAR-title.pdf; the skills index PDFs by citekey.
    target = out_dir / f"{args.name}.pdf"
    if target.exists() and target.resolve() != new[0].resolve():
        target.unlink()
    new[0].rename(target)
    for extra in new[1:]:
        extra.unlink()

    print(
        f"# download {args.id}: ok -> {target} "
        f"({metrics.get('runtime_in_seconds', 0):.1f}s)",
        file=sys.stderr,
    )
    print(str(target))


def _cmd_to_bibtex(args: argparse.Namespace) -> None:
    """Read JSON records from stdin or --input; write BibTeX to stdout.

    Each record may carry an optional `citekey` and `annote`; otherwise a
    citekey is generated and annote is omitted.
    """
    raw = Path(args.input).read_text() if args.input else sys.stdin.read()
    records = json.loads(raw)
    if not isinstance(records, list):
        records = [records]

    existing: set[str] = set()
    if args.existing_bib and Path(args.existing_bib).exists():
        text = Path(args.existing_bib).read_text()
        for m in re.finditer(r"^@\w+\{([^,]+),", text, re.MULTILINE):
            existing.add(m.group(1).strip())

    out_entries: list[str] = []
    for r in records:
        key = r.get("citekey") or make_citekey(r, existing)
        existing.add(key)
        out_entries.append(to_bibtex_entry(r, key, r.get("annote")))
    sys.stdout.write("\n\n".join(out_entries) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="subcommand", required=True)

    def add_dates(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--year-from", type=int, help="Include papers from this year on.")
        sp.add_argument("--year-to", type=int, help="Include papers up to this year.")
        sp.add_argument("--since", help="Exact lower bound, YYYY-MM-DD.")
        sp.add_argument("--until", help="Exact upper bound, YYYY-MM-DD.")

    ps = sub.add_parser(
        "search",
        help="Boolean query across every available database.",
        description=(
            "Bracket every term: '[safe reinforcement learning] AND ([CBF] OR "
            "[Lyapunov])'. An unbracketed string is one literal phrase."
        ),
    )
    ps.add_argument("query")
    ps.add_argument("--limit", type=int, default=25, help="Max papers per database.")
    ps.add_argument(
        "--databases", nargs="+", choices=SEARCHABLE,
        help=f"Default: all of {', '.join(SEARCHABLE)} that have a key.",
    )
    ps.add_argument("--workers", type=int, default=4, help="Parallel database workers.")
    ps.add_argument(
        "--no-enrich", action="store_true",
        help="Skip CrossRef/scraping enrichment (faster, loses retraction and OA flags).",
    )
    add_dates(ps)
    ps.set_defaults(func=_cmd_search)

    pg = sub.add_parser("get", help="Fetch one paper by DOI or landing-page URL.")
    pg.add_argument("id")
    pg.add_argument("--databases", nargs="+", choices=ENRICHABLE)
    pg.set_defaults(func=_cmd_get)

    pn = sub.add_parser(
        "snowball",
        help="Citation traversal from a seed DOI.",
        description=(
            "Replaces the old refs/cites subcommands: use --direction backward "
            "for references, forward for citations, both for a full sweep."
        ),
    )
    pn.add_argument("id", help="Seed DOI or landing-page URL. Must resolve to a DOI.")
    pn.add_argument(
        "--direction", choices=["both", "backward", "forward"], default="both"
    )
    pn.add_argument("--max-depth", type=int, default=1)
    pn.add_argument(
        "--max-papers-per-level", type=int, default=100,
        help="Keep only the N most-cited papers per level. Default 100.",
    )
    pn.add_argument(
        "--max-expansion-per-level", type=int,
        help="Only expand the N most-cited papers into the next level.",
    )
    pn.add_argument("--databases", nargs="+", choices=SNOWBALLABLE)
    pn.add_argument("--workers", type=int, default=4)
    pn.add_argument(
        "--include-seed", action="store_true",
        help="Include the seed paper in the output (excluded by default).",
    )
    add_dates(pn)
    pn.set_defaults(func=_cmd_snowball)

    pm = sub.add_parser("similar", help="Content-similar papers around a seed DOI.")
    pm.add_argument("id", help="Seed DOI or landing-page URL. Must resolve to a DOI.")
    pm.add_argument("--limit", type=int, help="Max papers per source before merging.")
    pm.add_argument(
        "--databases", nargs="+", choices=SIMILARABLE,
        help="Default: semantic_scholar, pubmed. openalex is noisier, opt in.",
    )
    pm.add_argument("--workers", type=int, default=4)
    add_dates(pm)
    pm.set_defaults(func=_cmd_similar)

    pd = sub.add_parser(
        "download",
        help="Best-effort PDF fetch for one paper, saved as <name>.pdf.",
        description="Does not defeat authentication; paywalled papers just fail.",
    )
    pd.add_argument("id", help="DOI or landing-page URL.")
    pd.add_argument("--name", required=True, help="Citekey; the PDF is <name>.pdf.")
    pd.add_argument("--out", default="lit_review/pdfs", help="Output directory.")
    pd.add_argument("--timeout", type=float, default=30.0)
    pd.set_defaults(func=_cmd_download)

    pb = sub.add_parser("to-bibtex", help="Convert JSON records to BibTeX entries.")
    pb.add_argument("--input", help="JSON file; default stdin.")
    pb.add_argument(
        "--existing-bib", help="Existing .bib; used to avoid citekey collisions."
    )
    pb.set_defaults(func=_cmd_to_bibtex)

    return p


def main() -> None:
    args = build_parser().parse_args()
    try:
        args.func(args)
    except findpapers.QueryValidationError as e:
        sys.exit(
            f"discover.py: invalid query -- {e}\n"
            "Terms must be bracketed: '[term a] AND ([term b] OR [term c])'."
        )
    except findpapers.MissingApiKeyError as e:
        sys.exit(f"discover.py: {e}\nSet the key in ~/.config/lit-review/findpapers.env")
    except findpapers.FindpapersError as e:
        sys.exit(f"discover.py: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
