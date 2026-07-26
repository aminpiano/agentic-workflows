# Authority Research Run Layout

## Folder Layout

Create one run folder per research campaign:

```text
<project>/data/authority-research-runs/<run-id>/
  run.yaml
  inventory/
  profiles/
  schedule/
  raw/
  triaged/
  rejected/
  classified/
  verified/
  drafted/
  synthesis/
  done/
  logs/
  prompts/
```

## Main-Agent Visible Files

The main agent may inspect:

- `run.yaml`
- `schedule/*.yaml`
- `done/*.yaml`
- `logs/measure-report.yaml`
- `logs/validation-report.yaml`
- `logs/normalization-report.yaml`
- `logs/public-material-gate.yaml`
- `logs/synthesis-quality-report.yaml`
- `logs/run-dashboard.yaml`

The main agent should not read `raw/`, `triaged/`, `classified/`, `verified/`, or `drafted/` during orchestration unless the user asks.

## Done Marker

Every worker must write `done/<task_id>.yaml`:

```yaml
task_id: "001"
status: done # done | failed
worker: codex-subagent # codex-subagent | agy
started_at: "YYYY-MM-DDTHH:MM:SSZ"
finished_at: "YYYY-MM-DDTHH:MM:SSZ"
output_files:
  - raw/001/source-01.md
  - triaged/001/source-01.md
items_collected: 0
items_rejected: 0
bytes_written: 0
errors: []
next_suggested_tasks: []
```

The worker's final chat response should contain only task id, status, and done marker path.

## Work Schedule

### Schedules accumulate — never overwrite one

Re-running a phase writes a **new wave file**; it does not replace the previous
schedule.

```text
schedule/collection-schedule.yaml       # wave 1 (historical name, kept)
schedule/collection-schedule-w2.yaml    # wave 2 — pivot / delta tasks
schedule/collection-schedule-w3.yaml    # wave 3 — repair after critic fail
```

The generator scripts pick the next free wave automatically
(`_contract.next_schedule_path`); pass `--out` only to override deliberately.

This matters because `done/` markers accumulate forever. Overwrite a schedule
and its finished tasks become unattributable — the run's completion can no
longer be computed at all, and nothing reports that it happened. Every delta or
repair task must therefore be appended to a schedule **before** its worker is
spawned, never handed to a worker directly.

### Schedules are identified by shape, not by filename

`schedule/` also holds `domain-map.yaml`, `candidate-axes.yaml`, and
`completeness-review.yaml` — different schemas entirely. A document is a
schedule when it is a mapping carrying a `tasks` list (`_contract.is_schedule_doc`).
Readers must not assume every YAML under `schedule/` is a schedule, or axis ids
get counted as task ids.

### Schedule file

Use `schedule/work-schedule.yaml`:

```yaml
version: authority_research_schedule_v0_1
run_id: "20260528-vision-therapy"
phase: collection
assignment_policy:
  codex_direction: ascending
  agy_direction: descending
  codex_batch_size: 5
  agy_concurrency: 1
tasks:
  - task_id: "001"
    status: pending
    worker: codex
    title: "PubMed convergence insufficiency"
    instruction: "Collect source candidates..."
    expected_outputs: [raw, triaged, rejected, done]
  - task_id: "999"
    status: pending
    worker: agy
    title: "Vivid Vision official pages"
    instruction: "Use web search..."
    expected_outputs: [raw, triaged, rejected, done]
```

Update status only from done markers:

- `pending`
- `running`
- `done`
- `failed`
- `skipped`

## Worker Prompt Files

Use `scripts/make_worker_prompt.py` to generate worker prompts under `prompts/`:

```text
prompts/<task_id>-<contract>.prompt.md
```

Generated prompts prepend the Global Rules and instruction boundary from `references/worker-contracts.md`, then include the assigned schedule task. Prefer generated prompts over hand-written prompts so subagents receive the same security and output contract.

## Source File Frontmatter

`raw/` and `triaged/` files should have frontmatter:

```yaml
---
source_id:
task_id:
source_url:
title:
source_type: paper | guideline | regulator | product | society | university | book | blog | news | other
trust_grade: S | A | B | C | D | UNKNOWN
domain_tags: []
doi:
pmid:
nct_id:
verification_status: unverified
publication_status: blocked_until_verified
---
```

Use `UNKNOWN` for missing fields.

---

# Phase 2 — Curation Layout

Phase 2 works inside the same Phase 1 run folder. It does not modify or move existing `raw/`, `triaged/`, `classified/`, or `verified/` files — it only adds the folders below.

## Curation Output Folders

```text
<run>/
  curation/       # per-axis editorial curation outputs
  claim-ledger/   # extracted claims that must be checked before drafting
  hallucination-audits/ # claim/source support audits
  topic-packs/    # article-ready source packs by topic
  article-briefs/ # draft plans, not final posts
  synthesis/      # design/article synthesis candidates with claim/source pointers
  dedup/          # cross-axis duplicate maps
```

