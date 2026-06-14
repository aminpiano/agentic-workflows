# AI Project Docs — v3 Redesign Roadmap

**Status:** design-frozen, implementation pending. The current shipped default is **v2**
(see [`README.md`](README.md)). v3 is a planned redesign; nothing here is wired yet.

This document records *what v3 should become and why*, so implementation can proceed
directly from a settled design instead of re-arguing it. It is the output of an
adversarial multi-model deliberation (provenance at the bottom).

---

## The core question

What kind of document best serves an AI agent working on a project?

- **Philosophy 1 — self-contained:** the doc replicates enough code facts (signatures,
  schema columns, enums) that an agent can work *without reading code*.
- **Philosophy 2 — code-companion:** the doc carries what code *lacks* (design intent,
  cross-file flows, risk map, entry points, precise anchors) and points to code for the
  facts themselves.

## The decision: hybrid, not a pure philosophy

Philosophy 2 is the right default — code-facts replicated as prose become a second source
of truth that inevitably drifts, and the consumer (an AI agent) can read code. **But the
exclusive "never replicate facts" stance breaks** for real consumers whose code access is
limited or expensive: multi-repo service boundaries, regulated/vendor sandboxes, giant
monorepos where re-reading code each time is costly, and context-density limits ("lost in
the middle"). For those, a self-contained contract layer is not optional.

So v3 is a **two-layer hybrid**:

- **`core/` — self-contained layer.** Service/data contracts + a bounded *factual cache*.
  Enough to orient and propose bounded changes *without code access*. Must NOT bloat back
  into v1 (full code mirror).
- **`extended/` — code-linked layer.** Anchors, flow views, deeper synthesis for consumers
  with full code access.
- Both layers render from a **single claim ledger**, so they cannot drift apart.

## Design decisions

1. **Two-layer structure from one claim ledger.** core (contract + factual cache) +
   extended (anchors + views), rendered from one model so the layers stay consistent.
   A non-code-access consumer can strip the extended/anchor blocks (delimited markup).

2. **Anchors: location → structure.** Replace `file:line` with AST/semantic anchors
   (tree-sitter symbol path) + snippet hash + commit SHA. Goal is **drift-*detectable***,
   not drift-*resistant*: a broken anchor must fail loudly (`check` reports stale) rather
   than silently point at the wrong code. (file:line breaks on any reformat/move; a
   stale anchor that the agent trusts is a silent bug.)

3. **Factual cache is a first-class feature, not a fallback.** Generated blocks
   (`<!-- generated … freshness=… commit=… -->`) for high-value facts: external contracts
   (routes, public API, event topics), data contracts (key tables, unique indexes, FKs,
   state enums), runtime entry points, high-fan-in nodes, operational facts (env, flags).
   **Boundary is auto-decided by structural topology + churn**, not by guessed "frequency":
   ingress/egress always cached; high-fan-in cached; high-churn → anchor-only (caching
   volatile facts just re-creates drift); per-category top-N (not global top-N); config
   override (`include`/`exclude`/`hot_paths`). What stays anchor-only: local helpers,
   private signatures, full enum/type dumps, generated code, single-file detail.

4. **Cross-cutting pre-composition: deferred.** Building accurate multi-file flow diagrams
   statically is the hardest piece and the easiest to get plausibly-but-wrongly. MVP is a
   simple `entrypoint → handler → persistence/event` graph only; rich Mermaid/pseudocode
   waits.

5. **Evaluation: blind doc-scoring → task-based eval.** Scoring two doc sets *with code
   withheld from the judge* cannot measure accuracy — an evaluator without ground truth
   misjudges conflicting factual claims (observed: a correct claim scored as a
   hallucination because the judge couldn't check the code). Replace with: tasks derived
   from historical commits (parent commit as start, commit/issue as prompt, ground-truth
   checklist extracted from the commit), automated test/check scoring (not a model judge),
   **generator-model ≠ solver-model split**, a fixed held-out task set, blinded bundle
   names, and canary tasks (a deliberately stale claim, to catch doc over-trust).

## Implementation priority (ROI)

1. **Anchors** (tree-sitter symbol + snippet hash + commit SHA; `check` flags stale).
2. **Factual cache** (generated blocks + freshness grade + topology/churn boundary).
3. Eval harness — build alongside, small, early (process tool, not a shipped feature).
4. *(Deferred)* Cross-cutting pre-composition beyond the simple graph.

## Repo-philosophy constraints

This repo is vendor-neutral, file-based, **no runtime, nothing to import** — the contract
is files on disk. v3 must honor that:

- The contract stays **protocol spec + templates**; Python stays a *helper* (prompt
  generation, merge, anchor check), never the product.
- A consumer must be able to run v3 with any file-capable agent. No hard dependency on one
  model or CLI.
- v3 is added as **experimental alongside v2**; v2 (stable) is not touched until v3 is
  task-eval-validated.

## Open questions (resolve before / during implementation)

- **Factual-cache depth: default vs `--profile`.** Most real usage is full-code-access
  single-repo, where a heavy core risks v1-style bloat. Likely answer: light by default,
  thick only under an explicit capsule profile for code-restricted targets.
- **v2 ↔ v3 worth-it check.** v2 already has native indexing + evidence/drift checks. Is
  v3's model-first increment (model + anchors + evidence-bound audit) worth the added
  weight over v2? Pending a direct code comparison before heavy v3 build.

## Provenance

- Adversarial deliberation: Claude (Anthropic) + Codex (OpenAI GPT) + Antigravity
  (Google Gemini), 2 rounds, 2026-06-15. Members were instructed to *refute*, not agree;
  the convergences above survived that.
- The two models independently converged on the hybrid conclusion and each revised their
  own round-1 stance (from "anchors only" toward "factual cache is core").
