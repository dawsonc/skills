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

Before doing anything else, read `lit_review/scope.md`. If it does not exist,
stop and tell the user to run the lit-review-scoping skill first. The wide
search keyword clusters, subtopic taxonomy, and in/out-of-scope rules all live
there.

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

`scripts/discover.py` does all the API work: keyword search across Semantic
Scholar, OpenAlex, and arXiv (deduplicated), citation chasing in both
directions, and JSON→BibTeX conversion. Stdlib only; APIs are keyless.

Subcommands you will use:

```bash
# Search by query. Combines all three sources, deduplicated.
python ${CLAUDE_SKILL_DIR}/scripts/discover.py keyword "safe reinforcement learning Lyapunov" \
    --year-from 2018 --limit 25

# Backward references (works the paper cites).
python ${CLAUDE_SKILL_DIR}/scripts/discover.py refs 10.1109/CDC.2018.8619252 --limit 100

# Forward citations (works that cite the paper).
python ${CLAUDE_SKILL_DIR}/scripts/discover.py cites 10.1109/CDC.2018.8619252 --limit 100

# Lookup a single paper by DOI or arXiv ID.
python ${CLAUDE_SKILL_DIR}/scripts/discover.py lookup 2006.16236

# Convert JSON records (optionally with an `annote` field added) to BibTeX,
# avoiding citekey collisions with an existing .bib file.
cat filtered.json | python ${CLAUDE_SKILL_DIR}/scripts/discover.py to-bibtex \
    --existing-bib lit_review/wide.bib >> lit_review/wide.bib
```

Read the script's docstring (`head -50 scripts/discover.py`) if you need the
output schema. Records carry `doi`, `arxiv_id`, `s2_id`, `openalex_id`,
`abstract`, `citation_count`, `open_access_pdf_url`, and a `sources` list.

The script's BibTeX entry-type heuristic (`@article` vs `@inproceedings` vs
`@misc`) is good but not perfect — source APIs do not reliably distinguish
journal from conference. Spot-check the first few entries before committing
to `wide.bib`; flip types by hand where obviously wrong.

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

For an initial build, take each keyword cluster from scope.md and turn it
into one or two `discover.py keyword` invocations. For follow-ups, write the
specific queries you intend to run.

Tell the user the plan briefly before executing — a 4-line summary, not a
table. They will catch obvious gaps faster than you will.

Best-practice habits:

- **Use multiple sources.** Default `--sources s2 openalex arxiv`. Single-
  source results miss systematically — S2's index is patchy for niche venues;
  OpenAlex picks up grey literature; arXiv catches preprints S2 has not
  ingested yet.
- **Run synonym variants separately.** "Safe RL" and "constrained policy
  optimization" surface different papers even though the topic is the same.
  Each scope.md cluster usually expands to several queries.
- **Cite-chase from seed papers** named in scope.md. Backward refs catch
  foundational work the keywords miss; forward cites catch recent extensions.
- **Date filters.** Use `--year-from` to constrain to the relevant window when
  the user has specified one. Otherwise leave it open — older foundational
  work matters.

### 3. Filter against scope.md

The raw JSON from `discover.py` is candidates, not includes. Apply scope.md's
in/out rules: drop papers outside the topical or temporal boundaries, drop
duplicates of papers already in wide.bib (the script dedupes across one call,
not against the existing .bib — check by DOI / arXiv ID / title).

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
2. Run `discover.py to-bibtex --input tmp.json --existing-bib
   lit_review/wide.bib >> lit_review/wide.bib`.
3. Spot-check the resulting entries; fix entry types if needed.
4. Delete the temp JSON.

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
- `discover.py keyword "safe reinforcement learning Lyapunov" --year-from 2018`
  - returned: 25, new: 19, dropped (out of scope): 4
- `discover.py keyword "constrained policy optimization" --year-from 2018`
  - returned: 18, new: 12, dropped (out of scope): 2
```

"New" = not already in `wide.bib` before this run. Track this so the
saturation check has data.

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
- Download paywalled content. The script reports `open_access_pdf_url` when
  available; that is all.
- Decide what to write a paper about. It surfaces what exists; judgment about
  novelty and gaps is the deep skill's job and ultimately the user's.
