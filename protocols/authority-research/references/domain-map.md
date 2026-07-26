# Domain Map Layer

Use a domain map before source scouting when the research scope is broad. It prevents one huge prompt from mixing unrelated topics and makes gaps visible later.

## Purpose

The domain map is a topic matrix. It lists the axes that must be filled before the project can claim broad coverage.

Examples:

- vision therapy: binocular vision, strabismus, diplopia, amblyopia, convergence insufficiency, products, regulation.
- DCA: volatility, exchange APIs, risk, taxes, on-chain data, bot security.
- UV coating: photopolymerization, curing equipment, defects, safety, suppliers, regulation.

## Axis Discovery First (bootstrap — deliberated 2026-05-31, MVP)

When the topic is broad, do NOT hand-write the axes from memory. Spawn an axis-discovery worker first; promote only evidence-backed candidates into the map below. The orchestrator's prior knowledge is the funnel ceiling — an axis never defined is never collected later. The worker counters this by running internal cross-model multi-round convergence (codex + agy: divergence → adversarial critique → converge), so no single model's prior caps the axis set (upgraded 2026-06-08; see "Axis Discovery (Bootstrap)" in `worker-contracts.md`).

Output `<run_dir>/schedule/candidate-axes.yaml`:

```yaml
version: authority_research_bootstrap_v0_1
topic:
proposed_axes:
  - id:
    name:
    scope:
    why_it_matters:
    evidence:
      - signal:        # recurring term / venue / tool / failure story that surfaced it
        where:         # the query or source where it appeared
    suggested_search_terms:
    adjacent_to:
    confidence: high | medium | low
    promote_to_domain_map: yes | no | watch
```

Keep promoted active axes to ~8 or fewer (start ~6, leave room for discovered ones). Contract: "Axis Discovery (Bootstrap)" in `worker-contracts.md`. The discovery + completeness-critic steps are now cross-model multi-round (2026-06-08); axis-budget enforcement + automated collection-reflux remain deferred — see `authority-phase1-redesign.md` in the notes-astro seogo.

## File Location

Save as:

```text
<run_dir>/schedule/domain-map.yaml
```

## Schema

```yaml
version: authority_research_domain_map_v0_1
domain: vision-therapy
title: Vision Therapy Research Map
description: Broad source collection map for vision therapy authority content.

defaults:
  preferred_worker: codex
  source_types: [paper, guideline, regulator, product, society, university, book, news, blog]

axes:
  - id: binocular-vision
    label: Binocular vision / 양안시
    priority: high
    preferred_worker: codex
    scope: Core concepts, disorders, diagnosis, and treatment evidence.
    search_terms:
      - binocular vision
      - binocular vision disorder
      - 양안시
    source_types: [paper, guideline, society, book]
    seed_sources:
      - https://pubmed.ncbi.nlm.nih.gov/
    notes:
      - Do not generalize learning-disability claims.

  - id: vivid-vision
    label: Vivid Vision
    priority: high
    preferred_worker: agy
    scope: Official product pages, clinical research, provider materials, and publication trail.
    search_terms:
      - Vivid Vision clinical research
      - Vivid Vision amblyopia
    source_types: [product, paper, company, clinical_trial]
    seed_sources:
      - https://www.seevividly.com/
```

## Worker Selection

- `preferred_worker: codex`: top-of-schedule task, numbered `001`, `002`, ...
- `preferred_worker: agy`: bottom-of-schedule task, numbered `999`, `998`, ...
- Use `agy` for broad web discovery, official product sites, weakly structured pages, and Google-search-heavy work.
- Use `codex` for structured academic or local-file-heavy tasks.

## Convert To Schedule

```bash
python3 $AR_SKILL/scripts/make_axis_schedule.py \
  --domain-map <run_dir>/schedule/domain-map.yaml \
  --run-dir <run_dir> \
  --phase source-scout
```

Supported phases:

- `source-scout`
- `site-profile`
- `collection`
- `classification`
- `source-verification`
- `fact-verification`
- `drafting`

The first pass should almost always be `source-scout`. Later phases can be generated after measuring existing output size.

## Coverage Tracking

Do not ask the main agent to read the materials. Use file counts and bytes per axis/task. After each phase:

```bash
python3 $AR_SKILL/scripts/measure_run.py <run_dir>
```

Then create the next schedule for weak or empty axes.
