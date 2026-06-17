# AI-docs v3 Schemas

This reference is the **source of truth** for every v3 artifact. The deterministic
indexer, the LLM worker prompts, the gate/validator, the renderer, and the drift
checker all conform to the contracts below. Change this file first, then the code.

## Core model (the v3 inversion)

v3's first-class output is a **structured architecture model** in `ai-docs/.model/`.
Markdown under `ai-docs/` is a **second-class, regeneratable view** of that model.
The AI entrypoint (`ai-docs/00_INDEX.md`) is a thin router that points at the model.

```text
ai-docs/
  .model/                 # 1st-class: the architecture model (machine source-of-truth)
    manifest.json
    file_index.ndjson
    anchors.ndjson
    entities.ndjson
    edges.ndjson
    flows.json
    runtime.json
    doc_plan.json
    claims.ndjson
    open_questions.ndjson
    render_state.json
  00_INDEX.md             # 2nd-class view: thin Task Router pointing at the model
  architecture.md         # 2nd-class view: rendered from the model
  ...                     # other profile docs, all regeneratable
  ai-project.yaml         # config (version: 3)
  .work/<run-id>/         # transient run staging (never the source of truth)
```

**Invariant 1** — markdown is never authored by hand and never the source of truth.
Editing markdown directly is a drift, not a fix.

**Invariant 2** — every LLM-originated claim/entity/edge MUST carry at least one
`support` anchor id. Items without support cannot enter the model. The gate rejects
the run if this is violated.

**Invariant 3** — the model never stores file *bodies*, normalized symbol body
hashes, complete call graphs, or per-helper symbol trees. It stores actionable
structure + a claim ledger + anchors. (Storing bodies = catalog + size blowup +
the v2 failure, structured.)

## ID conventions

Stable, content-derived ids so re-runs and diffs are stable:

- anchor id: `a:<path>:<anchor_line>:<kind>` (e.g. `a:src/app/main.py:42:signature`)
- entity id: `<kind>:<name>` (e.g. `route:GET /api/users`, `service:BillingService`, `process:web`)
- edge id: `<kind>:<src>->|<dst>` (e.g. `import:src/a.py->|src/b.py`)
- claim id: `<doc_slot>.<topic>[.<n>]` (e.g. `architecture.entrypoint.web`). NEVER rendered into markdown body text.
- flow id: `flow:<kind>:<slug>` (e.g. `flow:request:user-create`)

## `ai-project.yaml`

```yaml
version: 3
generation: v3
profile: auto            # auto | webapp | cli | library | service | monorepo
mode: full               # full | fast | update (default run mode hint)
model_dir: ai-docs/.model
budget:
  full:  { wall_min: 40, llm_input_tokens: 4000000, output_tokens: 300000 }
  fast:  { wall_min: 15, llm_input_tokens: 2000000, output_tokens: 250000 }
  update:{ wall_min: 3,  llm_input_tokens: 250000 }
evidence_policy:
  default: tracked       # strict | tracked | none
  architecture: strict
  api: strict
outputs:
  format: model-plus-views
  router: ai-docs/00_INDEX.md
```

## `.model/manifest.json`

Run-level metadata + integrity hashes. The renderer and drift checker read this first.

```json
{
  "version": 3,
  "kind": "ai-docs-v3-architecture-model",
  "generated_at": "ISO-8601",
  "root": "/abs/project",
  "commit": "abc1234",
  "profile": "webapp",
  "mode": "full",
  "source": "git-ls-files",
  "budget": { "wall_min": 40, "llm_input_tokens": 4000000, "output_tokens": 300000 },
  "spend": { "files_indexed": 0, "files_read_by_llm": 0, "est_input_tokens": 0 },
  "counts": {
    "files": 0, "files_core": 0, "files_defer": 0, "files_exclude": 0,
    "anchors": 0, "entities": 0, "edges": 0, "claims": 0, "flows": 0, "open_questions": 0
  },
  "model_files": {
    "file_index.ndjson": "sha256",
    "anchors.ndjson": "sha256",
    "entities.ndjson": "sha256",
    "edges.ndjson": "sha256",
    "flows.json": "sha256",
    "runtime.json": "sha256",
    "claims.ndjson": "sha256",
    "doc_plan.json": "sha256"
  },
  "generators": {
    "index_v3.py": "deterministic",
    "ops": "deterministic",
    "planner": "llm",
    "writer": "llm",
    "render": "deterministic+llm"
  },
  "degraded": null
}
```

