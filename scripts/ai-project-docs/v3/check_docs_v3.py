#!/usr/bin/env python3
"""AI-docs v3 three-layer drift check (decision 5 + 6).

The model is the source of truth. Code change -> update model -> re-render.

Layer 1 (repo -> model): per anchor in anchors.ndjson, compare stored file_sha256
  to the current file. clean / soft (anchor_text survives) / hard (anchor_text gone
  or file missing). Inference/diagram claims also go soft when any dep_files changed,
  even if their anchors survive (the Silent-Drift guard).
Layer 2 (model -> markdown): per doc in render_state.json, compare the model_inputs
  hashes it was rendered from to the current model hashes -> view_stale.
Layer 3 (markdown quality): each rendered doc must still pass the catalog gate.

v3 does NOT prove a claim is true. It reports which support is alive and which
claims/slots are due for re-synthesis.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import modellib as ml
import gate_v3


def check_anchor(root: Path, anchor: dict, file_sha_cache: dict) -> str:
    if anchor.get("policy") == "none":
        return "skipped"
    rel = anchor.get("path")
    if not rel:
        return "unverified"
    p = root / rel
    if not p.exists():
        return "hard"
    cur = file_sha_cache.get(rel)
    if cur is None:
        cur = ml.sha256_file(p)
        file_sha_cache[rel] = cur
    if cur == anchor.get("file_sha256"):
        return "clean"
    # file changed: does the exact anchor_text survive?
    text = anchor.get("anchor_text") or ""
    try:
        body = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "hard"
    return "soft" if text and text in body else "hard"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", nargs="?", default=".")
    parser.add_argument("--model-dir", default="ai-docs/.model")
    parser.add_argument("--docs-dir", default="ai-docs")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    model_dir = (root / args.model_dir) if not Path(args.model_dir).is_absolute() else Path(args.model_dir)
    model_dir = model_dir.resolve()
    if not (model_dir / "anchors.ndjson").exists():
        msg = {"status": "missing_model", "model_dir": str(model_dir)}
        print(json.dumps(msg, indent=2) if args.json else f"Missing model: {model_dir}")
        return 2

    anchors = ml.load_ndjson(model_dir / "anchors.ndjson")
    claims = ml.load_ndjson(model_dir / "claims.ndjson")

    # ---- Layer 1 ----
    file_sha_cache: dict[str, str] = {}
    anchor_status: dict[str, str] = {}
    l1 = {"clean": 0, "soft": 0, "hard": 0, "skipped": 0, "unverified": 0}
    changed_files: set[str] = set()
    hard_anchor_paths: set[str] = set()
    for a in anchors:
        st = check_anchor(root, a, file_sha_cache)
        anchor_status[a["id"]] = st
        l1[st] = l1.get(st, 0) + 1
        if st in ("soft", "hard"):
            changed_files.add(a.get("path"))
        if st == "hard":
            hard_anchor_paths.add(a.get("path"))

    # claim-level drift
    claim_drift = {"clean": 0, "soft_review": 0, "hard_resynth": 0}
    requeue_slots: set[str] = set()
    claim_details = []
    for c in claims:
        sup_status = [anchor_status.get(s, "unverified") for s in c.get("support", [])]
        cls = c.get("class")
        if "hard" in sup_status:
            verdict = "hard_resynth"
            requeue_slots.add(c.get("doc"))
        elif cls in ("inference", "diagram") and (set(c.get("dep_files", [])) & changed_files):
            verdict = "soft_review"
        elif "soft" in sup_status:
            verdict = "soft_review"
        else:
            verdict = "clean"
        claim_drift[verdict] = claim_drift.get(verdict, 0) + 1
        if verdict != "clean":
            claim_details.append({"claim": c.get("id"), "doc": c.get("doc"), "verdict": verdict, "class": cls})

    # ---- Layer 2 ----
    render_state = ml.load_json(model_dir / "render_state.json", default={}) or {}
    cur_hashes = {
        "claims_sha256": ml.sha256_file(model_dir / "claims.ndjson") if (model_dir / "claims.ndjson").exists() else None,
        "entities_sha256": ml.sha256_file(model_dir / "entities.ndjson") if (model_dir / "entities.ndjson").exists() else None,
        "edges_sha256": ml.sha256_file(model_dir / "edges.ndjson") if (model_dir / "edges.ndjson").exists() else None,
        "flows_sha256": ml.sha256_file(model_dir / "flows.json") if (model_dir / "flows.json").exists() else None,
    }
    view_stale = []
    for d in render_state.get("docs", []):
        mi = d.get("model_inputs", {})
        stale_keys = [k for k, v in cur_hashes.items() if mi.get(k) != v]
        if stale_keys:
            view_stale.append({"doc": d["doc"], "stale_inputs": stale_keys})

    # ---- Layer 3 ----
    docs_dir = (root / args.docs_dir) if not Path(args.docs_dir).is_absolute() else Path(args.docs_dir)
    docs_dir = docs_dir.resolve()
    gate_findings = []
    if docs_dir.exists():
        gate_findings = [f for f in gate_v3.lint_docs(docs_dir, model_dir) if f["severity"] == "fail"]

    status = "pass"
    if l1["hard"] or claim_drift["hard_resynth"] or gate_findings:
        status = "fail"
    elif l1["soft"] or claim_drift["soft_review"] or view_stale:
        status = "warn"

    report = {
        "status": status,
        "layer1_repo_to_model": l1,
        "layer1_claim_drift": claim_drift,
        "layer1_changed_files": sorted(changed_files),
        "layer2_view_stale": view_stale,
        "layer3_gate_fail": gate_findings,
        "requeue_slots": sorted(s for s in requeue_slots if s),
        "claim_details": claim_details,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"ai-docs v3 drift: {status}")
        print(f"  L1 anchors: {l1}")
        print(f"  L1 claims:  {claim_drift}")
        print(f"  L2 stale views: {len(view_stale)}")
        print(f"  L3 gate fails:  {len(gate_findings)}")
        if report["requeue_slots"]:
            print(f"  re-synth slots: {report['requeue_slots']}")
    return 1 if status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
