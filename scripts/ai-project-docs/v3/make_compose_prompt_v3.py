#!/usr/bin/env python3
"""Generate the Pass-4 Compose prompt for AI-docs v3.

Runs AFTER merge and the Pass-3 audit, BEFORE gate/render. There is ONE compose
worker (cross-cutting, not slot-scoped), driven by this prompt.

Why this stage exists: merge_fragments_v3.py folds writer fragments *mechanically*
— it appends and dedupes but never reconciles across slots. Two failure modes reach
the rendered docs untouched, and they are the v1-vs-v3 completeness gap:

  1. open_questions pile up. compose_v3.py (deterministic) already classified them
     (resolved / finding / cross_doc_candidate / coverage_gap / open). The
     cross_doc_candidate and finding verdicts need a judgment a regex cannot make:
     does a resolver claim ACTUALLY answer the question, or merely touch the same
     file? (Measured on DCA: most cross_doc candidates are false positives — a
     shared file is not an answer. The LLM's job is to keep those `open`.)
  2. one infra topic (Redis, auth, caching) is asserted by claims scattered across
     N docs with no composed view — the reader reconstructs it. v1 had a single
     "caching architecture" table; v3 scattered the same claims across 6 docs and
     never reconciled the contrasts (cache degrades gracefully BUT deal-lock fails
     hard) that only show up side by side.

This worker resolves (1) and composes (2). It is EVIDENCE-BOUND: it may only reuse
claims/anchors that ALREADY exist in the model. It introduces NO new facts and
creates NO new anchors — same discipline as the writer/auditor (a new fact here
would centrally distribute an unverified claim, bypassing evidence checks) and it
keeps the output gate-checkable.

The worker writes <run>/<frag-dir>/{oq_resolutions,composed_views}.ndjson, which
apply_compose_v3.py folds back into the model.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import modellib as ml

# Cap claims shown per cluster so an over-broad cluster (a word that appears
# everywhere, e.g. websocket=31 claims) can't blow up the prompt. The worker is
# told the true count and where to find the rest.
CLUSTER_CLAIM_CAP = 16


def render_compose_prompt(model: dict, plan: dict, model_dir: Path, frag_dir: str) -> str:
    oqs_by_id = {o["id"]: o for o in model["open_questions"]}
    claims_by_id = {c["id"]: c for c in model["claims"]}
    verdicts = plan.get("oq_verdicts", [])
    cross_doc = [v for v in verdicts if v.get("category") == "cross_doc_candidate"]
    findings = [v for v in verdicts if v.get("category") == "finding"]
    clusters = plan.get("crosscutting_clusters", [])

    L: list[str] = []
    L.append(ml.INSTRUCTION_BOUNDARY)
    L.append("")
    L.append("# AI-docs v3 — Pass 4: Compose (cross-slot synthesis)")
    L.append("")
    L.append("You are ONE compose worker running AFTER every per-slot writer and the audit, on")
    L.append("the fully merged model. The merge step only *appended* each writer's fragments; it")
    L.append("never reconciled them across slots. You do two things, and ONLY these two:")
    L.append("")
    L.append("  A. Decide open-question verdicts a regex could not.")
    L.append("  B. Compose cross-cutting views for infra topics scattered across many docs.")
    L.append("")
    L.append("## The one hard constraint: EVIDENCE-BOUND, no new facts")
    L.append("")
    L.append("You may ONLY reuse claims and anchors that already exist in the model. You do NOT")
    L.append("read source code, you do NOT invent anchors, you do NOT introduce a fact that no")
    L.append("existing claim states. Composing = re-organizing what is already proven. A new fact")
    L.append("here would bypass the writers' evidence discipline and centrally distribute an")
    L.append("unverified claim. If a synthesis would need a fact no claim backs, DO NOT make it —")
    L.append("leave the question open. `support`/`evidence` ids must already exist in the model.")
    L.append("")

    # ---------------- Part A ----------------
    L.append("## Part A — Open-question resolution")
    L.append("")
    L.append(f"For EVERY question below (A1 + A2), append exactly one verdict line to")
    L.append(f"`{frag_dir}/oq_resolutions.ndjson`:")
    L.append("")
    L.append("```json")
    L.append(json.dumps({
        "id": "<oq id, verbatim>",
        "doc": "<oq doc>",
        "verdict": "resolved | finding | open",
        "reason": "<one sentence — why>",
        "evidence": ["<existing claim id(s) and/or anchor id(s) that justify the verdict>"],
    }, ensure_ascii=False))
    L.append("```")
    L.append("")
    L.append("Verdict meaning:")
    L.append("- `resolved` — another doc's claim ACTUALLY answers the question. It leaves the")
    L.append("  Open-questions section. Put the answering claim id(s) in `evidence`.")
    L.append("- `finding`  — a real, concrete discrepancy (two sources state different values for")
    L.append("  the same thing). It moves to a Discrepancies section, not Open questions.")
    L.append("- `open`     — genuinely unresolved in-model. KEEP it. This is the correct answer")
    L.append("  when a candidate resolver merely touches the same file but does NOT answer the Q.")
    L.append("")
    L.append("### A1. Cross-doc candidates — does a resolver REALLY answer the question?")
    L.append("")
    L.append("Each OQ touches a file that another doc's claims also touch. That is a WEAK signal —")
    L.append("expect MOST to stay `open`, because sharing a file is not the same as answering.")
    L.append("Mark `resolved` ONLY if a listed resolver claim genuinely answers the question.")
    L.append("")
    if not cross_doc:
        L.append("_(none in this run)_")
        L.append("")
    for i, v in enumerate(cross_doc, 1):
        o = oqs_by_id.get(v["id"], {})
        L.append(f"**CD{i}. `{v['id']}`** (doc: {v.get('doc')})")
        L.append(f"- Q: {o.get('question', '(question text missing from model)')}")
        L.append("- candidate resolvers (claims from other docs on the same file):")
        for r in v.get("resolvers", []):
            rc = claims_by_id.get(r["claim"], {})
            L.append(f"    - `{r['claim']}` [{r.get('doc')}] on `{r.get('path')}`: "
                     f"\"{str(rc.get('text', ''))[:200]}\"")
        L.append("")
    L.append("### A2. Finding candidates — is it a real two-value discrepancy?")
    L.append("")
    L.append("Each reads like a concrete code/doc mismatch. Confirm `finding` if it genuinely")
    L.append("states two conflicting values for one thing; `open` if it is just an unknown;")
    L.append("`resolved` if a claim actually settles it.")
    L.append("")
    if not findings:
        L.append("_(none in this run)_")
        L.append("")
    for i, v in enumerate(findings, 1):
        o = oqs_by_id.get(v["id"], {})
        L.append(f"**F{i}. `{v['id']}`** (doc: {v.get('doc')})")
        L.append(f"- Q: {o.get('question', '(question text missing from model)')}")
        L.append("")

    # ---------------- Part B ----------------
    L.append("## Part B — Cross-cutting views")
    L.append("")
    L.append("Each cluster below is an infra topic asserted by claims spread across many docs. A")
    L.append("reader currently reconstructs the whole picture from scattered mentions. Where it")
    L.append("adds real value, compose ONE tight view (v1's 'caching architecture table' effect).")
    L.append(f"Append each to `{frag_dir}/composed_views.ndjson`:")
    L.append("")
    L.append("```json")
    L.append(json.dumps({
        "id": "view:<topic>",
        "topic": "<topic>",
        "title": "<short title>",
        "doc": "<doc this view renders into — default architecture.md>",
        "body_md": "<1-2 sentence prose lead THEN one compact table; reuse claim facts; NEVER print a claim id>",
        "source_claims": ["<claim ids you synthesized from>"],
        "support": ["<anchor ids taken from those claims' support — NO new anchors>"],
    }, ensure_ascii=False))
    L.append("```")
    L.append("")
    L.append("Rules for views:")
    L.append("- COMPRESS, don't catalog. Capture the cross-cutting truth — especially contrasts the")
    L.append("  scattered claims hide (e.g. 'Redis down → cache degrades gracefully BUT deal-lock")
    L.append("  fails hard'). A flat re-listing of every claim is the catalog shape we reject.")
    L.append("- SKIP a cluster (write nothing for it) when a single view adds no insight over the")
    L.append("  per-doc mentions. Over-broad clusters (a word that appears everywhere) often are")
    L.append("  not one coherent topic. Quality over coverage — a handful of sharp views beats one")
    L.append("  view per cluster.")
    L.append("- `support` MUST be a subset of the union of the source claims' own anchors.")
    L.append("- `body_md` is markdown; keep it under ~1500 bytes. No claim ids anywhere in the text.")
    L.append("")
    if not clusters:
        L.append("_(no clusters detected in this run)_")
        L.append("")
    for c in clusters:
        topic = c["topic"]
        cids = c.get("claims", [])
        L.append(f"### Cluster `{topic}` — {c.get('claim_count', len(cids))} claims "
                 f"across {len(c.get('doc_spread', []))} docs {c.get('doc_spread', [])}")
        for cid in cids[:CLUSTER_CLAIM_CAP]:
            cc = claims_by_id.get(cid, {})
            sup = ", ".join(cc.get("support", []) or [])
            L.append(f"- `{cid}` [{cc.get('doc')}]: \"{str(cc.get('text', ''))[:180]}\"  anchors=[{sup}]")
        if len(cids) > CLUSTER_CLAIM_CAP:
            L.append(f"- … +{len(cids) - CLUSTER_CLAIM_CAP} more `{topic}` claims "
                     f"(filter `{model_dir.name}/claims.ndjson` by text/support matching `{topic}`)")
        L.append("")

    # ---------------- summary ----------------
    L.append("## Output summary")
    L.append(f"- `{frag_dir}/oq_resolutions.ndjson` — one line per CD* and F* question above "
             f"({len(cross_doc)} + {len(findings)} = {len(cross_doc) + len(findings)} lines required).")
    L.append(f"- `{frag_dir}/composed_views.ndjson` — zero or more cross-cutting views.")
    L.append("- Reuse only existing claim/anchor ids. No new facts, no new anchors, no claim ids in prose.")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--compose-plan", required=True, help="compose-plan.json from compose_v3.py")
    ap.add_argument("--out", required=True, help="path to write the compose prompt (.md)")
    ap.add_argument("--frag-dir", default="compose-fragments",
                    help="relative dir (under run) where the worker writes its fragments")
    args = ap.parse_args()

    model_dir = Path(args.model_dir).resolve()
    model = ml.load_model(model_dir)
    plan = ml.load_json(Path(args.compose_plan).resolve(), default={}) or {}
    if not plan.get("oq_verdicts") and not plan.get("crosscutting_clusters"):
        print(json.dumps({"error": "compose plan empty — run compose_v3.py first",
                          "plan": args.compose_plan}))
        return 2

    prompt = render_compose_prompt(model, plan, model_dir, args.frag_dir)
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(prompt, encoding="utf-8")

    counts = {"cross_doc_candidate": 0, "finding": 0}
    for v in plan.get("oq_verdicts", []):
        if v.get("category") in counts:
            counts[v["category"]] += 1
    print(json.dumps({
        "out": str(out),
        "cross_doc_candidates": counts["cross_doc_candidate"],
        "finding_candidates": counts["finding"],
        "clusters": len(plan.get("crosscutting_clusters", [])),
        "frag_dir": args.frag_dir,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