`degraded` is `null` on a normal run, or an object `{ "level": "model-only"|"router-only",
"reason": "..." }` when a budget ceiling forced an explicit downgrade. Silent quality
degradation is forbidden (decision 9).

## `.model/file_index.ndjson`

One JSON object per line. Extends the v2 source index record with read-ownership and
tier, which drive the read-once cost discipline (decision 4).

```json
{"path":"src/app/main.py","language":"python","role":"source","bytes":8421,"lines":[1,210],"sha256":"hex","token_estimate":1800,"tier":"core","owner_slot":"architecture","read_owner":"writer:architecture","ignored":false,"ignore_reason":null}
```

- `tier`: `core` (top ~10%, LLM reads directly) | `defer` (indexed, not LLM-read) | `exclude` (binary/secret/large/profile-skipped).
- `owner_slot`: the doc slot that owns this file for synthesis (set by the planner; `null` until planning).
- `read_owner`: the single agent allowed to read this slice (`writer:<slot>` / `planner` / `null`). Prevents re-reads.

Ignored/deferred/excluded records keep `sha256`/`lines` when cheaply available, else `null`.

## `.model/anchors.ndjson`

The evidence substrate. Deterministic anchors are emitted by `index_v3.py`; LLM workers
may add anchors **only** for lines they actually read, with exact `anchor_text`.

```json
{"id":"a:src/app/main.py:42:signature","path":"src/app/main.py","anchor_text":"def create_app(","anchor_line":42,"file_sha256":"hex","kind":"signature","policy":"strict","origin":"deterministic"}
```

- `kind`: `signature` | `route` | `import` | `env` | `job` | `config` | `process` | `port` | `table` | `generic`.
- `anchor_text`: an **exact substring** present in the file at `anchor_line`. This is what drift matching uses. Never a paraphrase.
- `policy`: `strict` | `tracked` | `none` (see Drift policy).
- `origin`: `deterministic` | `llm`.

## `.model/entities.ndjson`

Architectural units. Deterministic candidates (route/job/env/process/port/table/class/func
signatures) are seeded by the indexer; the LLM enriches importance/summary/rationale and
adds module/service-level entities that require judgment.

```json
{"id":"route:GET /api/users","kind":"route","name":"GET /api/users","title":"List users","path":"src/api/users.py","anchor_id":"a:src/api/users.py:10:route","importance":"high","summary":"Returns paginated user list.","rationale":null,"origin":"deterministic","support":["a:src/api/users.py:10:route"]}
```

- `kind`: `process` | `service` | `module` | `route` | `table` | `model` | `job` | `config` | `external`.
- deterministic-origin entities have `importance`/`summary`/`rationale` = `null` until the LLM enriches them.
- `support`: anchor ids. Required for every entity (Invariant 2).

Explicitly **excluded** entity kinds (Invariant 3): individual helper/util functions, UI
leaf components, getters/setters, and any symbol that is not an entrypoint, boundary,
process, route, table, job, config surface, or named architectural service/module.

## `.model/edges.ndjson`

Typed relationships between entities (or files).

```json
{"id":"import:src/api/users.py->|src/services/billing.py","kind":"import","src":"module:src/api/users.py","dst":"service:BillingService","path":"src/api/users.py","anchor_id":"a:src/api/users.py:3:import","origin":"deterministic","support":["a:src/api/users.py:3:import"],"rationale":null}
```

