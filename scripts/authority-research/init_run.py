#!/usr/bin/env python3
"""Create an authority-research run folder with the standard layout."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path


SUBDIRS = [
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


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^0-9a-z]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value[:60] or "research-run"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize an authority research run directory.")
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--run-id", default=None)
    return parser.parse_args()


def dump_yaml(data: dict[str, object]) -> str:
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"  - {item}" for item in value)
        else:
            lines.append(f"{key}: {json.dumps(value)}")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    project = args.project.expanduser().resolve()
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = args.run_id or f"{stamp}-{slugify(args.topic)}"
    run_dir = project / "data" / "authority-research-runs" / run_id

    for subdir in SUBDIRS:
        (run_dir / subdir).mkdir(parents=True, exist_ok=True)

    manifest = {
        "version": "authority_research_run_v0_1",
        "run_id": run_id,
        "topic": args.topic,
        "created_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "status": "initialized",
        "layout": SUBDIRS,
    }
    (run_dir / "run.yaml").write_text(dump_yaml(manifest), encoding="utf-8")
    print(json.dumps({"run_dir": str(run_dir), "run_id": run_id}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
