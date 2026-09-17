---
name: lit-review-wide
description: >-
  Build and maintain a broad literature long-list for a research review. Use
  this whenever the user wants to cast a wide net on the literature — phrases
  like "find me papers on...", "do a broad search for...", "build a long-list
  on...", "what's been published on...", "expand the related work on...", or
  "follow up on <subtopic>" in an existing review context. The skill maintains
  lit_review/wide.bib (one BibTeX entry per paper, with a 1–2 sentence summary
  in the `annote` field) and lit_review/summary_wide.md (thematic summary
  organised by the subtopic taxonomy in scope.md). It also logs every query to
  lit_review/search_log.md and runs a saturation check so the user knows when
  further searching is yielding diminishing returns. PREREQUISITE: lit_review/
  scope.md must exist (produced by the lit-review-scoping skill); if it does
  not, point the user there first rather than guessing at scope. Do NOT use
  this skill for detailed per-paper synthesis (that is lit-review-deep), for
  reading a single paper, or for citation formatting in a manuscript.
---

# Wide Literature Review

This skill builds and grows `lit_review/wide.bib` and `lit_review/summary_wide.md`
— a long-list of relevant papers with short annotations and a thematic overview.
It is the second of three skills: scoping → **wide** → deep.

The user is a PhD-level researcher in CS / ML / control / robotics. Your job
is breadth and disciplined bookkeeping. Aim to surface what is out there
(including emerging work and adjacent-field analogues), apply scope.md's
inclusion criteria honestly, and produce annotations a busy domain expert can
scan without re-reading abstracts.

## Prerequisites

Two things must be in place before any searching.

**1. `lit_review/scope.md`.** Read it. If it does not exist, stop and tell the
user to run the lit-review-scoping skill first. The wide search keyword
clusters, subtopic taxonomy, and in/out-of-scope rules all live there.

**2. The pinned findpapers install.** Check it in one call:

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/run.sh --check
```

That prints the installed version, where it resolved from, and which API keys
are present. If it exits non-zero the venv is missing: tell the user to run
`bash ${CLAUDE_SKILL_DIR}/scripts/bootstrap.sh` once, and wait. Do not install
it yourself mid-search, and never `pip install` from git at invocation time —
the version in use is pinned to a single commit in `scripts/findpapers.pin`
deliberately, so that what runs today is what was reviewed.

## Folder contract

```
lit_review/
  scope.md          # input (read-only here)
  wide.bib          # OWNED HERE: BibTeX long-list with `annote` summaries
  summary_wide.md   # OWNED HERE: thematic summary, sectioned per scope taxonomy
  search_log.md     # OWNED HERE: append-only log of queries
  pdfs/             # used by lit-review-deep; ignore here
  requests.md       # used by lit-review-deep; ignore here
```

**Citekey convention:** `authorYEARword` — first author's surname (lowercase,
alphanumeric only), four-digit year, first non-stopword content word of the
title. Example: `coulom2006mcts`, `kingma2014adam`. Disambiguate collisions
with a trailing letter (`smith2020learninga`, `smith2020learningb`). The
bundled script generates these deterministically; do not regenerate keys for
papers already in `wide.bib` — they must remain stable so the deep skill and
the user's manuscript can rely on them.

## The bundled discovery script

`scripts/discover.py` does all the API work, bridging to
[findpapers](https://github.com/jonatasgrosman/findpapers). One query reaches
eight databases, deduplicated across them: arXiv, CrossRef, IEEE Xplore,
OpenAlex, PubMed, Scopus, Semantic Scholar, Web of Science. It also does
citation traversal, content-similarity lookup, and JSON→BibTeX conversion.

Always invoke it through `run.sh`, which selects the pinned interpreter and
loads API keys from `~/.config/lit-review/findpapers.env`:

```bash
# Boolean search across every database that has a key.
bash ${CLAUDE_SKILL_DIR}/scripts/run.sh discover.py search \
    '[safe reinforcement learning] AND ([Lyapunov] OR [control barrier function])' \
    --year-from 2018 --limit 25

# One paper, by DOI or landing-page URL.
bash ${CLAUDE_SKILL_DIR}/scripts/run.sh discover.py get 10.1109/CDC.2018.8619252

