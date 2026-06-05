---
name: lit-review-deep
description: >-
  Produce a detailed, full-text-informed synthesis of a chosen subset of
  papers, with per-paper long summaries, a cross-cutting synthesis of how the
  works relate, and an explicit gap analysis. Use this whenever the user wants
  depth on a set of papers — phrases like "do a deep read on...", "synthesise
  these papers", "go deep on the safe RL subset", "what do `kingma2014adam`
  and `loshchilov2017sgdr` actually disagree on", "what's missing in the
  current literature on..." or "promote these to a detailed review". The skill
  maintains lit_review/deep.bib (curated subset of wide.bib, with longer
  `annote` annotations) and lit_review/summary_deep.md (per-paper sections
  plus synthesis and gap analysis). It attempts to download open-access PDFs;
  when a paper is paywalled or otherwise unavailable, it adds a row to
  lit_review/requests.md so the user can fetch it manually. PREREQUISITES:
  lit_review/scope.md and lit_review/wide.bib must already exist (produced by
  lit-review-scoping and lit-review-wide). If they do not, point the user to
  those skills first. Do NOT use this skill to build a broad long-list (that
  is lit-review-wide), to read a single paper outside a review context, or to
  write a "related work" section of a manuscript.
---

# Deep Literature Review

This skill produces detailed per-paper analysis and synthesis for a curated
subset of the wide long-list. It is the third of three skills: scoping →
wide → **deep**.

The user is a PhD-level researcher in CS / ML / control / robotics. They
already have a long-list. Your job is to read carefully, characterise each
paper precisely, situate it against the others, and identify what the
literature is *not* doing. Where wide is about breadth, deep is about
fidelity and synthesis.

## Prerequisites

Before doing anything, verify:

1. `lit_review/scope.md` exists. Read it — the synthesis must speak to the
   scope's research question and gaps.
2. `lit_review/wide.bib` exists. The papers you promote to `deep.bib`
   come from there. If it is empty, send the user to the lit-review-wide
   skill first.

If either is missing, stop and tell the user. Do not improvise scope.

## Folder contract

```
lit_review/
  scope.md          # input (read-only here)
  wide.bib          # input (read-only here)
  summary_wide.md   # input (read-only here)
  deep.bib          # OWNED HERE: curated subset with longer `annote`
  summary_deep.md   # OWNED HERE: per-paper sections + synthesis + gaps
  requests.md       # OWNED HERE: paywalled PDFs queued for the user
  pdfs/             # OWNED HERE: <citekey>.pdf for each readable paper
  search_log.md     # append-only here as well
```

Citekeys are inherited unchanged from `wide.bib`. Never regenerate them — the
user's manuscript and the wide skill's bookkeeping depend on stability.

## Nominating papers for the deep dive

The user specifies which papers to promote in one of three ways:

1. **By citekey list.** "Go deep on `coulom2006mcts`, `silver2017mastering`,
   `schrittwieser2020muzero`." Use these directly.
2. **By subtopic.** "Deep dive on the MCTS subtopic." Open
   `summary_wide.md`, find the section, take its citekey list.
3. **By query.** "Deep dive on everything we have on safety filters."
   Search `wide.bib` annotations and titles; propose a candidate citekey
   list back to the user for confirmation *before* promoting.

If the user is vague, ask: "Which papers — citekeys, a subtopic name, or
shall I propose a shortlist?" Do not guess at 30 papers when they meant 5.
Deep is expensive; small batches are normal.

## The bundled operations script

`scripts/deep_ops.py` handles the deterministic work: promoting entries
between bib files, attempting open-access PDF downloads, and bookkeeping
into `requests.md`. Stdlib only.

```bash
# 1. Promote: copy entries from wide.bib to deep.bib by citekey.
python ${CLAUDE_SKILL_DIR}/scripts/deep_ops.py promote coulom2006mcts kingma2014adam

# 2. Acquire: try to download a PDF (arXiv / OpenReview / direct OA URL).
python ${CLAUDE_SKILL_DIR}/scripts/deep_ops.py acquire coulom2006mcts

# 3. Status: which deep.bib citekeys have / lack a local PDF.
python ${CLAUDE_SKILL_DIR}/scripts/deep_ops.py status

# 4. Request: queue a paywalled paper for the user to fetch manually.
python ${CLAUDE_SKILL_DIR}/scripts/deep_ops.py request paywalled2020
```

