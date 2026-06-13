# AI Docs Specification

Status: v1 legacy specification.

Use this specification only for the fixed 12-document v1 layout. For the current v2 workflow,
start with `protocols/ai-project-docs/README.md` and
`protocols/ai-project-docs/references/v2-mode.md`.

## Hard Rules

- Write only from repository evidence.
- Use `UNKNOWN` when a fact cannot be confirmed.
- Use `N/A` when a section does not apply.
- Never record secret values.
- Every document ends with `## Evidence`.
- Prefer tables, lists, and code blocks over prose.
- `00_INDEX.md` is written last.
- Record the documented commit hash.

## Documents

| File | Purpose |
| --- | --- |
| `00_INDEX.md` | Entry point. Read first. |
| `01_ENVIRONMENT.md` | Runtime, commands, env vars without values. |
| `02_DEPENDENCIES.md` | Package managers, dependencies, external services. |
| `03_ARCHITECTURE.md` | System structure and data flow. |
| `04_STRUCTURE.md` | Directory map and entry points. |
| `05_DATA_MODELS.md` | Database schemas, types, persistence. |
| `06_API.md` | HTTP endpoints, RPC, auth, integrations. |
| `07_BUSINESS_LOGIC.md` | Core behavior and workflows. |
| `08_DEBUG.md` | Logs, tests, common failures, troubleshooting. |
| `09_STANDARDS.md` | Local conventions and anti-patterns. |
| `10_WARNINGS.md` | Risky areas, side effects, do-not-touch zones. |
| `11_TODO.md` | Known bugs, incomplete features, future work. |

## Generation Flow

1. Scout the repository and write `.skeleton.md`.
2. Write documents from the skeleton and relevant source files.
3. Review documents against the source.
4. Cross-check references and shared facts.
5. Write `00_INDEX.md`.

## Evidence Format

Each document ends with:

```markdown
## Evidence

- `package.json`
- `src/app/page.tsx`
- `docker-compose.yml`
```

## Update Mode

1. Read the previous documented commit from `00_INDEX.md`.
2. Run a git diff from that commit to current HEAD.
3. Map changed files to affected docs.
4. Audit affected docs.
5. Edit only the docs that need changes.
6. Update `00_INDEX.md` metadata.
