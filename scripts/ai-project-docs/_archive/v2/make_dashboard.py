#!/usr/bin/env python3
"""Create a compact AI-docs v2 run dashboard."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def simple_yaml(value: object, indent: int = 0) -> str:
    pad = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.append(simple_yaml(item, indent + 2).rstrip())
            else:
                lines.append(f"{pad}{key}: {json.dumps(item, ensure_ascii=False)}")
        return "\n".join(lines) + "\n"
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}-")
                lines.append(simple_yaml(item, indent + 2).rstrip())
            else:
                lines.append(f"{pad}- {json.dumps(item, ensure_ascii=False)}")
        return "\n".join(lines) + "\n"
    return f"{pad}{json.dumps(value, ensure_ascii=False)}\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    parser.add_argument("--project-root", default=None)
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    project_root = Path(args.project_root).resolve() if args.project_root else None
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    index = load_json(run_dir / "source-index" / "index-final.json") or {}
    ops_inventory = load_json(run_dir / "ops-inventory" / "ops-inventory.json") or {}
    schedule = load_json(run_dir / "planning" / "schedule.json") or {}
    slots = load_json(run_dir / "planning" / "doc-slots.json") or {}
    deferred = load_json(run_dir / "planning" / "deferred-sources.json") or {}
    merge_report = load_json(run_dir / "logs" / "packet-merge-report.json") or {}
    state = load_json(run_dir / "synthesis" / "docs" / "ai-docs-state.json") or {}
    applied_state = {}
    if project_root:
        applied_state = load_json(project_root / "ai-docs" / "ai-docs-state.json") or {}

    packet_count = len(list((run_dir / "packets").glob("*.packet.json")))
    done_count = len(list((run_dir / "done").glob("*.done.json")))
    staged_docs = [
        str(path.relative_to(run_dir / "synthesis" / "docs"))
        for path in sorted((run_dir / "synthesis" / "docs").rglob("*.md"))
    ] if (run_dir / "synthesis" / "docs").exists() else []

    status = "pass"
    next_actions: list[str] = []
    if not index:
        status = "incomplete"
        next_actions.append("Run repo_index.py.")
    if not schedule:
        status = "incomplete"
        next_actions.append("Run make_v2_schedule.py.")
    if not ops_inventory:
        next_actions.append("Run ops_inventory.py if production/ops facts matter for this project.")
    if schedule and packet_count < schedule.get("task_count", 0):
        status = "incomplete"
        next_actions.append("Complete missing worker packets or run merge_packets.py with --allow-missing for a partial test.")
    if schedule.get("task_count", 0) > 48:
        status = "warn" if status == "pass" else status
        next_actions.append("Review schedule size; consider repo_index.py --profile code-first, .ai-docsignore, or lower slot task limits.")
    if merge_report.get("status") == "fail":
        status = "fail"
        next_actions.append("Fix packet merge errors before synthesis.")
    if packet_count and not staged_docs:
        status = "incomplete"
        next_actions.append("Run synthesize_docs.py.")
    applied = bool(applied_state) and applied_state.get("run_dir") == str(run_dir)
    if staged_docs and not state:
        status = "warn"
        next_actions.append("Check why staged docs lack ai-docs-state.json.")
    if not next_actions and applied:
        next_actions.append("Run check_docs.py to verify applied evidence state.")
    elif not next_actions:
        next_actions.append("Review staged docs, then run synthesize_docs.py --apply if acceptable.")

    files = index.get("files", {})
    top_dirs = Counter(path.split("/", 1)[0] for path in files)
    deferred_reasons = Counter(item.get("reason", "unknown") for item in deferred.get("sources", []))
    ignored_reasons = Counter(item.get("ignore_reason", "unknown") for item in index.get("ignored", []))
    noisy_dirs = [
        {"path": path, "indexed_files": count}
        for path, count in top_dirs.most_common(10)
        if count >= 25
    ]
    warnings = []
    if schedule.get("task_count", 0) > 48:
        warnings.append(
            {
                "kind": "task_explosion",
                "message": "Source-scout schedule is large for a default run.",
                "tasks": schedule.get("task_count", 0),
            }
        )
    if noisy_dirs:
        warnings.append(
            {
                "kind": "high_noise_dirs",
                "message": "Large indexed directories may need profile tuning or .ai-docsignore.",
                "dirs": noisy_dirs[:5],
            }
        )

    dashboard = {
        "status": status,
        "run_dir": str(run_dir),
        "source_index": {
            "present": bool(index),
            "stats": index.get("stats", {}),
            "profile": index.get("profile"),
            "ignored_reasons": dict(ignored_reasons.most_common(12)),
            "top_dirs": [{"path": path, "indexed_files": count} for path, count in top_dirs.most_common(12)],
        },
        "planning": {
            "slots": len(slots.get("slots", [])),
            "tasks": schedule.get("task_count", 0),
            "profile": schedule.get("profile"),
            "deferred_sources": len(deferred.get("sources", [])),
            "deferred_reasons": dict(deferred_reasons.most_common(12)),
        },
        "ops_inventory": {
            "present": bool(ops_inventory),
            "mode": ops_inventory.get("mode"),
            "repo_ops_files": len(ops_inventory.get("repo_ops_files", [])),
            "host_readonly": bool(ops_inventory.get("host_readonly")),
        },
        "execution": {
            "packets": packet_count,
            "done_markers": done_count,
            "merge_status": merge_report.get("status"),
            "missing_packets": merge_report.get("missing_packets", []),
        },
        "synthesis": {
            "staged_docs": staged_docs,
            "evidence_records": len(state.get("evidence", [])),
            "applied": applied,
        },
        "warnings": warnings,
        "next_actions": next_actions,
    }
    (logs_dir / "dashboard.json").write_text(
        json.dumps(dashboard, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (logs_dir / "dashboard.yaml").write_text(simple_yaml(dashboard), encoding="utf-8")
    print(json.dumps(dashboard, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