# Citation traversal. --direction backward = references, forward = citations.
bash ${CLAUDE_SKILL_DIR}/scripts/run.sh discover.py snowball 10.1109/CDC.2018.8619252 \
    --direction backward --max-depth 1 --max-papers-per-level 25

# Content-similar papers around a seed. Uses no keywords at all.
bash ${CLAUDE_SKILL_DIR}/scripts/run.sh discover.py similar 10.1109/CDC.2018.8619252

# JSON records (with the `annote` you wrote) → BibTeX, avoiding citekey
# collisions with an existing .bib file.
bash ${CLAUDE_SKILL_DIR}/scripts/run.sh discover.py to-bibtex \
    --input filtered.json --existing-bib lit_review/wide.bib >> lit_review/wide.bib
```

Write the invocation out in full each time rather than aliasing it into a
shell variable: the user's shell is zsh, which does not word-split an
unquoted `$var`, so `R="bash run.sh discover.py"; $R search ...` fails with
"No such file or directory".

Each record carries `doi`, `arxiv_id`, `abstract`, `citation_count`,
`keywords`, `entry_type`, `is_open_access`, `is_retracted`, `references`,
`cited_by`, and a `sources` list naming the databases the paper was found in.
Read the script's docstring (`head -60 scripts/discover.py`) for the full
schema.

Records go to stdout; a run summary goes to stderr. Keep the two separate
(`> out.json 2> summary.txt`, or let stderr through to your terminal) — the
summary is how you learn which databases actually answered.

### Query syntax is boolean, not free text

This is the easiest thing to get wrong. findpapers translates one bracketed
boolean expression into each database's native syntax, and **a bare
unbracketed string is treated as a single literal phrase** — so
`safe reinforcement learning Lyapunov` searches for that exact phrase and
returns almost nothing. Bracket every term.

Translate each scope.md cluster into canonical form:

```
scope.md:   "backward reachable set" AND (attack OR adversarial) AND "cyber-physical"
findpapers: [backward reachable set] AND ([attack] OR [adversarial]) AND [cyber-physical]
```

- Connectors are `AND`, `OR`, `AND NOT`, with whitespace on both sides.
- Group with parentheses; groups nest.
- Filter codes go before a bracket or a group: `ti` (title), `abs`, `key`
  (keywords), `au`, `src` (venue), `aff`, `tiabs`, `tiabskey`. The innermost
  one wins, so `ti([neural network] OR abs[deep learning])` searches the title
  for one term and the abstract for the other.
- Wildcards: `?` is one character, `*` is zero or more. Never at the start of
  a term, one per term, single-word terms only.

**A database that cannot express your filter code or wildcard is dropped from
the run silently.** Using no filter code at all is the safest default. When
you do use one, read the stderr summary to see who answered instead of
assuming everyone did.

### Which databases answer

| Database | API key | Notes |
|---|---|---|
| arXiv | none needed | preprints; no citation counts |
| CrossRef | none needed | enrichment and backward snowball only — not keyword search |
| OpenAlex | **effectively required** | keyless budget is ~10 requests/day |
| PubMed | optional | biomedical only; 3 → 10 req/s with a key |
| Semantic Scholar | optional | shared anonymous pool without a key |
| IEEE Xplore | required | ~200 req/day |
| Scopus | required | full access needs an institutional network |
| Web of Science | required | free tier is the Starter API, 1 req/s |

A database whose key is missing is dropped from the run and named in the
summary, so a keyless sweep still works — with thinner coverage and a hard
OpenAlex ceiling. If `run.sh --check` reports missing keys and the review
depends on IEEE/Elsevier/Clarivate-indexed venues, say so once and point the
user at `~/.config/lit-review/findpapers.env`. Do not repeat it every run.

## Workflow

### 1. Determine the run mode

Three modes, distinguished by what the user just asked for:

- **Initial build.** wide.bib is empty or absent. Run the full keyword sweep
  from scope.md's clusters.
- **Follow-up.** User asks to expand a particular subtopic ("more on extreme
  value theory", "chase citations from `kingma2014adam`", "anything newer
  than 2023 on this"). Run targeted searches; *add* to wide.bib without
  touching existing entries.
- **Refresh.** User wants a periodic top-up. Re-run the clusters with a
  `--year-from` cutoff matching the last refresh date (read from
  `search_log.md`).

State the chosen mode in one sentence before running anything.

### 2. Plan the searches

For an initial build, translate each keyword cluster from scope.md into one or
two bracketed boolean `search` queries (see Query syntax above). For
follow-ups, write out the specific queries you intend to run.

Tell the user the plan briefly before executing — a 4-line summary, not a
table. They will catch obvious gaps faster than you will.

Best-practice habits:

- **Leave `--databases` unset** unless you have a specific reason. The default
  is every database that has a key, and the summary reports who answered.
- **Let one query carry the synonyms.** `[safe RL] OR [constrained policy
  optimization]` inside a single search covers what used to take two runs.
  Still split them when the synonyms pull genuinely different literatures:
  results are ranked per database, so a rare term can get buried inside a
  large `OR` group.
- **Cite-chase with `snowball`** from the seed papers named in scope.md.
  `--direction backward` catches foundational work the keywords miss, `forward`
  catches recent extensions. Depth grows fast — at `--max-depth 2` always pair
  it with `--max-papers-per-level`.
- **Use `similar` as a vocabulary check.** After the keyword sweep, run it on
  two or three of the most central papers. It uses no keywords at all, so
  whatever it surfaces that your queries missed is telling you your search
  terms are off — feed that back into the next round of queries.
- **Date filters.** Use `--year-from` to constrain to the relevant window when
  the user has specified one. Otherwise leave it open — older foundational
  work matters.

### 3. Filter against scope.md

The raw JSON from `discover.py` is candidates, not includes. Apply scope.md's
in/out rules: drop papers outside the topical or temporal boundaries, drop
duplicates of papers already in wide.bib (the script dedupes across one call,
not against the existing .bib — check by DOI / arXiv ID / title).

**Check `is_retracted` before anything else.** A record flagged `true` is
either dropped or kept with its `annote` opening `RETRACTED:` — never silently
included. Tell the user about every retraction you hit: a retracted paper
sitting in the field's citation graph is worth knowing about whether or not it
enters the review. The flag comes from enrichment, so `null` means unknown,
not clean.

Be honest about borderline cases. If a paper is plausibly relevant but you
are not sure, keep it and flag uncertainty in the `annote`. Better to over-
include in the wide list — the deep skill will prune.

### 4. Write the 1–2 sentence annotations

This is the irreducible Claude work. Each `annote` answers, in one or two
sentences: **what the paper does** and **why it is in this review**.

Good annotations are specific. "Proposes a method for X" is useless; "Proposes
a CBF-based safety filter for nonlinear systems with state-dependent
disturbances; cited as the canonical learning-free baseline" is useful.

If the paper's contribution is unclear from title and abstract, say so —
"abstract is vague; needs full-text read" — rather than confabulating.

Use the paper's `abstract` field (already in each record) as the basis, plus
the venue and citation count for context on its standing in the field.

### 5. Append to wide.bib

Pipe filtered, annotated records through `to-bibtex` and append to
`wide.bib`. Use `--existing-bib lit_review/wide.bib` so generated citekeys do
not collide with what is already there.

Workflow:

1. Save the filtered records (with `annote` fields you wrote) to a temp JSON.
2. Run `run.sh discover.py to-bibtex --input tmp.json --existing-bib
   lit_review/wide.bib >> lit_review/wide.bib`.
3. Spot-check the resulting entries; fix entry types and venues if needed.
4. Delete the temp JSON.

Entry types come from findpapers' `paper_type` rather than a venue-keyword
guess, which is a real improvement but not infallible: venue resolution
sometimes picks an aggregator or repository mirror over the actual
proceedings, and a conference paper then arrives as `@article` with a wrong
`journal` field. Check the `venue` of the first few entries in each batch
against what you know the paper is, and fix by hand.

### 6. Update summary_wide.md

`summary_wide.md` is organised around scope.md's subtopic taxonomy — its
sections are the same as the taxonomy items. For each subtopic that received
new papers in this run:

- Add new papers to the section's paper list, citing by `\cite{citekey}`-
  style reference (use `[@citekey]` if the user works in Markdown; ask once
  and stick with it).
- Update the section's narrative paragraph if the new papers change the
  picture (introduce a new sub-cluster, fill a gap previously noted, etc.).
  Otherwise leave the narrative alone.
- If a new subtopic emerges that the scope.md taxonomy missed, add a section
  named "Unmapped: <topic>" and surface it to the user — it may warrant a
  scope.md revision.

Do not regenerate the whole file. Edit in place. This matters for follow-ups
— the user may have manually annotated sections you should not overwrite.

See the template at the end of this file.

### 7. Log the queries

Append one entry to `search_log.md` per query you ran:

```markdown
## 2026-06-01 — initial build, cluster "safe RL"
- `search '[safe reinforcement learning] AND [Lyapunov]' --year-from 2018`
  - answered: arxiv=9, openalex=12, scopus=4 | no key: ieee, wos
  - returned: 25, new: 19, dropped (out of scope): 4
