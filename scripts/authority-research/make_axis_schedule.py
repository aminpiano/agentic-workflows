#!/usr/bin/env python3
"""Create a simple authority-research work schedule from a domain map."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


PHASES = {
    "source-scout": "Find source lists and durable source families for this axis.",
    "site-profile": "Profile source sites for access method, value, trust, and collection strategy.",
    "collection": "Collect assigned material into raw, triaged, and rejected files.",
    "classification": "Classify collected material by topic, source type, trust, and usefulness.",
    "source-verification": "Verify source existence and metadata.",
    "fact-verification": "Verify factual claims against sources.",
}

PRIORITY = {"critical": 100, "high": 80, "medium": 50, "low": 20}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create work-schedule.yaml from domain-map.yaml.")
    parser.add_argument("--domain-map", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--phase", choices=sorted(PHASES), default="source-scout")
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args()


def load_minimal_yaml(path: Path) -> dict[str, Any]:
    """Parse the small domain-map template without requiring PyYAML."""
    text = path.read_text(encoding="utf-8")
    axes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_list: str | None = None

    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.match(r"\s*-\s+id:", line):
            current = {"id": stripped.split(":", 1)[1].strip().strip('"')}
            axes.append(current)
            current_list = None
            continue
        if current is None:
            continue
        key_match = re.match(r"\s{4}([a-zA-Z0-9_-]+):\s*(.*)$", line)
        if key_match:
            key, value = key_match.groups()
            value = value.strip()
            if value:
                current[key] = value.strip('"')
                current_list = None
            else:
                current[key] = []
                current_list = key
            continue
        item_match = re.match(r"\s{6}-\s*(.*)$", line)
        if item_match and current_list:
            current[current_list].append(item_match.group(1).strip().strip('"'))

    return {"axes": axes}


def priority_value(axis: dict[str, Any]) -> int:
    return PRIORITY.get(str(axis.get("priority", "medium")).lower(), 50)


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    data = load_minimal_yaml(args.domain_map.expanduser().resolve())
    axes = sorted(data.get("axes", []), key=priority_value, reverse=True)
    if not axes:
        raise SystemExit("domain map has no axes")

    tasks = []
    for index, axis in enumerate(axes, start=1):
        task_id = f"{index:03d}"
        tasks.append(
            {
                "task_id": task_id,
                "phase": args.phase,
                "axis_id": axis.get("id"),
                "axis_label": axis.get("label", axis.get("id")),
                "priority": axis.get("priority", "medium"),
                "instruction": PHASES[args.phase],
                "questions": axis.get("questions", []),
                "source_families": axis.get("source_families", []),
                "expected_done_marker": f"done/{task_id}.yaml",
            }
        )

    schedule = {
        "version": "authority_research_schedule_v0_1",
        "phase": args.phase,
        "run_dir": str(run_dir),
        "tasks": tasks,
    }
    out = args.out or run_dir / "schedule" / f"{args.phase}-schedule.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schedule, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"schedule": str(out), "tasks": len(tasks)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
