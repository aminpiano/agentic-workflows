#!/usr/bin/env python3
"""Create a compact authority-research run dashboard."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from _contract import is_schedule_doc, next_action, normalize_status


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


def load_yaml(path: Path, broken: list[Path] | None = None) -> Any:
    """Parse a YAML file, recording rather than raising on malformed input.

    The dashboard is what you consult when a run looks wrong, so a single
    unparsable artifact must not take the whole report down with it — that is
    exactly the moment the status is needed. Broken files are collected and
    surfaced as a next-action instead.
    """
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, UnicodeDecodeError, OSError):
        if broken is not None:
            broken.append(path)
        return None


def count_files(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    files = [p for p in path.rglob("*") if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


def done_status(run_dir: Path, broken: list[Path] | None = None) -> dict[str, int]:
    counts = {"done": 0, "failed": 0, "other": 0}
    for path in sorted((run_dir / "done").glob("*.y*ml")) if (run_dir / "done").exists() else []:
        data = load_yaml(path, broken) or {}
        status = str(data.get("status") or "other").strip().strip('"').strip("'").lower() if isinstance(data, dict) else "other"
        status = normalize_status(status)
        counts[status if status in counts else "other"] += 1
    return counts


def schedule_status(run_dir: Path, broken: list[Path] | None = None) -> dict[str, int]:
    counts = {"pending": 0, "running": 0, "done": 0, "failed": 0, "skipped": 0, "other": 0}
    for path in sorted((run_dir / "schedule").glob("*.y*ml")) if (run_dir / "schedule").exists() else []:
        data = load_yaml(path, broken)
        if not is_schedule_doc(data):
            continue
        for task in data["tasks"]:
            status = str(task.get("status") or "other").strip().lower() if isinstance(task, dict) else "other"
            counts[status if status in counts else "other"] += 1
    return counts


def next_actions(
    validation: dict[str, Any] | None,
    public_gate: dict[str, Any] | None,
    synthesis: dict[str, Any] | None,
    schedules: dict[str, int],
    done: dict[str, int],
    broken: list[Path] | None = None,
) -> list[dict[str, Any]]:
    """Compute the run's next actions as structured records.

    Emits data, not prose. Each record carries a machine-stable `action` and
    `reason` so an executor can branch on it without parsing English, a
    `blocking` flag marking the gates that must clear before downstream
    synthesis, and a `detail` sentence for whoever reads the YAML directly.

    Purely derived from file counts and report summaries — this function never
    reads research material or judges quality.
    """
    actions: list[dict[str, Any]] = []

    if broken:
        actions.append(next_action(
            "inspect", "unparsable_files",
            f"{len(broken)} artifact(s) could not be parsed; every count below excludes them.",
            target="run", count=len(broken),
            files=[p.name for p in broken[:10]],
        ))

    if validation:
        summary = validation.get("summary") or {}
        errors = int(summary.get("errors") or 0)
        warnings = int(summary.get("warnings") or 0)
        if errors:
            actions.append(next_action(
                "halt", "validation_errors",
                f"Fix {errors} validation error(s) before downstream synthesis.",
                blocking=True, count=errors,
            ))
        elif warnings:
            actions.append(next_action(
                "run_script", "validation_warnings",
                f"Review {warnings} validation warning(s); run normalize_run.py if they are enum drift.",
                script="normalize_run.py", args=["--write"], count=warnings,
            ))

    unfinished = int(schedules.get("pending") or 0) + int(schedules.get("running") or 0)
    if unfinished:
        actions.append(next_action(
            "spawn_workers", "schedule_tasks_pending",
            f"{unfinished} scheduled task(s) unfinished; assign workers from the schedule.",
            count=unfinished,
        ))
    if schedules.get("failed"):
        actions.append(next_action(
            "inspect", "schedule_tasks_failed",
            f"Inspect {schedules['failed']} failed scheduled task(s) and their done markers.",
            target="schedule", count=int(schedules["failed"]),
        ))
    if done.get("failed"):
        actions.append(next_action(
            "inspect", "done_markers_failed",
            f"Inspect {done['failed']} failed worker done marker(s).",
            target="done", count=int(done["failed"]),
        ))

    if public_gate:
        invalid = int((public_gate.get("summary") or {}).get("invalid_public_use") or 0)
        if invalid:
            actions.append(next_action(
                "halt", "public_gate_invalid",
                f"Fix {invalid} invalid public-use claim(s) before briefing.",
                blocking=True, count=invalid,
            ))
    else:
        actions.append(next_action(
            "run_script", "public_gate_missing",
            "Run make_public_material_gate.py after hallucination audits.",
            script="make_public_material_gate.py",
        ))

    if synthesis:
        status = (synthesis.get("summary") or {}).get("status")
        if status == "fail":
            actions.append(next_action(
                "halt", "synthesis_failed",
                "Fix synthesis-quality failures before the final report.",
                blocking=True,
            ))
        elif status == "warn":
            actions.append(next_action(
                "inspect", "synthesis_warnings",
                "Review synthesis-quality warnings before the final report.",
                target="logs/synthesis-quality-report.yaml",
            ))
    else:
        actions.append(next_action(
            "run_script", "synthesis_report_missing",
            "Run make_synthesis_quality_report.py before the final report.",
            script="make_synthesis_quality_report.py",
        ))

    if not actions:
        actions.append(next_action(
            "ready", "all_gates_passed",
            "Run is ready for final synthesis or publication review.",
        ))
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
    broken: list[Path] = []
    validation = load_yaml(run_dir / "logs" / "validation-report.yaml", broken)
    public_gate = load_yaml(run_dir / "logs" / "public-material-gate.yaml", broken)
    synthesis = load_yaml(run_dir / "logs" / "synthesis-quality-report.yaml", broken)
    done = done_status(run_dir, broken)
    schedules = schedule_status(run_dir, broken)
    actions = next_actions(
        validation if isinstance(validation, dict) else None,
        public_gate if isinstance(public_gate, dict) else None,
        synthesis if isinstance(synthesis, dict) else None,
        schedules,
        done,
        broken,
    )
    dashboard = {
        "run_dir": str(run_dir),
        "stages": stages,
        "done_status": done,
        "schedule_status": schedules,
        "schedule_status_note": "Schedule task statuses may be stale; done/*.yaml is the source of truth for completion.",
        "validation": validation.get("summary") if isinstance(validation, dict) else None,
        "public_material_gate": public_gate.get("summary") if isinstance(public_gate, dict) else None,
        "synthesis_quality": synthesis.get("summary") if isinstance(synthesis, dict) else None,
        # One field an executor can branch on before reading anything else.
        "blocked": any(a["blocking"] for a in actions),
        "next_actions": actions,
    }
    out = run_dir / "logs" / "run-dashboard.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(dashboard, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(yaml.safe_dump({"dashboard_path": str(out), "done_status": done, "validation": dashboard["validation"], "public_material_gate": dashboard["public_material_gate"], "synthesis_quality": dashboard["synthesis_quality"], "blocked": dashboard["blocked"], "next_actions": dashboard["next_actions"]}, allow_unicode=True, sort_keys=False, width=120).strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
