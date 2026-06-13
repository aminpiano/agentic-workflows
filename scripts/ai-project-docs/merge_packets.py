#!/usr/bin/env python3
"""Merge AI-docs v2 worker packets into synthesis artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_schedule(run_dir: Path) -> dict:
    return load_json(run_dir / "planning" / "schedule.json")


def load_slots(run_dir: Path) -> dict:
    return load_json(run_dir / "planning" / "doc-slots.json")


def validate_packet(packet: dict, path: Path, known_slots: set[str]) -> list[str]:
    errors: list[str] = []
    task_id = packet.get("task_id")
    if not task_id:
        errors.append(f"{path.name}: missing task_id")
    if packet.get("status") != "done":
        errors.append(f"{path.name}: status must be done")
    findings = packet.get("findings")
    if not isinstance(findings, list):
        errors.append(f"{path.name}: findings must be a list")
        return errors
    for idx, finding in enumerate(findings):
        prefix = f"{path.name}: findings[{idx}]"
        slot_id = finding.get("slot_id")
        if slot_id not in known_slots:
            errors.append(f"{prefix}: unknown slot_id {slot_id!r}")
        if not finding.get("claim"):
            errors.append(f"{prefix}: missing claim")
        evidence = finding.get("evidence", [])
        if not isinstance(evidence, list):
            errors.append(f"{prefix}: evidence must be a list")
            continue
        for ev_idx, item in enumerate(evidence):
            ev_prefix = f"{prefix}.evidence[{ev_idx}]"
            if not item.get("path"):
                errors.append(f"{ev_prefix}: missing path")
            if item.get("policy", "tracked") != "none" and not item.get("file_sha256"):
                errors.append(f"{ev_prefix}: missing file_sha256")
            if item.get("policy", "tracked") != "none" and not item.get("anchor"):
                errors.append(f"{ev_prefix}: missing anchor")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    parser.add_argument("--allow-missing", action="store_true", help="Warn instead of fail when scheduled packets are missing")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    synthesis_dir = run_dir / "synthesis"
    logs_dir = run_dir / "logs"
    synthesis_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    schedule = load_schedule(run_dir)
    slots = load_slots(run_dir)
    known_slots = {slot["slot_id"] for slot in slots.get("slots", [])}
    expected = {task["task_id"]: task for task in schedule.get("tasks", [])}

    packets = []
    errors: list[str] = []
    for path in sorted((run_dir / "packets").glob("*.packet.json")):
        packet = load_json(path)
        packet["_path"] = str(path)
        errors.extend(validate_packet(packet, path, known_slots))
        packets.append(packet)

    seen = {packet.get("task_id") for packet in packets}
    missing = sorted(task_id for task_id in expected if task_id not in seen)
    if missing and not args.allow_missing:
        errors.extend(f"missing packet for scheduled task {task_id}" for task_id in missing)

    findings_by_slot: dict[str, list[dict]] = {slot_id: [] for slot_id in known_slots}
    open_questions: list[dict] = []
    for packet in packets:
        task_id = packet.get("task_id")
        for finding in packet.get("findings", []):
            slot_id = finding.get("slot_id")
            if slot_id in findings_by_slot:
                findings_by_slot[slot_id].append({"task_id": task_id, **finding})
        for question in packet.get("open_questions", []):
            open_questions.append({"task_id": task_id, "question": question})

    merged = {
        "version": 2,
        "kind": "ai-docs-v2-merged-packets",
        "run_dir": str(run_dir),
        "packet_count": len(packets),
        "missing_packets": missing,
        "errors": errors,
        "findings_by_slot": findings_by_slot,
        "open_questions": open_questions,
    }
    report = {
        "status": "fail" if errors else ("warn" if missing else "pass"),
        "packet_count": len(packets),
        "scheduled_tasks": len(expected),
        "missing_packets": missing,
        "error_count": len(errors),
        "errors": errors,
    }
    (synthesis_dir / "merged-packets.json").write_text(
        json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (logs_dir / "packet-merge-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
