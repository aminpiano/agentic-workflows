#!/usr/bin/env python3
"""Measure an authority curation run without reading source contents."""

from __future__ import annotations

import argparse
from pathlib import Path

from _contract import ALL_DIRS, STATUS_ALIASES


STAGES = list(ALL_DIRS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure curation run file counts and bytes.")
    parser.add_argument("run_dir", type=Path)
    return parser.parse_args()


def count_files(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    files = [p for p in path.rglob("*") if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


def done_status(done_dir: Path) -> dict[str, int]:
    counts = {"done": 0, "failed": 0, "other": 0}
    if not done_dir.exists():
        return counts
    for path in done_dir.glob("*.yaml"):
        text = path.read_text(encoding="utf-8", errors="replace")
        status = "other"
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("status:"):
                raw = stripped.split(":", 1)[1].split("#", 1)[0].strip().strip('"').strip("'")
                normalized = STATUS_ALIASES.get(raw.lower(), raw.lower())
                if normalized in counts:
                    status = normalized
                break
        counts[status] = counts.get(status, 0) + 1
    return counts


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    if not run_dir.exists():
        raise SystemExit(f"run directory not found: {run_dir}")

    stage_counts: dict[str, tuple[int, int]] = {}
    total_files = 0
    total_bytes = 0
    for stage in STAGES:
        count, size = count_files(run_dir / stage)
        stage_counts[stage] = (count, size)
        total_files += count
        total_bytes += size

    report_lines: list[str] = []
    report_lines.append(f"run_dir: {run_dir}")
    report_lines.append("stages:")
    for stage, (count, size) in stage_counts.items():
        report_lines.append(f"  {stage}:")
        report_lines.append(f"    files: {count}")
        report_lines.append(f"    bytes: {size}")
    report_lines.append("done_status:")
    for key, value in done_status(run_dir / "done").items():
        report_lines.append(f"  {key}: {value}")
    report_lines.append(f"total_files: {total_files}")
    report_lines.append(f"total_bytes: {total_bytes}")

    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    report_path = logs_dir / "curation-measure-report.yaml"
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    report_lines.append(f"report_path: {report_path}")
    print("\n".join(report_lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
