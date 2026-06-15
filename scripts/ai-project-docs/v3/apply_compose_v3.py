#!/usr/bin/env python3
"""Apply the Pass-4 compose worker's output back into the model (AI-docs v3).

Runs after the compose worker, before gate/render. Inputs:
  - compose-plan.json          : deterministic classification from compose_v3.py —
                                 the baseline category for every OQ + cross_doc
                                 resolver candidates.
  - <frag>/oq_resolutions.ndjson : LLM verdicts for the cross_doc + finding OQs.
  - <frag>/composed_views.ndjson : LLM cross-cutting views.

It folds the LLM verdicts onto the deterministic baseline and writes the validated
cross-cutting views to <model>/composed_views.ndjson, so render_v3.py can filter the
Open-questions section, split out a Discrepancies section, and render the views.

Final OQ category (deterministic baseline, overlaid by any LLM verdict):
  - open / coverage_gap : stays in the Open-questions section (status open).
  - finding             : moves to a Discrepancies section (out of Open questions).
  - resolved            : dropped from Open questions (status closed).
  - cross_doc_candidate : if the LLM did NOT rule on it, conservatively DEMOTE to
                          `open` — a candidate is not a resolution. The worker is
                          expected to rule on every one; an unruled candidate means
                          it was skipped, so keep the question visible rather than
                          silently hide it.

Evidence guard (same spirit as merge_fragments_v3.normalize_anchor): a composed view
may only cite anchors that already exist in anchors.ndjson, and evidence ids on a
resolution must resolve to a real claim/anchor. Hallucinated ids are dropped; a view
left with no real support is dropped entirely and reported. No new facts enter here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import modellib as ml

OPEN_CATEGORIES = {"open", "coverage_gap"}
VALID_LLM_VERDICTS = {"resolved", "finding", "open"}


def final_category(det_cat: str, llm_verdict: str | None) -> str:
    """Combine the deterministic baseline category with the LLM verdict (if any)."""
    if llm_verdict in VALID_LLM_VERDICTS:
        return llm_verdict  # resolved | finding | open
    # No LLM ruling. A cross_doc_candidate is only a *candidate* -> demote to open.
    if det_cat == "cross_doc_candidate":
        return "open"
    return det_cat  # open | coverage_gap | finding | resolved (deterministic)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--compose-plan", required=True, help="compose-plan.json from compose_v3.py")
    ap.add_argument("--frag-dir", required=True,
                    help="dir holding oq_resolutions.ndjson + composed_views.ndjson")
    args = ap.parse_args()

    model_dir = Path(args.model_dir).resolve()
    frag_dir = Path(args.frag_dir).resolve()
    plan = ml.load_json(Path(args.compose_plan).resolve(), default={}) or {}

    det = {v["id"]: v for v in plan.get("oq_verdicts", [])}
    resolutions = {r["id"]: r for r in ml.load_ndjson(frag_dir / "oq_resolutions.ndjson")}

    anchors = ml.load_ndjson(model_dir / "anchors.ndjson")
    anchor_ids = {a["id"] for a in anchors}
    claims = ml.load_ndjson(model_dir / "claims.ndjson")
    claim_ids = {c["id"] for c in claims}
    oqs = ml.load_ndjson(model_dir / "open_questions.ndjson")

    report: dict = {"oq_counts": {}, "warnings": [], "views_written": 0, "views_dropped": 0,
                    "resolutions_seen": len(resolutions)}

    # ---- OQ overlay (deterministic baseline + LLM verdict) ----
    for oq in oqs:
        oid = oq.get("id")
        det_cat = (det.get(oid) or {}).get("category", "open")
        res = resolutions.get(oid)
        llm_verdict = res.get("verdict") if res else None
        if res and llm_verdict not in VALID_LLM_VERDICTS:
            report["warnings"].append(f"oq {oid}: invalid LLM verdict {llm_verdict!r}, ignored")
            llm_verdict = None
        cat = final_category(det_cat, llm_verdict)
        oq["category"] = cat
        oq["status"] = "open" if cat in OPEN_CATEGORIES else "closed"
        if res:
            oq["compose_verdict"] = llm_verdict
            if res.get("reason"):
                oq["compose_reason"] = res["reason"]
            ev = [e for e in (res.get("evidence") or []) if e in claim_ids or e in anchor_ids]
            bad = [e for e in (res.get("evidence") or []) if e not in claim_ids and e not in anchor_ids]
            if bad:
                report["warnings"].append(f"oq {oid}: dropped {len(bad)} unresolvable evidence id(s)")
            if ev:
                oq["compose_evidence"] = ev
        elif (det.get(oid) or {}).get("resolvers"):
            oq["resolver_candidates"] = det[oid]["resolvers"][:8]
        report["oq_counts"][cat] = report["oq_counts"].get(cat, 0) + 1
    ml.write_ndjson(model_dir / "open_questions.ndjson", oqs)

    # resolutions referencing an OQ that isn't in the model (worker hallucinated an id)
    oq_ids = {o.get("id") for o in oqs}
    for rid in resolutions:
        if rid not in oq_ids:
            report["warnings"].append(f"resolution for unknown oq id {rid!r} ignored")

    # ---- composed views (evidence guard) ----
    views_out = []
    for v in ml.load_ndjson(frag_dir / "composed_views.ndjson"):
        vid = v.get("id") or f"view:{v.get('topic', '?')}"
        support = v.get("support") or []
        good = [s for s in support if s in anchor_ids]
        dropped = [s for s in support if s not in anchor_ids]
        if dropped:
            report["warnings"].append(f"view {vid}: dropped {len(dropped)} hallucinated anchor(s)")
        if not good:
            # empty support OR all-hallucinated: a view with no live anchor violates the
            # evidence invariant (same as a claim without support) -> drop it.
            report["warnings"].append(f"view {vid}: no valid support anchor -> view dropped")
            report["views_dropped"] += 1
            continue
        if not (v.get("body_md") or "").strip():
            report["warnings"].append(f"view {vid}: empty body_md -> dropped")
            report["views_dropped"] += 1
            continue
        v["support"] = good
        v["source_claims"] = [c for c in (v.get("source_claims") or []) if c in claim_ids]
        v.setdefault("origin", "llm")
        v.setdefault("doc", "architecture.md")
        views_out.append(v)
    ml.write_ndjson(model_dir / "composed_views.ndjson", views_out)
    report["views_written"] = len(views_out)

    report["oq_total"] = len(oqs)
    report["oq_section_after_compose"] = sum(
        n for c, n in report["oq_counts"].items() if c in OPEN_CATEGORIES)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