## Phase 2 Done Marker

Phase 2 workers also write `done/<task_id>.yaml`. Task ids use a prefix to separate them from Phase 1 (`001`): `ec001` (editorial curation), `ha001` (hallucination audit), etc. The schema is identical to the Phase 1 Done Marker.

## Editorial Curation Output

`curation/<task_id>-curation.yaml`:

```yaml
task_id: "ec001"
source_files:
  classified: classified/cl001-classification.yaml
  verified: verified/sv001-source-verification.yaml
axis_label: "UNKNOWN"
curated_sources:
  - source_file:
    source_url:
    title:
    source_type:
    evidence_role:
    trust_grade:
    verification_status: verified | needs_correction | unknown
    editorial_bucket:
    article_usefulness: high | medium | low | reject
    recommended_use:
    claims_to_fact_check: []
    cautions: []
topic_pack_suggestions:
  - topic_slug:
    topic_title:
    source_files: []
    angle:
    readiness: ready_for_brief | needs_fact_verification | background_only | reject
```

## Claim Ledger Output

`claim-ledger/<task_id>-claims.yaml`:

```yaml
task_id: "ha001"
source_curation: curation/ec001-curation.yaml
claims:
  - claim_id: "ha001-c001"
    claim_text:
    source_files: []
    source_urls: []
    claim_type: clinical | regulatory | product | market | historical | biographical | other
    risk_level: high | medium | low
    publication_relevance: high | medium | low
    verification_status: pending
    verifier_prompt_hint:
```

Every claim needs at least one `source_files` or `source_urls` pointer. A synthesis-only file is not enough for schema-like design claims unless it points through to original source notes or audited claims.

## Hallucination Audit Output

`hallucination-audits/<task_id>-audit.yaml`:

```yaml
task_id: "ha001"
source_curation: curation/ec001-curation.yaml
claim_ledger: claim-ledger/ha001-claims.yaml
audited_claims:
  - claim_id: "ha001-c001"
    claim_text:
    source_files: []
    source_urls: []
    verdict: SUPPORTED | PARTIALLY_SUPPORTED | UNSUPPORTED | CONFLICT | UNKNOWN
    risk_flags: []
    evidence_notes:
    required_caveat:
    public_use: usable | usable_with_caveat | do_not_use
summary:
  usable_claims: 0
  caveated_claims: 0
  blocked_claims: 0
  unknown_claims: 0
```

Do not use hallucination audit files as primary evidence. They are editorial controls pointing back to source files and URLs.

## Topic Pack Output

`topic-packs/<topic-slug>.yaml`:

```yaml
topic_slug:
topic_title:
status: draft_pack
source_groups:
  evidence: []
  guidelines: []
  regulatory: []
  product_or_company: []
  market_context: []
  controversy: []
  background: []
fact_verification_needed: []
audited_claim_refs: []
article_angles: []
not_for_publication: []
```

## Public Material Gate Output

`logs/public-material-gate.yaml`:

```yaml
summary:
  total_claims: 0
  usable: 0
  usable_with_caveat: 0
  do_not_use: 0
counts_by_verdict:
  SUPPORTED: 0
  PARTIALLY_SUPPORTED: 0
  UNSUPPORTED: 0
  CONFLICT: 0
  UNKNOWN: 0
claims_by_public_use:
  usable: []
  usable_with_caveat: []
  do_not_use: []
```

Use this gate before topic packs, article briefs, public reports, or final drafts.

## Run Dashboard

`logs/run-dashboard.yaml`:

```yaml
done_status:
  done: 0
  failed: 0
  other: 0
schedule_status:
  pending: 0
  running: 0
  done: 0
  failed: 0
  skipped: 0
validation: {}
public_material_gate: {}
synthesis_quality: {}
next_actions: []
```

Keep this file current at phase boundaries and before handoff. It is the main-agent dashboard for resuming without reading raw or curated source bodies.

## Synthesis Quality Report

`logs/synthesis-quality-report.yaml`:

```yaml
summary:
  status: pass | warn | fail
checks:
  coverage_check: {}
  claim_trace_check: {}
  uncertainty_check: {}
  decision_readiness_check: {}
  perspective_preservation_check: {}
```

This is not a token compression report. It checks whether final briefs/topic packs preserve enough coverage, traceability, uncertainty handling, and decision usefulness for a human or another AI to continue.

## Article Brief Output

`article-briefs/<brief-slug>.md` is a plan, not a final post. It should include:

- target reader
- central question
- draft thesis
- source pack
- audited claims that can be used
- claims requiring fact verification or exclusion
- balance/caution notes
- recommended next verifier tasks
