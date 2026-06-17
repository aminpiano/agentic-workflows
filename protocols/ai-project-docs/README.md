# AI Project Docs

AI Project Docs is a protocol for generating documentation that lets future AI agents work on a codebase quickly and safely.

## Current Default: v1.5

Use **v1.5** for active work.

Canonical active skill:

```text
/home/s-office/projects/ai-docs
```

The server-wide Claude/Codex skill symlinks point there. This `agentic-workflows` directory keeps historical design material, not the active implementation.

## v1.5 Shape

v1.5 keeps the v1 12-file output because that shape is still the most useful for feature implementation, implementation simulation, and bug fixing:

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

The v1.5 change is agent allocation, not output shape:

```text
scout team
  -> .skeleton.md
     -> shared facts
     -> file-to-document map
     -> workload matrix
     -> agent assignment plan
  -> workload-based writer team
  -> workload-based reviewer team
  -> cross-checker
  -> 00_INDEX.md
```

The 12 documents are the final contract. They are not the writer/reviewer partition. Large API, schema, or business-logic areas must get dedicated or split agents when the workload matrix says they are heavy.

## Archive

v2/v3 material is archived under:

```text
protocols/ai-project-docs/_archive/
scripts/ai-project-docs/_archive/
```

Do not route active work to v2/v3/v4 unless the user explicitly asks for historical comparison or recovery.
