#!/usr/bin/env python3
"""Check AI-docs v2 evidence records for repo drift."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect_evidence(state: dict) -> list[dict]:
    if isinstance(state.get("evidence"), list):
        return state["evidence"]
    evidence: list[dict] = []
    for doc, payload in state.get("documents", {}).items():
        for item in payload.get("evidence", []):
            evidence.append({"doc": doc, **item})
    return evidence


def check_record(root: Path, record: dict) -> dict:
    policy = record.get("policy", "tracked")
    rel_path = record.get("path")
    result = {"record": record, "status": "clean", "message": ""}
    if policy == "none":
        result["status"] = "skipped"
        return result
    if not rel_path:
        result.update(status="unverified", message="missing path")
        return result
    path = root / rel_path
    if not path.exists():
        result.update(status="hard_drift", message="file missing")
        return result
    actual_hash = sha256(path)
    expected_hash = record.get("file_sha256") or record.get("sha256")
    anchor = record.get("anchor")
    if expected_hash and actual_hash == expected_hash:
        return result
    if not anchor:
        result.update(status="unverified", message="hash changed and no anchor recorded")
        return result
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        result.update(status="hard_drift", message=f"cannot read file: {exc.__class__.__name__}")
        return result
    if anchor in text:
        result.update(status="soft_drift", message="file hash changed but anchor still exists")
    else:
        result.update(status="hard_drift", message="file hash changed and anchor is missing")
    return result


def summarize(results: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    if counts.get("hard_drift"):
        status = "fail"
    elif counts.get("unverified") or counts.get("soft_drift"):
        status = "warn"
    else:
        status = "pass"
    return {"status": status, "counts": counts, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", nargs="?", default=".")
    parser.add_argument("--state", default="ai-docs/ai-docs-state.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    state_path = (root / args.state).resolve() if not Path(args.state).is_absolute() else Path(args.state)
    if not state_path.exists():
        payload = {"status": "missing_state", "state": str(state_path)}
        print(json.dumps(payload, indent=2) if args.json else f"Missing state file: {state_path}")
        return 2
    state = json.loads(state_path.read_text(encoding="utf-8"))
    evidence = collect_evidence(state)
    results = [check_record(root, record) for record in evidence]
    summary = summarize(results)
    summary["state"] = str(state_path)
    summary["evidence_count"] = len(evidence)
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"AI-docs check: {summary['status']} ({len(evidence)} evidence records)")
        for key, value in sorted(summary["counts"].items()):
            print(f"- {key}: {value}")
        for result in results:
            if result["status"] != "clean":
                record = result["record"]
                print(f"- {result['status']}: {record.get('path')} :: {result['message']}")
    return 1 if summary["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
