#!/usr/bin/env python3
"""Create an authority-research work schedule from a domain-map YAML file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


PHASES = {
    "source-scout": {
        "expected_outputs": ["inventory", "done"],
        "verb": "Find source lists and durable source families for this axis.",
    },
    "site-profile": {
        "expected_outputs": ["profiles", "done"],
        "verb": "Profile known source sites for access method, rough item count, parsing feasibility, and collection strategy.",
    },
    "collection": {
        "expected_outputs": ["raw", "triaged", "rejected", "done"],
        "verb": "Collect assigned materials into raw, triaged, and rejected files.",
    },
    "classification": {
        "expected_outputs": ["classified", "done"],
        "verb": "Classify collected materials by topic, source type, trust grade, and usefulness.",
    },
    "source-verification": {
        "expected_outputs": ["verified", "done"],
        "verb": "Verify source existence and metadata correctness.",
    },
    "fact-verification": {
        "expected_outputs": ["verified", "done"],
        "verb": "Verify extracted factual claims against sources.",
    },
    "drafting": {
        "expected_outputs": ["drafted", "done"],
        "verb": "Draft article material from verified or explicitly approved sources only.",
    },
}


PRIORITY = {"critical": 100, "high": 80, "medium": 50, "low": 20}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create work-schedule.yaml from domain-map.yaml.")
    parser.add_argument("--domain-map", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--phase", choices=sorted(PHASES), default="source-scout")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--codex-start", type=int, default=1)
    parser.add_argument("--agy-start", type=int, default=999)
    return parser.parse_args()


def priority_value(value: Any) -> int:
    if isinstance(value, int):
        return value
    return PRIORITY.get(str(value or "medium").lower(), 50)


def ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def task_instruction(axis: dict[str, Any], phase: str, defaults: dict[str, Any]) -> str:
    phase_info = PHASES[phase]
    lines = [
        phase_info["verb"],
        "",
        f"Axis id: {axis.get('id')}",
        f"Axis label: {axis.get('label') or axis.get('id')}",
        f"Scope: {axis.get('scope') or 'UNKNOWN'}",
    ]
    terms = ensure_list(axis.get("search_terms"))
    if terms:
        lines.extend(["", "Search terms:"])
        lines.extend(f"- {term}" for term in terms)
    source_types = ensure_list(axis.get("source_types")) or ensure_list(defaults.get("source_types"))
    if source_types:
        lines.extend(["", "Desired source types:"])
        lines.extend(f"- {source_type}" for source_type in source_types)
    seed_sources = ensure_list(axis.get("seed_sources"))
    if seed_sources:
        lines.extend(["", "Seed sources:"])
        lines.extend(f"- {source}" for source in seed_sources)
    notes = ensure_list(axis.get("notes"))
    if notes:
        lines.extend(["", "Notes and cautions:"])
        lines.extend(f"- {note}" for note in notes)
    lines.extend(
        [
            "",
            "Worker requirements:",
            "- Write files under the assigned run folder only.",
            "- Write done/<task_id>.yaml.",
            "- Use UNKNOWN for unsupported or missing facts.",
            "- Final chat response should contain only task id, status, and done marker path.",
        ]
    )
    return "\n".join(lines)


def make_schedule(domain_map: dict[str, Any], run_dir: Path, phase: str, codex_start: int, agy_start: int) -> dict[str, Any]:
    defaults = domain_map.get("defaults", {}) or {}
    axes = list(domain_map.get("axes", []) or [])
    axes.sort(key=lambda item: (-priority_value(item.get("priority")), str(item.get("id") or "")))

    codex_id = codex_start
    agy_id = agy_start
    tasks = []
    for axis in axes:
        worker = str(axis.get("preferred_worker") or defaults.get("preferred_worker") or "codex").lower()
        if worker not in {"codex", "agy", "either"}:
            worker = "codex"
        if worker == "either":
            worker = "codex"
        if worker == "agy":
            task_id = f"{agy_id:03d}"
            agy_id -= 1
        else:
            task_id = f"{codex_id:03d}"
            codex_id += 1
        tasks.append(
            {
                "task_id": task_id,
                "axis_id": axis.get("id"),
                "axis_label": axis.get("label") or axis.get("id"),
                "status": "pending",
                "worker": worker,
                "priority": priority_value(axis.get("priority")),
                "title": f"{PHASES[phase]['verb']} [{axis.get('label') or axis.get('id')}]",
                "instruction": task_instruction(axis, phase, defaults),
                "expected_outputs": list(PHASES[phase]["expected_outputs"]),
            }
        )

    tasks.sort(key=lambda item: int(item["task_id"]))
    return {
        "version": "authority_research_schedule_v0_1",
        "source": "domain-map",
        "domain": domain_map.get("domain"),
        "title": domain_map.get("title"),
        "phase": phase,
        "run_dir": str(run_dir),
        "assignment_policy": {
            "codex_direction": "ascending",
            "agy_direction": "descending",
            "codex_batch_size": 5,
            "agy_concurrency": 1,
        },
        "tasks": tasks,
    }


def main() -> int:
    args = parse_args()
    domain_map_path = args.domain_map.expanduser().resolve()
    run_dir = args.run_dir.expanduser().resolve()
    with domain_map_path.open("r", encoding="utf-8") as f:
        domain_map = yaml.safe_load(f) or {}
    schedule = make_schedule(domain_map, run_dir, args.phase, args.codex_start, args.agy_start)
    out = args.out.expanduser().resolve() if args.out else run_dir / "schedule" / f"{args.phase}-schedule.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(schedule, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    counts = {}
    for task in schedule["tasks"]:
        counts[task["worker"]] = counts.get(task["worker"], 0) + 1
    print(json.dumps({"schedule_path": str(out), "tasks": len(schedule["tasks"]), "by_worker": counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
