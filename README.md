# Agentic Workflows

Portable, file-based protocols for AI agents that need to do long work without losing context.

This repository is not a framework. It is a set of operating patterns that can be used with Claude, Codex, Gemini, Cursor, Copilot, or any agent that can read and write files.

## Why This Exists

Most agent workflows fail for boring reasons:

- the agent reads too much raw material into the main context
- work cannot resume after a session reset
- source quality is mixed with final claims
- different agents repeat the same discovery work
- project knowledge is trapped inside one vendor memory system

The protocols here use the filesystem as the coordination layer. Agents write schedules, done markers, source notes, claim ledgers, audits, and indexes. The next agent can resume from files instead of reconstructing the whole conversation.

## Protocols

| Protocol | Purpose | Status |
| --- | --- | --- |
| [Authority Research](protocols/authority-research/README.md) | Build a source-backed research corpus and article-ready evidence packs | flagship |
| [AI Project Docs](protocols/ai-project-docs/README.md) | Generate and maintain project documentation optimized for future AI agents | companion |
| [Deliberate](protocols/deliberate/README.md) | Run lightweight multi-model review rounds for high-tradeoff decisions | companion |
| [Seogo](protocols/seogo/README.md) | Keep long-term project context, session handoff, lessons, and progress in a local knowledge shelf | companion |

## The Core Pattern

1. The main agent orchestrates. It does not ingest the whole corpus.
2. Workers read bounded inputs and write structured files.
3. Completion is tracked with `done/*.yaml`, not memory.
4. Claims are separated from sources.
5. High-risk claims are audited before publication or action.
6. A small index tells the next agent where to start.

## Quick Start

For research:

```bash
python3 scripts/authority-research/init_run.py \
  --project . \
  --topic "example research topic"
```

Then copy and edit:

```bash
cp templates/authority-research/domain-map.yaml \
  data/authority-research-runs/<run-id>/schedule/domain-map.yaml

python3 scripts/authority-research/make_axis_schedule.py \
  --domain-map data/authority-research-runs/<run-id>/schedule/domain-map.yaml \
  --run-dir data/authority-research-runs/<run-id> \
  --phase source-scout
```

Assign the generated tasks to whichever agents you use. Each worker writes its outputs and a done marker. Measure progress with:

```bash
python3 scripts/authority-research/measure_run.py \
  data/authority-research-runs/<run-id>
```

## Repository Layout

```text
protocols/          Human-readable protocol specifications
templates/          Copyable starter files
scripts/            Small helper scripts for file layout and schedules
adapters/           Notes for Claude, Codex, Gemini, and generic agents
examples/           Minimal examples and run sketches
```

## Non-Goals

- No central server.
- No hosted database.
- No vendor-specific lock-in.
- No promise that agents are correct without verification.
- No replacement for source review in high-stakes domains.

## License

MIT