- `snowball 10.1109/CDC.2018.8619252 --direction backward --max-depth 1`
  - answered: crossref=24
  - returned: 24, new: 11, dropped (out of scope): 13
```

"New" = not already in `wide.bib` before this run. Track this so the
saturation check has data.

Log the databases as well as the counts, copied from the run summary. A sweep
that quietly lost Scopus to an expired key looks exactly like a saturated
field if all you recorded was "returned: 25, new: 3".

### 8. Saturation check

After each cluster (or each follow-up batch), compute the new-paper rate:
`new / returned` across that cluster's queries. Report it explicitly to the
user with a one-line interpretation:

- **>50% new** — early in the search; keep going with this cluster.
- **20–50% new** — middle ground; one or two more synonym variants may help.
- **<20% new** — likely saturated; further keyword searches here will mostly
  resurface known papers. Suggest moving on or switching to citation chasing
  from highly-cited papers found so far.

This is a signal, not a rule. A real field might genuinely saturate at 100
papers or take 500. Tell the user the rate, let them decide.

Before calling saturation, check the per-database counts in the summary for
the cluster. A low new-paper rate concentrated in two databases while three
others returned nothing is a coverage problem, not saturation.

### 9. Hand off

When the user is satisfied with the long-list, point them to the
lit-review-deep skill for detailed synthesis. Mention how many papers are in
`wide.bib` and which subtopics have the thickest coverage / thinnest coverage
— this helps them target the deep dive.

## Working with follow-up requests

The user will return repeatedly with prompts like:

- "More on Lyapunov-based methods."
- "Chase citations from `coulom2006mcts`."
- "Anything from CDC 2024 you missed?"
- "Add a row of preprints from this month."

Treat each as an additive operation. Do not re-run prior queries unless asked.
Do not rewrite annotations or summaries the user (or you, previously) already
produced. Append, log, and update.

If a follow-up surfaces a paper already in `wide.bib`, mention it ("the
citation chase resurfaced `kingma2014adam`, already present") rather than
silently dropping — the user may want to know the paper's centrality.

## summary_wide.md template

```markdown
# Wide Literature Review: <topic>

