---
name: lit-review-scoping
description: >-
  Scope and frame a literature review before any searching begins. Use this
  whenever the user wants to start a literature review or survey of a research
  area — phrases like "I want to do a lit review on...", "help me survey the
  work on...", "I'm looking into the literature on...", or "frame my research
  on..." — even if they never say the words "literature review". This skill runs an iterative
  dialogue with the user to settle the research question, in/out-of-scope
  boundaries, relevant fields and adjacent areas, target venues, search
  keywords, and a subtopic taxonomy, then writes lit_review/scope.md. Run this
  FIRST: the lit-review-wide and lit-review-deep skills both depend on the
  scope.md it produces. Do NOT use this skill for the actual searching and
  summarizing of papers (that is lit-review-wide / lit-review-deep) or for
  citation formatting.
---

# Literature Review Scoping

This skill produces `lit_review/scope.md` — the planning document that frames a
literature review before any searching happens. It is the first of three
skills: **scoping** (this one) → **wide** (broad long-list) → **deep** (curated
synthesis). A good scope makes the later skills far more efficient, because
they search against deliberate keyword clusters and organize results against an
agreed taxonomy rather than improvising.

The user is a PhD-level researcher in CS / ML / control / robotics. Treat them as
the domain expert. Your value is breadth of recall (adjacent fields, venues,
terminology), identifying emerging ideas, and structure — not teaching them
their field.

## The shared folder contract

All three lit-review skills operate inside a `lit_review/` directory. This
skill owns `scope.md`; it should be aware of the rest so `scope.md` stays
consistent with what downstream skills expect.

```
lit_review/
  scope.md          # OWNED HERE
  wide.bib          # long-list (lit-review-wide)
  summary_wide.md   # thematic long-list summary (lit-review-wide)
  deep.bib          # curated subset (lit-review-deep)
  summary_deep.md   # synthesis + gaps (lit-review-deep)
  requests.md       # paywalled PDFs for the user to fetch
  search_log.md     # query/source/date log
  pdfs/             # PDFs, one per citekey
```

**Citekey convention:** `authorYEARword` — first author's surname (lowercase,
alphanumeric only), four-digit year, first non-stopword content word of the
title. Example: `coulom2006mcts`, `kingma2014adam`. Disambiguate collisions
with a trailing letter (`smith2020learninga`, `smith2020learningb`). Apply this
to any seed papers listed in `scope.md`; every paper keeps the *same* key
across `scope.md`, `wide.bib`, `deep.bib`, and the user's eventual manuscript,
so the downstream skills can rely on it.

## Workflow

### 1. Set up

Locate or create the `lit_review/` directory (default: the current working
directory; ask if ambiguous). If `scope.md` already exists, read it and treat
this as a revision — confirm with the user what they want to change rather than
overwriting silently.

### 2. Establish the research question

If the user's topic is already sharp, move on. If it is broad or ambiguous,
ask a small number of focused questions — not a generic intake form. The ones
that matter most:

- What is the underlying problem, and what would a *good answer* look like?
- Is this review surveying a field, or positioning a specific contribution the
  user intends to make? (This changes what counts as in-scope.)
- What is already known to the user — seed papers, a prior survey, a course?

Ask at most two or three at a time. Stop asking once you can write a defensible
first draft.

### 3. Draft an initial scope and present it

Do not interrogate the user to fill every section. Produce a concrete first
draft of `scope.md` quickly — a draft is easier to react to than a blank form —
and present the substantive choices for feedback. The sections that need real
thought:

- **In / out of scope.** State boundaries explicitly. Most reviews fail by
  being too broad. Name what you are deliberately excluding and why. Set a
  temporal boundary too (e.g. "2018–present, foundational pre-2018 work
  allowed") or note explicitly that the window is open — lit-review-wide filters
  candidates against it and uses it to set `--year-from`.
- **Fields and adjacent areas.** This is the highest-value part. See the
  heuristic below.
- **Venues.** For CS/ML: NeurIPS, ICML, ICLR, AISTATS, UAI, CoRL, L4DC, JMLR,
  TMLR. For control: CDC, ACC, ECC, IFAC World Congress, *Automatica*, IEEE
  *TAC*, *L-CSS*. For robotics: RSS, ICRA, IROS, IEEE *RA-L*, IEEE *T-RO*,
  *IJRR*. Operations-research-adjacent work appears in *Operations Research*,
  *Management Science*, INFORMS venues. Tailor to the actual topic; use web
  search to confirm where a specific subfield publishes if unsure.
- **Keyword clusters.** Produce ready-to-use search strings, grouped by
  subtopic, each with synonyms and community-specific variants (the same idea
  is often named differently in ML vs. controls vs. OR). The lit-review-wide
  skill consumes these directly.
- **Subtopic taxonomy.** A 3–7 item breakdown of the area. This becomes the
  section skeleton of `summary_wide.md`, so make it MECE-ish and stable.

### 4. Iterate

Refine with the user. Push back when scope looks unworkable — too broad to
finish, or so narrow it will surface a handful of papers. Frame pushback as a
tradeoff ("scoped this way you'll have ~200 candidates; tightening to X cuts it
to ~50"), not a verdict. Update `scope.md` after each round.

## The adjacent-areas heuristic

The point of scoping is to catch the fields the user would not have searched.
A topic in CS/ML/controls almost always has neighbors that share structure
under different names. Look along these axes:

- **Shared methods.** Same mathematical machinery, different application. *Rare
  event simulation* → *extreme value theory*, *importance sampling*, *large
  deviations theory*.
- **Same problem, different community.** *Safe RL* ↔ *robust/constrained
  control* ↔ *chance-constrained optimization*. Flag the vocabulary mismatch
  explicitly so the wide search uses both sets of terms.
- **Upstream / downstream.** Methods the topic depends on, and applications
  that consume it.
- **Theoretical foundations.** The statistics, optimization, or dynamical-
  systems theory the area rests on.

For each adjacent area, state *why* it is relevant in one line — that
justification is what makes the suggestion useful rather than noise.

## scope.md template

Write `scope.md` in this structure. Keep it tight; it is a working document,
not an essay.

```markdown
# Literature Review Scope: <topic>

_Last updated: <YYYY-MM-DD>_

## Research question
<1–3 sentences. The question the review must answer.>

## Motivation
<2–4 sentences: why this matters, what a good answer enables.>

## In scope / Out of scope
**In:** <bulleted boundaries>
**Out:** <bulleted exclusions, each with a one-line reason>
**Time window:** <e.g. "2018–present, foundational earlier work allowed", or "open">


## Fields and subfields
<Primary field(s) and the relevant subfields within them.>

## Adjacent areas
| Area | Why relevant | Key terms / vocabulary |
|------|--------------|------------------------|
| ...  | ...          | ...                    |

## Target venues
**Conferences:** ...
**Journals:** ...

## Search keyword clusters
### <subtopic 1>
- "<query string>" — variants: ...
### <subtopic 2>
- ...

## Subtopic taxonomy
<3–7 items; this is the section skeleton for summary_wide.md.>
1. ...
2. ...

## Seed papers
| Citekey | Reference | Why it seeds the review |
|---------|-----------|-------------------------|
| ...     | ...       | ...                     |

## Open questions / decisions pending
<Anything unresolved that affects the wide search.>
```

## Closing

When the user is satisfied, confirm `scope.md` is written and point them to the
next step: run the lit-review-wide skill to build the long-list. Do not start
searching for papers yourself — that is a separate skill with its own
discovery and bookkeeping logic.
