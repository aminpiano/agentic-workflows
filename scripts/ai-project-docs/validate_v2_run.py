#!/usr/bin/env python3
"""Validate AI-docs v2 run artifacts without reading source files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    index_path = run_dir / "source-index" / "index-final.json"
    schedule_path = run_dir / "planning" / "schedule.json"
    slots_path = run_dir / "planning" / "doc-slots.json"
    for path in [index_path, schedule_path, slots_path]:
        if not path.exists():
            errors.append(f"missing {path.relative_to(run_dir)}")
    if errors:
        payload = {"status": "fail", "errors": errors, "warnings": warnings}
        print(json.dumps(payload, indent=2) if args.json else payload)
        return 1

    index = json.loads(index_path.read_text(encoding="utf-8"))
    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    slots = json.loads(slots_path.read_text(encoding="utf-8"))
    known_files = set(index.get("files", {}).keys())
    known_slots = {slot["slot_id"] for slot in slots.get("slots", [])}
    seen_tasks: set[str] = set()
    for task in schedule.get("tasks", []):
        task_id = task.get("task_id")
        if not task_id:
            errors.append("task without task_id")
            continue
        if task_id in seen_tasks:
            errors.append(f"duplicate task_id {task_id}")
        seen_tasks.add(task_id)
        for slot_id in task.get("target_slots", []):
            if slot_id not in known_slots:
                errors.append(f"{task_id}: unknown slot {slot_id}")
        if not task.get("source_ranges"):
            warnings.append(f"{task_id}: no source ranges")
        for source in task.get("source_ranges", []):
            if source.get("path") not in known_files:
                errors.append(f"{task_id}: source not in index {source.get('path')}")

    packet_dir = run_dir / "packets"
    done_dir = run_dir / "done"
    packet_count = len(list(packet_dir.glob("*.packet.json"))) if packet_dir.exists() else 0
    done_count = len(list(done_dir.glob("*.done.json"))) if done_dir.exists() else 0
    payload = {
        "status": "fail" if errors else "pass",
        "errors": errors,
        "warnings": warnings,
        "tasks": len(schedule.get("tasks", [])),
        "slots": len(known_slots),
        "packets": packet_count,
        "done_markers": done_count,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json else payload)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