_Last updated: <YYYY-MM-DD>. Papers: <N>._

## Overview
<3–6 sentences placing the field. What it covers, where the main debates are,
where activity has concentrated recently. Not a paper-by-paper synthesis —
that is for summary_deep.md.>

## <Subtopic 1 from scope.md taxonomy>
<1–2 paragraphs on the shape of this subtopic: methods, factions, recent
trajectory.>

**Papers:**
- `coulom2006mcts` — one-line characterisation.
- `kingma2014adam` — one-line characterisation.
- ...

## <Subtopic 2>
...

## Cross-cutting themes
<Optional. Methods or framings that span multiple subtopics — useful for the
deep synthesis later.>

## Notes
- Subtopics with thin coverage so far: ...
- Open questions surfaced during the search: ...
```

## What this skill does *not* do

- Read full-text PDFs. Annotations are abstract-based; deeper reading is the
  job of lit-review-deep.
- Bypass paywalls. Records report `is_open_access` and an
  `open_access_pdf_url` when one exists; actually fetching PDFs is the deep
  skill's job.
- Install or upgrade its own tooling. findpapers is pinned to one commit and
  installed once by `bootstrap.sh`; if it is missing, say so and stop.
- Decide what to write a paper about. It surfaces what exists; judgment about
  novelty and gaps is the deep skill's job and ultimately the user's.
