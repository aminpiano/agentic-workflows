#!/usr/bin/env python3
"""Measure file counts and byte sizes for an authority-research run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml


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
    "synthesis",
    "dedup",
    "drafted",
    "done",
    "logs",
    "prompts",
]

DONE_STATUS_ALIASES = {
    "completed": "done",
    "complete": "done",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure an authority research run folder.")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args()


def measure_stage(path: Path) -> dict:
    files = [p for p in path.rglob("*") if p.is_file()] if path.exists() else []
    return {
        "files": len(files),
        "bytes": sum(p.stat().st_size for p in files),
    }


def normalize_done_status(value: object) -> str:
    status = str(value or "other").strip().strip('"').strip("'").lower()
    return DONE_STATUS_ALIASES.get(status, status)


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    stages = {stage: measure_stage(run_dir / stage) for stage in STAGES}
    done_files = list((run_dir / "done").glob("*.yaml")) if (run_dir / "done").exists() else []
    done_status = {"done": 0, "failed": 0, "other": 0}
    raw_done_status: dict[str, int] = {}
    for path in done_files:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            raw_status = str(data.get("status", "other")).strip().strip('"').strip("'").lower()
            status = normalize_done_status(raw_status)
        except Exception:
            raw_status = "unparseable"
            status = "other"
        raw_done_status[raw_status] = raw_done_status.get(raw_status, 0) + 1
        done_status[status if status in done_status else "other"] += 1

    report = {
        "run_dir": str(run_dir),
        "stages": stages,
        "done_status": done_status,
        "raw_done_status": raw_done_status,
        "total_files": sum(item["files"] for item in stages.values()),
        "total_bytes": sum(item["bytes"] for item in stages.values()),
    }
    if not args.no_write:
        out = run_dir / "logs" / "measure-report.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.safe_dump(report, allow_unicode=True, sort_keys=False), encoding="utf-8")
        report["report_path"] = str(out)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(yaml.safe_dump(report, allow_unicode=True, sort_keys=False).strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
