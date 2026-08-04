# Seogo

Seogo means "book storage" or "archive shelf." In this repository, it means a local project context shelf for AI collaboration.

It is a filesystem convention for long-term project memory that remains outside any single vendor's hidden memory system.

## Problem

Agent sessions lose context. Hidden memory systems are useful, but they are not portable, auditable, or easy to hand off across tools.

Seogo keeps the durable part of project memory in project files.

## Layout

```text
seogo/
  seogo_index.md
  seogo_progress.md
  seogo_failure-patterns.md
  topics/
  ideas/
  lessons/
  research/
context/
  001-YYYY-MM-DD-01.md
  002-YYYY-MM-DD-02.md
```

## Roles

| File or folder | Role |
| --- | --- |
| `seogo_index.md` | Router. One-line summaries and pointers only. |
| `seogo_progress.md` | Current project dashboard. Not a changelog. |
| `seogo_failure-patterns.md` | Reusable mistakes and discarded approaches. |
| `topics/` | Research notes, technical notes, comparisons. |
| `ideas/` | Idea records with status and stage. |
| `lessons/` | Debugging lessons and operating lessons. |
| `context/` | Session handoff logs. Same autonomy as `seogo/` — written by an agent, read by the next one. |

## Document Style

Use:

- YAML frontmatter
- stable slugs
- wiki links like `[[topic-slug]]`
- tags as simple arrays
- short indexes, detailed notes in separate files

Example:

```yaml
---
status: active
stage: validating
created: 2026-01-01
updated: 2026-01-02
tags: [research, agent]
related: [[authority-research]]
---
```

## Session Handoff

A session log has two halves, separated by explicit markers:

```markdown
<!-- HANDOFF-START -->
## Next Session Start Guide
...
<!-- HANDOFF-END -->
```

**Only the marked region is injected into the next session.** Everything outside it
is archive — on disk and greppable, but the next agent gets no signal that it exists
and will not go looking for it.

The marked region should tell the next agent:

- what was just decided
- what files matter
- what to do first
- what not to repeat
- what is blocked
- **what it must not re-derive** — the diagnosis or measurement the actions depend on

That last item is the one most often missed. Writing "the root cause was X" outside
the markers means the next agent re-investigates X from scratch. Duplicating two
lines into the region is cheaper than one re-investigation.

Budget the region at roughly 4 KB. Leave the archive unbounded — it costs nothing
per session, so writing it thin to look disciplined helps no one.

Markers rather than a heading name, for two reasons. Heading spellings drift across
projects and languages, and an extractor that matches one spelling fails silently on
the rest. More fundamentally: which part of a given session matters next time is a
judgement about content, and no script has that. The agent writing the log does.

Do not try to preserve the whole conversation. Preserve the next useful state.
