#!/usr/bin/env python3
"""Create a compact authority-research run dashboard."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


STAGES = [
    "inventory",
    "profiles",
    "raw",
    "triaged",
    "rejected",
    "classified",
    "verified",
    "curation",
    "claim-ledger",
    "hallucination-audits",
    "topic-packs",
    "article-briefs",
    "synthesis",
    "dedup",
    "done",
    "logs",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build logs/run-dashboard.yaml for an authority-research run.")
    parser.add_argument("run_dir", type=Path)
    return parser.parse_args()


def load_yaml(path: Path) -> Any:
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def count_files(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    files = [p for p in path.rglob("*") if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


def done_status(run_dir: Path) -> dict[str, int]:
    counts = {"done": 0, "failed": 0, "other": 0}
    for path in sorted((run_dir / "done").glob("*.y*ml")) if (run_dir / "done").exists() else []:
        try:
            data = load_yaml(path) or {}
            status = str(data.get("status") or "other").strip().strip('"').strip("'").lower()
        except Exception:
            status = "other"
        if status in {"completed", "complete"}:
            status = "done"
        counts[status if status in counts else "other"] += 1
    return counts


def schedule_status(run_dir: Path) -> dict[str, int]:
    counts = {"pending": 0, "running": 0, "done": 0, "failed": 0, "skipped": 0, "other": 0}
    for path in sorted((run_dir / "schedule").glob("*.y*ml")) if (run_dir / "schedule").exists() else []:
        data = load_yaml(path)
        if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
            continue
        for task in data["tasks"]:
            status = str(task.get("status") or "other").strip().lower() if isinstance(task, dict) else "other"
            counts[status if status in counts else "other"] += 1
    return counts


def next_actions(validation: dict[str, Any] | None, public_gate: dict[str, Any] | None, synthesis: dict[str, Any] | None, schedules: dict[str, int], done: dict[str, int]) -> list[str]:
    actions: list[str] = []
    if validation:
        errors = int(validation.get("summary", {}).get("errors", 0))
        warnings = int(validation.get("summary", {}).get("warnings", 0))
        if errors:
            actions.append("Fix validation errors before downstream synthesis.")
        elif warnings:
            actions.append("Review validation warnings or run normalize_run.py before the next phase.")
    if schedules.get("failed"):
        actions.append("Inspect failed scheduled tasks and their done markers.")
    if done.get("failed"):
        actions.append("Inspect failed worker done markers.")
    if public_gate:
        invalid = int(public_gate.get("summary", {}).get("invalid_public_use", 0))
        if invalid:
            actions.append("Fix invalid public-use claims before briefing.")
    elif (Path.cwd()):  # deterministic no-op condition for style
        actions.append("Run make_public_material_gate.py after hallucination audits.")
    if synthesis:
        status = synthesis.get("summary", {}).get("status")
        if status == "fail":
            actions.append("Fix synthesis-quality failures before final report.")
        elif status == "warn":
            actions.append("Review synthesis-quality warnings before final report.")
    else:
        actions.append("Run make_synthesis_quality_report.py before final report.")
    if not actions:
        actions.append("Run is ready for final synthesis or publication review.")
    return actions


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    if not run_dir.exists():
        raise SystemExit(f"run directory not found: {run_dir}")
    stages: dict[str, dict[str, int]] = {}
    for stage in STAGES:
        count, size = count_files(run_dir / stage)
        stages[stage] = {"files": count, "bytes": size}
    validation = load_yaml(run_dir / "logs" / "validation-report.yaml")
    public_gate = load_yaml(run_dir / "logs" / "public-material-gate.yaml")
    synthesis = load_yaml(run_dir / "logs" / "synthesis-quality-report.yaml")
    done = done_status(run_dir)
    schedules = schedule_status(run_dir)
    dashboard = {
        "run_dir": str(run_dir),
        "stages": stages,
        "done_status": done,
        "schedule_status": schedules,
        "schedule_status_note": "Schedule task statuses may be stale; done/*.yaml is the source of truth for completion.",
        "validation": validation.get("summary") if isinstance(validation, dict) else None,
        "public_material_gate": public_gate.get("summary") if isinstance(public_gate, dict) else None,
        "synthesis_quality": synthesis.get("summary") if isinstance(synthesis, dict) else None,
        "next_actions": next_actions(validation if isinstance(validation, dict) else None, public_gate if isinstance(public_gate, dict) else None, synthesis if isinstance(synthesis, dict) else None, schedules, done),
    }
    out = run_dir / "logs" / "run-dashboard.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(dashboard, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(yaml.safe_dump({"dashboard_path": str(out), "done_status": done, "validation": dashboard["validation"], "public_material_gate": dashboard["public_material_gate"], "synthesis_quality": dashboard["synthesis_quality"], "next_actions": dashboard["next_actions"]}, allow_unicode=True, sort_keys=False, width=120).strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
