# Agentic Workflows

> **TL;DR** — Portable, file-based protocols that let AI agents run long, multi-step work
> without losing context. The filesystem is the coordination layer: agents write schedules,
> done-markers, source notes, claim ledgers, and indexes, so the next agent resumes from
> files instead of replaying the whole conversation. Vendor-neutral — works with any
> file-capable agent: Claude Code, Codex CLI, Gemini CLI, Cursor, or GitHub Copilot.

This repository is a set of **operating patterns for multi-agent and long-horizon AI workflows** —
covering context engineering, orchestrator–worker coordination, file-based agent memory, session
resumption, and research automation. It is not a framework and not a library.

## What is this?

A collection of plain-Markdown protocols, copyable templates, and small helper scripts for AI
agents that need to run tasks across many steps and multiple sessions. There is no runtime to
install and nothing to import. Point an agent at the repository and it can execute a protocol
directly, because the entire contract is just files on disk that any agent — or human — can read
and write.

## What problem does it solve?

Most agent workflows fail for boring, repeatable reasons:

- the agent pulls too much raw material into its main context window
- work cannot resume after a session reset or context compaction
- source material gets mixed with final claims, so nothing is verifiable
- parallel agents repeat each other's discovery work
- project knowledge is trapped inside one vendor's memory system

These protocols use the filesystem as shared state to remove each of those failures.

## When should you use it?

Use it when you are building a bounded research corpus, running a project across multiple
sessions, fanning work out to several agents in parallel, or when you need the result to be
resumable and auditable later. Skip it when a single prompt already answers the question — these
patterns are for work too large or too long-lived to hold in one context window.

## How is this different from agent frameworks (LangChain, CrewAI, AutoGPT)?

Those are code frameworks: you import a library and your control flow lives in Python or
JavaScript. These protocols are **vendor-neutral and code-optional** — the contract is files on
disk, readable and writable by any agent or human. There is no runtime to install and no
lock-in. You can run a protocol by hand, from a script, or fully agent-driven, and switch model
vendors at any point without rewriting anything.

## Protocols

| Protocol | Purpose | Status |
| --- | --- | --- |
| [Authority Research](protocols/authority-research/README.md) | Build a source-backed research corpus and article-ready evidence packs | flagship |
| [AI Project Docs](protocols/ai-project-docs/README.md) | Generate and maintain repo-grounded project documentation optimized for future AI agents | v2 companion |
| [Deliberate](protocols/deliberate/README.md) | Run lightweight multi-model review rounds for high-tradeoff decisions | companion |
| [Seogo](protocols/seogo/README.md) | Keep long-term project context, session handoff, lessons, and progress in a local knowledge shelf | companion |

## The core pattern

1. The main agent orchestrates. It does not ingest the whole corpus.
2. Workers read bounded inputs and write structured files.
3. Completion is tracked with `done/*.yaml` files, not memory.
4. Claims are separated from sources.
5. High-risk claims are audited before publication or action.
6. A small index tells the next agent where to start.

## Glossary

- **done marker** — a small `done/*.yaml` file a worker writes when its task is finished. The
  orchestrator measures progress by counting these files, not by remembering what happened.
- **claim ledger** — a structured record that keeps each extracted claim attached to its source,
  so high-risk claims can be audited before they are used.
- **axis discovery** — the step that splits a research topic into independent sub-axes, so workers
  can fan out in parallel without repeating each other's work.

## For AI agents

If you are an agent reading this repository, start at [`adapters/README.md`](adapters/README.md)
for vendor-specific notes, then open the target protocol at `protocols/<name>/README.md`. Treat
that protocol spec as the source of truth: read bounded inputs, write your outputs and a
done-marker as described, and keep long material in files rather than in chat history.

## Quick start

For research:

```bash
python3 -m pip install -r requirements.txt
```

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

Assign the generated tasks to whichever agents you use. Each worker writes its outputs and a done
marker. Measure progress with:

```bash
python3 scripts/authority-research/validate_run.py \
  data/authority-research-runs/<run-id>

python3 scripts/authority-research/measure_run.py \
  data/authority-research-runs/<run-id>

python3 scripts/authority-research/make_run_dashboard.py \
  data/authority-research-runs/<run-id>
```

Generate worker prompts from schedule tasks so every worker receives the same instruction
boundary:

```bash
python3 scripts/authority-research/make_worker_prompt.py \
  --run-dir data/authority-research-runs/<run-id> \
  --schedule data/authority-research-runs/<run-id>/schedule/source-scout-schedule.yaml \
  --task-id 001 \
  --contract source-scout
```

For AI project documentation:

```bash
RUN_DIR=$(python3 scripts/ai-project-docs/init_v2_run.py . | python3 -c 'import json,sys; print(json.load(sys.stdin)["run_dir"])')
python3 scripts/ai-project-docs/repo_index.py . \
  --out-dir "$RUN_DIR/source-index"
python3 scripts/ai-project-docs/make_v2_schedule.py \
  "$RUN_DIR/source-index/index-final.json"
```

Then follow [`protocols/ai-project-docs/README.md`](protocols/ai-project-docs/README.md) to
generate worker prompts, merge packets, synthesize docs, validate evidence, and check drift.

## Repository layout

```text
protocols/          Human-readable protocol specifications
templates/          Copyable starter files
scripts/            Small helper scripts for file layout and schedules
adapters/           Notes for Claude, Codex, Gemini, and generic agents
examples/           Minimal examples and run sketches
```

## Non-goals

- No central server.
- No hosted database.
- No vendor-specific lock-in.
- No promise that agents are correct without verification.
- No replacement for source review in high-stakes domains.

## License

MIT
