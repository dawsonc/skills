#!/usr/bin/env python3
"""deep_ops.py — operations specific to the deep literature review.

Subcommands:
  promote   Copy nominated BibTeX entries from wide.bib to deep.bib.
  acquire   Try to download the PDF for a citekey; report what worked / failed.
  status    Scan deep.bib and report which citekeys have / lack a local PDF.
  request   Emit (or refresh) a requests.md row for a citekey that needs manual
            fetching.

PDF acquisition is best-effort against open sources only:
  - arXiv (https://arxiv.org/pdf/<id>.pdf)
  - OpenReview (https://openreview.net/pdf?id=<id>) when the entry url points
    to OpenReview
  - Any url field that ends in .pdf and resolves to a PDF content-type

The script never attempts to bypass paywalls. Closed-access papers are routed
to requests.md.

Stdlib only.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

UA = "lit-review-skill/1.0"


# ---------------------------------------------------------------------------
# Minimal BibTeX parsing
# ---------------------------------------------------------------------------


def parse_bib(text: str) -> list[dict[str, Any]]:
    """Parse a .bib file into a list of entry dicts.

    Handles the entry shapes produced by discover.py and most hand-written
    BibTeX (braces-balanced values, double-quoted values, simple comments).
    Does NOT handle @string macros or @preamble. Comments outside entries are
    ignored.

    Returns a list of {"type": str, "key": str, "fields": dict[str,str],
                       "raw": str (verbatim source)}.
    """
    entries: list[dict[str, Any]] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "@":
            i += 1
            continue
        start = i
        m = re.match(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text[i:])
        if not m:
            i += 1
            continue
        etype = m.group(1).lower()
        if etype in ("string", "preamble", "comment"):
            # Skip these — minimal support.
            i += m.end()
            continue
        ekey = m.group(2)
        i += m.end()
        fields: dict[str, str] = {}
        # Parse fields until matching closing brace of the entry.
        depth = 1
        while i < n and depth > 0:
            # Skip whitespace and commas.
            while i < n and text[i] in " \t\r\n,":
                i += 1
            if i >= n:
                break
            if text[i] == "}":
                depth -= 1
                i += 1
                break
            # Parse "fieldname = value".
            fm = re.match(r"(\w+)\s*=\s*", text[i:])
            if not fm:
                # Malformed — skip rest of entry.
                while i < n and text[i] != "}":
                    i += 1
                if i < n:
                    i += 1
                depth = 0
                break
            fname = fm.group(1).lower()
            i += fm.end()
            value, i = _read_bib_value(text, i)
            fields[fname] = value
        entries.append({
            "type": etype, "key": ekey, "fields": fields,
            "raw": text[start:i],
        })
    return entries


def _read_bib_value(text: str, i: int) -> tuple[str, int]:
    """Read one BibTeX value starting at index i; returns (value, new_index)."""
    n = len(text)
    if i >= n:
        return "", i
    ch = text[i]
    if ch == "{":
        # Brace-balanced value.
        depth = 1
        i += 1
        start = i
        while i < n and depth > 0:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        value = text[start:i]
        if i < n:
            i += 1  # consume closing brace
        return value, i
    elif ch == '"':
        i += 1
        start = i
        while i < n and text[i] != '"':
            i += 1
        value = text[start:i]
        if i < n:
            i += 1
        return value, i
    else:
        # Bare token (number, citekey) — read until comma or whitespace.
        start = i
        while i < n and text[i] not in ",}\r\n":
            i += 1
        return text[start:i].strip(), i


def find_entry(entries: list[dict[str, Any]], citekey: str) -> dict[str, Any] | None:
    for e in entries:
        if e["key"] == citekey:
            return e
    return None


# ---------------------------------------------------------------------------
# promote
# ---------------------------------------------------------------------------


def _cmd_promote(args: argparse.Namespace) -> None:
    """Copy wide.bib entries with the given citekeys into deep.bib."""
    with open(args.wide) as f:
        wide_entries = parse_bib(f.read())
    existing_keys: set[str] = set()
    if os.path.exists(args.deep):
        with open(args.deep) as f:
            existing_keys = {e["key"] for e in parse_bib(f.read())}

    promoted: list[str] = []
    skipped_existing: list[str] = []
    not_found: list[str] = []
    for ck in args.citekeys:
        if ck in existing_keys:
            skipped_existing.append(ck)
            continue
        entry = find_entry(wide_entries, ck)
        if not entry:
            not_found.append(ck)
            continue
        with open(args.deep, "a") as f:
            if os.path.getsize(args.deep) > 0:
                f.write("\n\n")
            f.write(entry["raw"].rstrip())
            f.write("\n")
        promoted.append(ck)
        existing_keys.add(ck)

    report = {
        "promoted": promoted,
        "skipped_already_in_deep": skipped_existing,
        "not_found_in_wide": not_found,
    }
    import json
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")


# ---------------------------------------------------------------------------
# acquire
# ---------------------------------------------------------------------------


def _try_download(url: str, dest: str, timeout: int = 60) -> tuple[bool, str]:
    """Download a URL to dest if it serves a PDF. Returns (ok, message)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            data = resp.read()
        if "pdf" not in ctype and not data.startswith(b"%PDF"):
            return False, f"not a PDF (Content-Type: {ctype})"
        with open(dest, "wb") as f:
            f.write(data)
        return True, f"saved {len(data)} bytes from {url}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code} on {url}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _candidate_urls(fields: dict[str, str]) -> list[tuple[str, str]]:
    """Return (label, url) candidates to try, in priority order."""
    out: list[tuple[str, str]] = []
    eprint = fields.get("eprint") or ""
    if eprint:
        out.append(("arxiv", f"https://arxiv.org/pdf/{eprint}.pdf"))
    url = fields.get("url") or ""
    if url:
        if "openreview.net" in url:
            m = re.search(r"id=([\w\-]+)", url)
            if m:
                out.append(("openreview", f"https://openreview.net/pdf?id={m.group(1)}"))
        if "arxiv.org/abs/" in url and not eprint:
            m = re.search(r"arxiv\.org/abs/([\w.\-/]+)", url)
            if m:
                out.append(("arxiv", f"https://arxiv.org/pdf/{m.group(1)}.pdf"))
        if url.lower().endswith(".pdf"):
            out.append(("url-pdf", url))
    return out


