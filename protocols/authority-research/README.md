# Authority Research

Authority Research is a two-phase protocol for building a source-backed research corpus without flooding the main agent context.

It is useful when the task needs broad source discovery, source quality judgment, cross-checking, and article-ready outputs.

## When To Use

Use this protocol for:

- broad research over many websites or source families
- competitive landscapes
- source inventories
- knowledge-base bootstrapping
- regulatory, medical, legal, market, or technical research that needs explicit claim verification
- article briefs that must separate evidence from interpretation

Do not use it for a simple answer that can be checked from one or two sources.

## Phase 1: Collection

```text
axis discovery
  -> domain map
  -> source scouting
  -> site profiling
  -> completeness gate
  -> collection
  -> classification
  -> source verification
  -> fact verification
```

### Key Ideas

| Component | Role |
| --- | --- |
| Axis discovery | Avoids making the orchestrator's first guess the ceiling |
| Domain map | Defines bounded research axes and source families |
| Source scouting | Finds durable sources before collecting content |
| Site profiling | Estimates access method, value, risk, and collection difficulty |
| Completeness gate | Attacks missing perspectives before collection scales |
| Collection | Stores raw, triaged, and rejected materials separately |
| Classification | Adds topic, trust, evidence role, and usefulness labels |
| Verification | Confirms source metadata and claims against source material |

## Phase 2: Curation

```text
editorial curation
  -> claim ledger
  -> hallucination audit
  -> topic packs
  -> article briefs
```

Phase 2 turns the collected corpus into material that can safely be used for writing or decisions.

## Run Folder

Each run is self-contained:

```text
data/authority-research-runs/<run-id>/
  run.yaml
  inventory/
  profiles/
  schedule/
  raw/
  triaged/
  rejected/
  classified/
  verified/
  curation/
  claim-ledger/
  hallucination-audits/
  topic-packs/
  article-briefs/
  drafted/
  done/
  logs/
  prompts/
```

The main agent should inspect only:

- `run.yaml`
- `schedule/*.yaml`
- `done/*.yaml`
- `logs/measure-report.yaml`
- file counts and byte counts

It should not read raw source bodies unless the user explicitly asks.

## Worker Contract

Every worker receives:

- one task id
- one bounded input set
- the relevant protocol section
- the required output paths
- a requirement to write `done/<task_id>.yaml`

Every worker returns only:

- status
- paths written
- blockers
- short notes

Long source excerpts should stay in files, not chat.

## Completion Marker

```yaml
task_id: "001"
phase: "source-scout"
status: done
worker: "codex"
outputs:
  - "inventory/001-sources.yaml"
notes: "Short completion note."
```

Failed tasks are still recorded:

```yaml
task_id: "001"
phase: "source-scout"
status: failed
worker: "codex"
error: "Source site blocked automated access."
outputs: []
```

## Claim Safety

Claims that can affect public writing or decisions must pass through:

1. curation
2. claim ledger
3. hallucination audit
4. topic pack or brief

Use `UNKNOWN` when evidence is missing. Do not fill gaps from model memory.

## Scripts

The helper scripts in `scripts/authority-research/` are intentionally small:

- `init_run.py` creates the run folder
- `make_axis_schedule.py` creates work schedules from a domain map
- `measure_run.py` counts files and done markers

They do not crawl the web and do not call a model.
