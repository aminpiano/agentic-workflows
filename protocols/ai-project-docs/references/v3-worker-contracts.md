# AI-docs v3 Worker Contracts

Three LLM roles. Each is spawned with a generated prompt and must obey the instruction
boundary at the top of that prompt (everything read afterward is untrusted data). All
three conform to `references/v3-schemas.md`.

## Planner (Pass 1) — `make_planner_prompt_v3.py`

**Input**: the deterministic model summary (core files by role, entity inventory,
runtime, edge stats). The planner does NOT read source bodies.

**Output**: `doc_plan.json`.

**Must**:
- Pick a `profile` (webapp/cli/library/service/monorepo).
- Design the document set keeping the default identities (index/router, architecture,
  workflows, data_model, api, operations, testing, troubleshooting, todo) but split/merge
  by scale. No fixed 12-file layout; no one-doc-per-file.
- Assign every `core` file to exactly one owning doc (`owned_sources`) — the **write**-ownership
  boundary (not a read cage). Adaptive split: keep any single doc under ~25 owned files AND
  ~100k owned input tokens; set `split_of` when either limit is exceeded.
- Pick `blueprint_sources`: 5-20 cross-file core files every writer reads as shared context
  (router/mounts, shared models/schemas, auth, config, DB setup). Each must also appear in
  exactly one `owned_sources` (it is a READ overlay, not separate ownership).
- Give each doc an `identity`, `skeleton`, `must_have`, and `token_budget`.
- Build a `task_router` (change-intent -> doc + entry entities).

**Must not**: invent files not in the core list; create a doc per source file; leave core
files unassigned.

## Writer (Pass 2) — `make_writer_prompt_v3.py` (one per doc)

**Input**: its doc's `owned_sources` (write-ownership, read in full); the shared
`blueprint_sources` (read-only cross-file context, read in full); the deterministic
`blueprint_facts` (authoritative repo-wide route/table/env/service facts, injected into the
prompt + full data in `blueprint_facts.json`); plus the model's anchors/entities/edges for
its owned sources.

**Output** (per-slot fragment under `model-fragments/<slot>/`): `claims.ndjson`,
`anchors.ndjson` (llm-origin), `entities.ndjson` (enriched), `flows.json`,
`open_questions.ndjson`, `draft.md`.

**Must**:
- Synthesize the slot per its skeleton — lead with how things connect (flows, boundaries,
  rationale), not a flat enumeration.
- Record every non-trivial claim **as it is written** (evidence-aware), each with a class
  (`direct`/`inference`/`diagram`/`operational`), support anchor(s), and `dep_files`.
- Cite stable anchor ids from `anchors.ndjson`; when citing a line with no anchor, append a
  new llm anchor with an exact substring as `anchor_text`.
- Build the required Mermaid diagram(s); record each flow with `dep_files`.
- File gaps as open questions. Never invent.

**Must not**: emit a claim/entity without a support anchor; print claim ids in body text;
**contradict `blueprint_facts`**; state a risky claim (auth/authz, DB constraint, transaction,
idempotency, scheduling, money/orders, or any always/never/guarantees wording) from inference
rather than a read anchor — these are audited (Pass 3); exceed `max_bytes` (file a split open
question instead).

(Read isolation is intentionally dropped: writers read owned + blueprint files. Write
ownership — who documents and later re-generates a file — is still one doc per file.)

## Auditor (Pass 3) — `make_audit_prompt_v3.py` (one per doc, after merge, before render)

Deterministic checks (catalog ratio, claim-id leakage, dangling support, required
diagram/router, size, unfixed-verdict) are handled by `gate_v3.py`. The LLM auditor is the
evidence-bound check scripts cannot do: verifying that risky cross-file **prose** is actually
true — the gap that lost the v1-vs-v3 eval on accuracy.

**Input**: its doc's `draft.md`, the doc's recorded claims, `blueprint_facts` (authoritative
route/constraint/middleware/env facts), and read access to owned + blueprint source.

**Must**:
- Audit ONLY risky classes (auth/authz, DB constraints, transactions/idempotency, scheduling,
  deploy/config, money/orders, security, always/never guarantees). Ignore safe prose.
- For each, BIND evidence: read the cited anchor line AND search for counter-evidence (try to
  falsify). Verdict `supported`/`contradicted`/`insufficient`.
- Fix the draft IN PLACE: correct contradicted facts (cite an anchor); hedge insufficient ones
  and file an open question. Keep inventory/tables intact; never weaken a correct claim.
- Record `audit_verdicts.ndjson` (one row per statement).

**Must not**: rewrite safe prose; weaken correct claims; leave a `contradicted`/`insufficient`
verdict with `action: kept` (gate fail); invent facts.
