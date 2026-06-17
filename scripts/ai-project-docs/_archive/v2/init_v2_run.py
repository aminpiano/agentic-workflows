#!/usr/bin/env python3
"""Initialize an AI-docs v2 file-based run directory."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path


def current_commit(root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "uncommitted"
    return proc.stdout.strip() or "uncommitted"


def write_default_config(path: Path) -> None:
    path.write_text(
        """version: 2
profile: auto
evidence_policy:
  overview: tracked
  architecture: strict
  api_or_types: strict
  runtime_ops: tracked
outputs:
  format: slot-docs
  state_file: ai-docs/ai-docs-state.json
""",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", nargs="?", default=".")
    parser.add_argument("--run-id")
    parser.add_argument("--no-config", action="store_true", help="Do not create ai-docs/ai-project.yaml")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    ai_docs = root / "ai-docs"
    ai_docs.mkdir(parents=True, exist_ok=True)
    run_id = args.run_id or dt.datetime.now().strftime("%Y%m%d-%H%M%S-v2")
    run_dir = ai_docs / ".work" / run_id
    for subdir in ["source-index", "planning", "prompts", "packets", "synthesis", "done", "logs"]:
        (run_dir / subdir).mkdir(parents=True, exist_ok=True)

    config_path = ai_docs / "ai-project.yaml"
    if not args.no_config and not config_path.exists():
        write_default_config(config_path)

    run = {
        "version": 2,
        "run_id": run_id,
        "created_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "project_root": str(root),
        "commit": current_commit(root),
        "status": "initialized",
        "layout": {
            "source_index": "source-index/index-final.json",
            "schedule": "planning/schedule.json",
            "doc_slots": "planning/doc-slots.json",
            "prompts": "prompts/",
            "packets": "packets/",
            "done": "done/",
            "logs": "logs/",
        },
    }
    (run_dir / "run.yaml").write_text(
        "\n".join(
            [
                "version: 2",
                f"run_id: {json.dumps(run_id)}",
                f"created_at: {json.dumps(run['created_at'])}",
                f"project_root: {json.dumps(str(root))}",
                f"commit: {json.dumps(run['commit'])}",
                "status: initialized",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"run_dir": str(run_dir), "config": str(config_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