- `kind`: `import` | `route_handler` (route→handler) | `handler_service` (handler→service) | `service_table` (service→table) | `job_handler` (job→handler) | `process_service` (process→service).
- `import` edges are deterministic (regex import literals). The semantic edges
  (`handler_service`, `service_table`, etc.) are LLM-origin and **must** carry support anchors.

## `.model/flows.json`

LLM-synthesized request/data/scheduler/worker flows. This is where v1-grade synthesis
lives (the thing v2 lost). Each flow carries `dep_files` so the drift checker can flag it.

```json
{
  "version": 3,
  "flows": [
    {
      "id": "flow:request:user-create",
      "kind": "request",
      "title": "Create user request path",
      "steps": [
        {"entity": "route:POST /api/users", "note": "validates payload"},
        {"entity": "service:UserService", "note": "hashes password"},
        {"entity": "table:users", "note": "insert"}
      ],
      "support": ["a:src/api/users.py:22:route", "a:src/services/user.py:14:signature"],
      "dep_files": ["src/api/users.py", "src/services/user.py"],
      "origin": "llm"
    }
  ]
}
```

- `kind`: `request` | `data` | `scheduler` | `worker` | `startup`.
- `dep_files`: the set of files this flow's correctness depends on. If any `dep_files`
  sha256 changes, the flow is flagged `soft` for LLM re-review (decision 5).

## `.model/runtime.json`

Deterministic, repo-only ops topology (host probes only with explicit `--host-readonly`).
Derived from `ops_inventory.py`.

```json
{
  "version": 3,
  "kind": "ai-docs-v3-runtime",
  "mode": "repo-only",
  "processes": [
    {"name": "web", "manager": "pm2", "command": "node server.js", "path": "ecosystem.config.js", "anchor_id": "a:ecosystem.config.js:4:process", "port": "3000"}
  ],
  "services": [
    {"name": "app", "kind": "docker-compose", "path": "docker-compose.yml", "ports": ["8080:80"], "domains": ["app.example.com"], "anchor_id": "a:docker-compose.yml:1:config"}
  ],
  "env_keys": [{"key": "DATABASE_URL", "path": ".env.example", "anchor_id": "a:.env.example:1:env"}],
  "topology": [{"src": "service:app", "dst": "process:web", "note": "compose runs web"}],
  "safety": {"writes_performed": false, "sudo_used": false, "secret_values_recorded": false}
}
```

Env files contribute **key names only**. Secret values are never recorded.

## `.model/doc_plan.json`

The planner's output. This is where document boundaries are decided (decision 8 —
"catalog is a planning failure, not a writing failure"). The gate enforces size/coverage/
ownership/token budget against this plan.

```json
{
  "version": 3,
  "profile": "webapp",
  "mode": "full",
  "docs": [
    {
      "doc": "architecture.md",
      "slot": "architecture",
      "identity": "How the system is wired: entrypoints, process topology, module boundaries, request/data flows.",
      "skeleton": ["Entrypoints", "Process topology", "Module boundaries", "Request flows", "Data flows"],
      "must_have": ["mermaid", "process_topology"],
      "owned_sources": ["src/app/main.py", "src/api/users.py"],
      "token_budget": 6000,
      "max_bytes": 24000,
      "split_of": null
    }
  ],
  "task_router": [
    {"intent": "add an API endpoint", "doc": "api.md", "entities": ["route:GET /api/users"]},
    {"intent": "change a background job", "doc": "operations.md", "entities": ["job:nightly-billing"]}
  ]
}
```

Default profile identities (split/merge by scale, never a fixed 12-file regression):
`index/router` · `architecture` · `workflows` · `data_model` · `api` · `operations` ·
`testing` · `troubleshooting` · `todo`. The planner keeps these identities and
splits a slot into `architecture.md` + `architecture-<area>.md` (with `split_of`) when a
slot exceeds its `max_bytes`.

## `.model/claims.ndjson`