PDF acquisition is best-effort and does *not* attempt to bypass paywalls.
Sources tried, in order: arXiv (via `eprint` field), OpenReview (via the
`url` field pattern), any `url` ending in `.pdf` that resolves to a PDF
content-type. Anything else routes to `requests.md`.

## Workflow

### 1. Promote nominees into deep.bib

Run `deep_ops.py promote <citekeys...>`. The script preserves entries
verbatim, so any `annote` written during the wide pass is carried forward —
you will *replace* it with the deeper annotation in step 4, but keep the
original handy as a sanity check.

### 2. Acquire PDFs

For each promoted citekey, run `deep_ops.py acquire <citekey>`. Capture the
result. Batch this — it makes the next step much smoother.

For any failures, run `deep_ops.py request <citekey>` to add a row to
`requests.md` with the title, DOI, and best landing URL.

When PDFs become available later (the user drops them into `pdfs/`),
remove the corresponding row from `requests.md` and proceed.

### 3. Read

For each paper with a local PDF, read it. Aim to understand:

- The problem setup precisely — what is held fixed, what varies, what is
  assumed about the environment.
- The technical core of the method — the actual mathematical or
  architectural idea, not just the name.
- The empirical or theoretical claims — what specifically is shown, on what
  benchmarks or in what theorem, with what guarantees and what gaps.
- The argued position vs. prior work — what the authors say is new.
- Where the paper is weak — assumptions that may not hold elsewhere,
  experimental coverage that is narrow, results that are weaker than the
  framing suggests.

For papers without a local PDF, work from abstract + the paper's own
references (visible in citation chasing) + any reviews/discussions found via
the wide skill's tools. Be explicit in the annotation that the read is
abstract-based and which questions remain open.

### 4. Write the per-paper section in summary_deep.md

Each promoted paper gets its own section under a subtopic heading (same
taxonomy as `scope.md`). Follow this template — adapt where a section is
genuinely not applicable, but do not skip without good reason:

```markdown
### <Paper title>  `\cite{citekey}`

**Setting.** <1–3 sentences. The problem the paper addresses, the
assumptions, the regime.>

**Approach.** <2–5 sentences. The technical contribution, with enough
precision that an expert can tell it apart from neighbouring methods.>

**Findings.** <2–4 sentences. What is shown — empirical numbers if they
matter, the form of any theorem, the conditions under which the result
holds.>

**Position.** <1–3 sentences. What this paper changes about the prior
literature. Reference other citekeys in the review where relevant.>

**Strengths and limitations.** <Short, honest. Where assumptions bind,
where evidence is thin.>

**Relevance to this review.** <1–2 sentences tying back to scope.md's
research question.>
```

### 5. Update deep.bib's `annote`

Replace each paper's wide-era `annote` with a 2–4 sentence enriched
annotation capturing position and contribution. This is the scannable
version of the per-paper section in step 4 — the bib is for someone
flipping through citekeys; `summary_deep.md` is for reading.

Edit the `annote` field directly in `deep.bib` in place. (Standard styles
ignore `annote`, so this never reaches a compiled paper.)

### 6. Update the synthesis

`summary_deep.md` opens with a synthesis section that grows as papers are
added. This is the most valuable artefact of the deep skill — it is where
the cross-cutting argument lives. Update it whenever you add or revise
per-paper sections. The structure:

- **Lineages.** Group papers into the actual technical lineages — what
  follows from what, who first introduced an idea, where the field forked.
  Not "everyone cites Sutton & Barto"; specific influence paths.
- **Methodological clusters.** Group by *how* papers solve their problem,
  not by what they call themselves. Methods often cross subtopic
  boundaries.
