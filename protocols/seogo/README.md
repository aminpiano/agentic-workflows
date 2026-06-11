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
| `context/` | Session handoff logs. |

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

The most important section in a session log is:

```markdown
## Next Session Start Guide
```

It should tell the next agent:

- what was just decided
- what files matter
- what to do first
- what not to repeat
- what is blocked

Do not try to preserve the whole conversation. Preserve the next useful state.
