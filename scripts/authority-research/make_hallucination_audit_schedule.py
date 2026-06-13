#!/usr/bin/env python3
"""Create hallucination-audit tasks from curation outputs without reading source contents."""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path


CURATION_RE = re.compile(r"^ec(?P<suffix>[0-9]{3})-curation\.ya?ml$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a hallucination audit schedule.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--phase", default="hallucination-audit")
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args()


def worker_for_suffix(suffix: str) -> str:
    try:
        number = int(suffix)
    except ValueError:
        return "codex"
    return "agy" if number >= 900 else "codex"


def q(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def ensure_dirs(run_dir: Path) -> None:
    for name in [
        "claim-ledger",
        "hallucination-audits",
        "topic-packs",
        "article-briefs",
        "schedule",
        "done",
        "logs",
        "prompts",
    ]:
        (run_dir / name).mkdir(parents=True, exist_ok=True)


def discover_tasks(run_dir: Path) -> list[dict[str, str]]:
    curation_dir = run_dir / "curation"
    if not curation_dir.exists():
        raise SystemExit(f"curation directory not found: {curation_dir}")

    tasks: list[dict[str, str]] = []
    for path in sorted(curation_dir.iterdir()):
        if not path.is_file():
            continue
        match = CURATION_RE.match(path.name)
        if not match:
            continue
        suffix = match.group("suffix")
        classified_path = run_dir / "classified" / f"cl{suffix}-classification.yaml"
        verified_path = run_dir / "verified" / f"sv{suffix}-source-verification.yaml"
        tasks.append(
            {
                "suffix": suffix,
                "task_id": f"ha{suffix}",
                "worker": worker_for_suffix(suffix),
                "curation": f"curation/{path.name}",
                "classified": f"classified/{classified_path.name}" if classified_path.exists() else "UNKNOWN",
                "verified": f"verified/{verified_path.name}" if verified_path.exists() else "UNKNOWN",
                "raw_dir": f"raw/c{suffix}",
                "triaged_dir": f"triaged/c{suffix}",
                "rejected_dir": f"rejected/c{suffix}",
                "claim_ledger": f"claim-ledger/ha{suffix}-claims.yaml",
                "audit": f"hallucination-audits/ha{suffix}-audit.yaml",
            }
        )
    if not tasks:
        raise SystemExit(f"no curation files found in {curation_dir}")
    return tasks


def write_schedule(run_dir: Path, phase: str, out_path: Path, tasks: list[dict[str, str]]) -> None:
    lines: list[str] = []
    lines.append("version: authority_curation_hallucination_audit_schedule_v0_1")
    lines.append("source: editorial-curation")
    lines.append(f"phase: {phase}")
    lines.append(f"created_at: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"run_dir: {q(str(run_dir))}")
    lines.append("assignment_policy:")
    lines.append("  codex_direction: ascending")
    lines.append("  agy_direction: descending")
    lines.append("  codex_batch_size: 5")
    lines.append("  agy_concurrency: 1")
    lines.append("notes:")
    lines.append("  - One hallucination-audit task per curation file.")
    lines.append("  - Workers must check claims against cited source files and URLs.")
    lines.append("  - Unsupported, conflicting, or unknown claims are blocked from publication use.")
    lines.append("tasks:")
    for task in tasks:
        lines.append(f"  - task_id: {q(task['task_id'])}")
        lines.append("    status: pending")
        lines.append(f"    worker: {task['worker']}")
        lines.append(f"    curation_task_id: {q('ec' + task['suffix'])}")
        lines.append(f"    collection_task_id: {q('c' + task['suffix'])}")
        lines.append(f"    input_curation: {q(task['curation'])}")
        lines.append(f"    input_classified: {q(task['classified'])}")
        lines.append(f"    input_verified: {q(task['verified'])}")
        lines.append("    input_source_dirs:")
        lines.append(f"      - {q(task['raw_dir'])}")
        lines.append(f"      - {q(task['triaged_dir'])}")
        lines.append(f"      - {q(task['rejected_dir'])}")
        lines.append(f"    output_claim_ledger: {q(task['claim_ledger'])}")
        lines.append(f"    output_audit: {q(task['audit'])}")
        lines.append(f"    title: {q('Audit curated claims from source set ' + task['suffix'])}")
        lines.append("    expected_outputs:")
        lines.append("      - claim-ledger")
        lines.append("      - hallucination-audit")
        lines.append("      - done")
        lines.append("    instruction: >-")
        lines.append("      Read the assigned curation file and cited source pointers. Extract publication-relevant")
        lines.append("      claims into the claim ledger, then audit each claim against cited source files and URLs.")
        lines.append("      Mark claims SUPPORTED, PARTIALLY_SUPPORTED, UNSUPPORTED, CONFLICT, or UNKNOWN.")
        lines.append("      Block unsupported, conflicting, and unknown claims from public use. Use UNKNOWN instead")
        lines.append("      of guessing when source support is missing or inaccessible.")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    if not run_dir.exists():
        raise SystemExit(f"run directory not found: {run_dir}")
    ensure_dirs(run_dir)
    tasks = discover_tasks(run_dir)
    out_path = args.out.expanduser().resolve() if args.out else run_dir / "schedule" / f"{args.phase}-schedule.yaml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_schedule(run_dir, args.phase, out_path, tasks)
    print(f"schedule_path: {out_path}")
    print(f"tasks: {len(tasks)}")
    print(f"codex_tasks: {sum(1 for task in tasks if task['worker'] == 'codex')}")
    print(f"agy_tasks: {sum(1 for task in tasks if task['worker'] == 'agy')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
