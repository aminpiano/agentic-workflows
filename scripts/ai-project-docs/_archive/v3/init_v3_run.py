#!/usr/bin/env python3
"""Initialize an AI-docs v3 run directory and (optionally) the v3 config.

v3 inverts v1/v2: the first-class output is a structured architecture model in
ai-docs/.model/. Markdown docs are regeneratable views. This script only scaffolds
the run staging area + ai-project.yaml; the model is staged under .work/<run-id>/model
and applied to ai-docs/.model/ after the gate passes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path

RUN_SUBDIRS = [
    "source-index",   # deterministic index outputs
    "ops-inventory",  # deterministic ops outputs
    "planning",       # planner prompt + doc_plan staging
    "prompts",        # generated LLM prompts
    "model",          # staged .model/ before apply
    "render",         # staged markdown views before apply
    "done",           # worker done markers
    "logs",           # dashboards / reports
]

DEFAULT_CONFIG = """version: 3
generation: v3
profile: auto
mode: full
model_dir: ai-docs/.model
budget:
  full:   {wall_min: 40, llm_input_tokens: 4000000, output_tokens: 300000}
  fast:   {wall_min: 15, llm_input_tokens: 2000000, output_tokens: 250000}
  update: {wall_min: 3,  llm_input_tokens: 250000}
evidence_policy:
  default: tracked
  architecture: strict
  api: strict
outputs:
  format: model-plus-views
  router: ai-docs/00_INDEX.md
"""


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", nargs="?", default=".")
    parser.add_argument("--run-id")
    parser.add_argument("--mode", choices=["full", "fast", "update"], default="full")
    parser.add_argument("--no-config", action="store_true", help="Do not create ai-docs/ai-project.yaml")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    if not root.exists():
        print(f"Project root does not exist: {root}")
        return 2

    ai_docs = root / "ai-docs"
    ai_docs.mkdir(parents=True, exist_ok=True)
    run_id = args.run_id or dt.datetime.now().strftime("%Y%m%d-%H%M%S-v3")
    run_dir = ai_docs / ".work" / run_id
    for subdir in RUN_SUBDIRS:
        (run_dir / subdir).mkdir(parents=True, exist_ok=True)

    config_path = ai_docs / "ai-project.yaml"
    if not args.no_config and not config_path.exists():
        config_path.write_text(DEFAULT_CONFIG, encoding="utf-8")

    run = {
        "version": 3,
        "run_id": run_id,
        "mode": args.mode,
        "created_at": now_iso(),
        "project_root": str(root),
        "commit": current_commit(root),
        "status": "initialized",
        "layout": {
            "source_index": "source-index/",
            "ops_inventory": "ops-inventory/",
            "doc_plan": "planning/doc_plan.json",
            "prompts": "prompts/",
            "model_staging": "model/",
            "render_staging": "render/",
            "done": "done/",
            "logs": "logs/",
            "model_final": "ai-docs/.model/",
        },
    }
    (run_dir / "run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({"run_dir": str(run_dir), "config": str(config_path), "mode": args.mode}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