The claim ledger — every non-trivial statement a rendered doc makes, with its class,
support, and the doc it appears in. Written **during** synthesis (evidence-aware), not
post-hoc.

```json
{"id":"architecture.entrypoint.web","text":"The HTTP app is constructed by create_app() in src/app/main.py.","class":"direct","doc":"architecture.md","support":["a:src/app/main.py:42:signature"],"dep_files":["src/app/main.py"],"confidence":"high","rendered":true}
```

- `class`:
  - `direct` — supported by a single anchor on one file (high drift confidence).
  - `inference` — cross-file reasoning; `dep_files` lists every file it depends on.
  - `diagram` — backs a Mermaid/diagram edge; `dep_files` = files the diagram asserts.
  - `operational` — from `runtime.json` (compose/process/env/port).
- `text`: the human-readable claim. Must NOT contain the claim id.
- `rendered`: whether this claim currently appears in its doc view.

## `.model/open_questions.ndjson`

```json
{"id":"oq:auth.session-store","question":"Session store backend is referenced but not defined in-repo.","doc":"architecture.md","raised_by":"writer:architecture","support":["a:src/auth/session.py:8:import"]}
```

Unknowns stay explicit. The writer never fills a gap with invention; it files an open
question instead.

## `.model/render_state.json`

Links each rendered markdown view to the model hashes it was rendered from. This is the
substrate for layer-2 (model→markdown) drift.

```json
{
  "version": 3,
  "rendered_at": "ISO-8601",
  "docs": [
    {
      "doc": "architecture.md",
      "rendered_at": "ISO-8601",
      "doc_sha256": "hex",
      "model_inputs": {"claims_sha256": "hex", "entities_sha256": "hex", "edges_sha256": "hex", "flows_sha256": "hex"},
      "gate": "pass"
    }
  ]
}
```

## Drift policy (3 layers, decision 5 & 6)

The model is the source of truth. Code change → update model (resolve drift) → re-render.

**Layer 1 — repo → model** (per anchor in `anchors.ndjson`):

| condition | status | action |
|---|---|---|
| `file_sha256` unchanged | `clean` | none (zero compute) |
| `file_sha256` changed, `anchor_text` still present | `soft` | refresh `anchor_line`, no warning |
| `file_sha256` changed, `anchor_text` gone | `hard` | queue owning slot for re-synthesis |
| file missing | `hard` | queue owning slot |
| `policy: none` | `skipped` | — |

For `inference`/`diagram` claims: if any `dep_files` sha256 changed → `soft` warning →
LLM re-review (even if individual anchors survive). This is the Silent-Drift guard
(Redis→RabbitMQ swap that leaves an anchor alive is still caught via dep_files).

**Layer 2 — model → markdown** (per doc in `render_state.json`):
if a doc's `model_inputs` hashes ≠ current model hashes → `view_stale` → re-render needed.

**Layer 3 — markdown quality** (per doc): the rendered view must still pass the gate
(`gate_v3.py`). A view that regressed into catalog shape is `gate_fail`.

**Non-goal**: v3 does NOT prove a claim is *true*. It proves (a) support anchors are
still alive, and (b) which claims are due for re-review. Automatic truth-proving is the
parser trap and is explicitly out of scope (decision 5, top risk).

## Deterministic vs LLM boundary (decision 3)

| deterministic (scripts) | LLM (workers) |
|---|---|
| file list / sha256 / size / lines / token est | component meaning + importance |
| git metadata, commit | "why this edge matters architecturally" |
| import literals → import edges | flow synthesis (request/data/scheduler) |
| route literals (`@app.get`, `app.route`, etc.) | doc boundary semantics |
| env keys, job schedule literals | Mermaid diagram structure |
| process/port/compose config | cross-file inference, open-question judgment |
| class/def/table signature lines | rationale prose |
| line anchors, tier/budget | — |

Hard rule: an LLM claim cannot enter the model without a support anchor (Invariant 2).
