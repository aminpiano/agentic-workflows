#!/usr/bin/env python3
"""Create a conservative editorial curation schedule for an authority research run."""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path


CLASSIFIED_RE = re.compile(r"^cl(?P<suffix>[0-9]{3})-classification\.ya?ml$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create an authority curation schedule.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--phase", default="editorial-curation")
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
        "curation",
        "topic-packs",
        "article-briefs",
        "claim-ledger",
        "dedup",
        "synthesis",
        "schedule",
        "done",
        "logs",
        "prompts",
    ]:
        (run_dir / name).mkdir(parents=True, exist_ok=True)


def discover_tasks(run_dir: Path) -> list[dict[str, str]]:
    classified_dir = run_dir / "classified"
    if not classified_dir.exists():
        raise SystemExit(f"classified directory not found: {classified_dir}")

    tasks: list[dict[str, str]] = []
    for path in sorted(classified_dir.iterdir()):
        if not path.is_file():
            continue
        match = CLASSIFIED_RE.match(path.name)
        if not match:
            continue
        suffix = match.group("suffix")
        verified_path = run_dir / "verified" / f"sv{suffix}-source-verification.yaml"
        tasks.append(
            {
                "suffix": suffix,
                "task_id": f"ec{suffix}",
                "worker": worker_for_suffix(suffix),
                "classified": f"classified/{path.name}",
                "verified": f"verified/{verified_path.name}" if verified_path.exists() else "UNKNOWN",
                "raw_dir": f"raw/c{suffix}",
                "triaged_dir": f"triaged/c{suffix}",
                "rejected_dir": f"rejected/c{suffix}",
                "output": f"curation/ec{suffix}-curation.yaml",
            }
        )
    if not tasks:
        raise SystemExit(f"no classification files found in {classified_dir}")
    return tasks


def write_schedule(run_dir: Path, phase: str, out_path: Path, tasks: list[dict[str, str]]) -> None:
    lines: list[str] = []
    lines.append("version: authority_curation_schedule_v0_1")
    lines.append("source: classification-and-source-verification")
    lines.append(f"phase: {phase}")
    lines.append(f"created_at: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"run_dir: {q(str(run_dir))}")
    lines.append("assignment_policy:")
    lines.append("  codex_direction: ascending")
    lines.append("  agy_direction: descending")
    lines.append("  codex_batch_size: 5")
    lines.append("  agy_concurrency: 1")
    lines.append("notes:")
    lines.append("  - Conservative schedule: one editorial curation task per classification file.")
    lines.append("  - Workers read assigned classified and verified files; main session does not read source content.")
    lines.append("tasks:")
    for task in tasks:
        lines.append(f"  - task_id: {q(task['task_id'])}")
        lines.append(f"    status: pending")
        lines.append(f"    worker: {task['worker']}")
        lines.append(f"    collection_task_id: {q('c' + task['suffix'])}")
        lines.append(f"    input_classified: {q(task['classified'])}")
        lines.append(f"    input_verified: {q(task['verified'])}")
        lines.append("    input_source_dirs:")
        lines.append(f"      - {q(task['raw_dir'])}")
        lines.append(f"      - {q(task['triaged_dir'])}")
        lines.append(f"      - {q(task['rejected_dir'])}")
        lines.append(f"    output_file: {q(task['output'])}")
        lines.append(f"    title: {q('Editorially curate source set ' + task['suffix'])}")
        lines.append("    expected_outputs:")
        lines.append("      - curation")
        lines.append("      - done")
        lines.append("    instruction: >-")
        lines.append("      Read the assigned classified and verified files, optionally consult the assigned")
        lines.append("      source-note folders, then create an editorial curation YAML. Separate evidence,")
        lines.append("      official guidance, regulatory material, product/company material, market context,")
        lines.append("      controversy, and background. Do not write a final blog draft. Use UNKNOWN for")
        lines.append("      unsupported fields and do not accept unverified claims as facts.")
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