def _cmd_acquire(args: argparse.Namespace) -> None:
    """Try to download a PDF for the given citekey."""
    with open(args.deep) as f:
        entries = parse_bib(f.read())
    entry = find_entry(entries, args.citekey)
    if not entry:
        print(f"error: {args.citekey} not in {args.deep}", file=sys.stderr)
        sys.exit(2)

    os.makedirs(args.pdfs_dir, exist_ok=True)
    dest = os.path.join(args.pdfs_dir, f"{args.citekey}.pdf")
    if os.path.exists(dest) and not args.force:
        print(f"already have {dest}")
        return

    candidates = _candidate_urls(entry["fields"])
    if not candidates:
        print(f"no open-access candidates for {args.citekey}; route to requests.md")
        sys.exit(1)

    for label, url in candidates:
        ok, msg = _try_download(url, dest)
        print(f"[{label}] {msg}")
        if ok:
            return
    print(f"all candidates failed for {args.citekey}; route to requests.md")
    sys.exit(1)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def _cmd_status(args: argparse.Namespace) -> None:
    """Report which deep.bib citekeys have a PDF locally."""
    with open(args.deep) as f:
        entries = parse_bib(f.read())
    have: list[str] = []
    missing: list[str] = []
    for e in entries:
        pdf_path = os.path.join(args.pdfs_dir, f"{e['key']}.pdf")
        if os.path.exists(pdf_path):
            have.append(e["key"])
        else:
            missing.append(e["key"])
    import json
    json.dump({"have_pdf": have, "missing_pdf": missing,
               "total": len(entries)}, sys.stdout, indent=2)
    sys.stdout.write("\n")


# ---------------------------------------------------------------------------
# request
# ---------------------------------------------------------------------------


REQUEST_HEADER = (
    "# PDF Requests\n\n"
    "Papers below could not be auto-downloaded. Once you have placed a PDF in\n"
    "`lit_review/pdfs/<citekey>.pdf`, remove the row (or strike it through).\n\n"
)

REQUEST_TABLE_HEADER = (
    "| citekey | title | best link | DOI | venue |\n"
    "|---------|-------|-----------|-----|-------|\n"
)


def _cmd_request(args: argparse.Namespace) -> None:
    """Add (or refresh) a row for citekey in requests.md."""
    with open(args.deep) as f:
        entries = parse_bib(f.read())
    entry = find_entry(entries, args.citekey)
    if not entry:
        print(f"error: {args.citekey} not in {args.deep}", file=sys.stderr)
        sys.exit(2)
    f_ = entry["fields"]
    title = f_.get("title", "").strip("{}")
    doi = f_.get("doi", "")
    venue = f_.get("journal") or f_.get("booktitle", "")
    link = f_.get("url") or (f"https://doi.org/{doi}" if doi else "")

    path = args.requests
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, "w") as f:
            f.write(REQUEST_HEADER)
            f.write(REQUEST_TABLE_HEADER)

    with open(path) as f:
        body = f.read()
    if f"| `{args.citekey}` |" in body:
        print(f"{args.citekey} already in {path}")
        return

    row = (f"| `{args.citekey}` | {title} | "
           f"{('[' + link + '](' + link + ')') if link else '—'} | "
           f"{doi or '—'} | {venue or '—'} |\n")
    with open(path, "a") as f:
        f.write(row)
    print(f"added {args.citekey} to {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="subcommand", required=True)

    pr = sub.add_parser("promote", help="Copy citekeys from wide.bib into deep.bib.")
    pr.add_argument("citekeys", nargs="+")
    pr.add_argument("--wide", default="lit_review/wide.bib")
    pr.add_argument("--deep", default="lit_review/deep.bib")
    pr.set_defaults(func=_cmd_promote)

    pa = sub.add_parser("acquire", help="Try to download a PDF for one citekey.")
    pa.add_argument("citekey")
    pa.add_argument("--deep", default="lit_review/deep.bib")
    pa.add_argument("--pdfs-dir", default="lit_review/pdfs")
    pa.add_argument("--force", action="store_true",
                    help="Re-download even if a PDF already exists.")
    pa.set_defaults(func=_cmd_acquire)

    ps = sub.add_parser("status", help="List which deep.bib citekeys have a PDF.")
    ps.add_argument("--deep", default="lit_review/deep.bib")
    ps.add_argument("--pdfs-dir", default="lit_review/pdfs")
    ps.set_defaults(func=_cmd_status)

    pq = sub.add_parser("request", help="Add citekey to requests.md.")
    pq.add_argument("citekey")
    pq.add_argument("--deep", default="lit_review/deep.bib")
    pq.add_argument("--requests", default="lit_review/requests.md")
    pq.set_defaults(func=_cmd_request)

    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
