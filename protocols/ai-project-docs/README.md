# AI Project Docs

AI Project Docs is a protocol for generating and maintaining documentation that helps future AI agents work on a codebase.

The audience is not a human manager. The audience is the next agent that has to understand the project quickly and safely.

## Problem

Code search is not enough. A codebase index can tell an agent where files are, but it often misses:

- why the project is shaped that way
- how to run and debug it
- which files are dangerous to edit
- what decisions are already settled
- which behavior is known but not obvious from file names
- what changed since the last documentation pass

## Output Set

```text
ai-docs/
  SPEC.md
  .skeleton.md
  00_INDEX.md
  01_ENVIRONMENT.md
  02_DEPENDENCIES.md
  03_ARCHITECTURE.md
  04_STRUCTURE.md
  05_DATA_MODELS.md
  06_API.md
  07_BUSINESS_LOGIC.md
  08_DEBUG.md
  09_STANDARDS.md
  10_WARNINGS.md
  11_TODO.md
```

## Generation Flow

```text
scout
  -> skeleton
  -> parallel doc writers
  -> parallel reviewers
  -> cross-checker
  -> 00_INDEX.md
```

### Scout

The scout reads the project and writes `.skeleton.md`.

The skeleton contains:

- shared facts
- runtime and framework versions
- entry points
- important file-to-document mappings
- cross-reference targets
- known risks
- update manifest

### Writers

Writers read only:

- `SPEC.md`
- `.skeleton.md`
- source files relevant to their assigned docs

They write assigned documentation files.

### Reviewers

Reviewers re-read the source and fix gaps. The cross-checker runs last and verifies:

- all files exist
- evidence sections exist
- cross-references resolve
- shared facts match
- quick start commands are plausible
- warnings and TODOs do not conflict

## Update Flow

```text
git diff from previous documented commit
  -> affected-doc estimate
  -> audit
  -> refactoring list
  -> selective edits
  -> review
  -> updated index
```

Update mode should edit only affected docs. Full regeneration is a fallback, not the default.

## Writing Rules

- Write only from repository evidence.
- Use `UNKNOWN` for facts that cannot be confirmed.
- Never record secret values.
- Every doc ends with `## Evidence`.
- Prefer tables, lists, and code blocks over prose.
- Keep the docs portable across agents and vendors.

## Why This Matters

For non-developers using AI to build software, the bottleneck is often not code generation. It is project continuity. AI Project Docs turns project context into a durable, inspectable layer that survives session resets and tool changes.
