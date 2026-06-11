#!/usr/bin/env python3
"""Measure file counts and done marker status for an authority-research run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


STAGES = [
    "inventory",
    "profiles",
    "schedule",
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
    "drafted",
    "done",
    "logs",
    "prompts",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure an authority research run folder.")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args()


def measure_stage(path: Path) -> dict[str, int]:
    files = [p for p in path.rglob("*") if p.is_file()] if path.exists() else []
    return {
        "files": len(files),
        "bytes": sum(p.stat().st_size for p in files),
    }


def marker_status(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("status:"):
            return stripped.split(":", 1)[1].strip().strip('"').strip("'")
    return "other"


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    if not run_dir.exists():
        raise SystemExit(f"run directory not found: {run_dir}")

    stages = {stage: measure_stage(run_dir / stage) for stage in STAGES}
    done_status = {"done": 0, "failed": 0, "other": 0}
    done_dir = run_dir / "done"
    for path in done_dir.glob("*.yaml") if done_dir.exists() else []:
        status = marker_status(path)
        done_status[status if status in done_status else "other"] += 1

    report = {
        "run_dir": str(run_dir),
        "stages": stages,
        "done_status": done_status,
        "total_files": sum(item["files"] for item in stages.values()),
        "total_bytes": sum(item["bytes"] for item in stages.values()),
    }

    if not args.no_write:
        out = run_dir / "logs" / "measure-report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        report["report_path"] = str(out)

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