- **Debates and disagreements.** Where do papers contradict each other?
  Where is the empirical or theoretical evidence ambiguous?
- **Convergences.** Where has the field actually settled? State this
  explicitly because it is often invisible until called out.

### 7. Gap analysis

This is the second most valuable artefact, and the one most easily skipped.
Maintain a "Gaps" section that lists, explicitly:

- Problem settings the literature has not addressed.
- Assumptions that everyone makes and nobody justifies.
- Empirical evidence that is missing (regimes, scales, baselines).
- Theoretical results that would resolve open debates if proven.
- Methodological combinations that would be obvious but have not been
  tried.

Be specific. "More work needed on scalability" is not a gap. "No paper
evaluates beyond 10⁶ environment steps; the asymptotic regime claims rest
on extrapolation" is a gap.

These are first-draft observations for the user, not conclusions. The user
will know which are real gaps and which are gaps you missed seeing
addressed. Mark each with confidence: `(strong)` for things you are sure
of, `(tentative)` for things to verify.

### 8. Maintain requests.md hygiene and surface it in Notes

When the user has dropped a PDF into `pdfs/<citekey>.pdf`, the
corresponding row in `requests.md` is stale. On each invocation, run
`deep_ops.py status` early; for any citekey listed in `requests.md` whose
PDF now exists, remove the row.

Then mirror the *still-outstanding* requests into the Notes section of
`summary_deep.md` (see template) so the user sees them in the report
itself, not only in the separate `requests.md`. The mirror is a short
bulleted list — citekey, title, best link — kept in sync each run. The
authoritative queue is `requests.md`; the Notes mirror is a reading aid.

## When to chase citations from within the deep dive

While reading, you will encounter cited works that look essential and are
not yet in the review. Two options:

1. **If clearly in-scope:** add the paper to `wide.bib` first (via the wide
   skill's `discover.py lookup`/`refs`/`cites`), then promote into
   `deep.bib`. Maintains the invariant that everything in `deep.bib` came
   from `wide.bib`.
2. **If marginal:** note it in `summary_deep.md` under "Notes" with a
   one-line justification, but do not pull it into the review. Surface
   these to the user — they may want to widen scope.

Resist the temptation to balloon the deep set. A focused deep review of 8
papers beats a sprawling one of 30.

## What the synthesis section looks like

```markdown
# Deep Literature Review: <topic>

_Last updated: <YYYY-MM-DD>. Papers in deep set: <N>._

## Synthesis

### Lineages
<2–4 short paragraphs tracing influence paths between papers.>

### Methodological clusters
<Group papers by approach. State the unifying technical commitment of each
cluster.>

### Debates and convergences
<Where the field disagrees and where it has settled.>

### Gaps
- _(strong)_ <Specific, concrete gap.>
- _(tentative)_ <Specific, concrete gap.>

## Papers, by subtopic

### <Subtopic A>
<Per-paper sections following the template above.>

### <Subtopic B>
...

## Notes

### Outstanding PDF requests
<Mirror of unfetched rows from requests.md. Empty if none.>
- `paywalled2020` — *A Paywalled Paper* — [DOI](https://doi.org/10.1234/abcd)

### Other
<Anything that surfaced during reading that does not fit elsewhere —
candidate scope revisions, papers worth pulling in, methodological
questions to track.>
```

## Stopping conditions

A deep review is done when:

- Every nominated citekey has a per-paper section and a refreshed `annote`.
- The synthesis section reflects all included papers, not just the most
  recent batch.
- The gaps section has been updated and the user has seen the latest
  version.
- `requests.md` is up to date — no stale rows for papers now in `pdfs/`.

If the user asks "what's next?", suggest one of: tighten scope based on
gaps; promote more papers from `wide.bib`; or move to drafting a related-
work section (which is a future skill, not this one).

## What this skill does *not* do

- Bypass paywalls. Closed-access papers go to `requests.md`.
- Replace the user's judgment. The synthesis and gaps are first drafts; the
  user is the expert.
- Generate the manuscript's related-work section. That is downstream and
  has its own argumentative shape.
