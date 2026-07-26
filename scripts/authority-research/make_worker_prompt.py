#!/usr/bin/env python3
"""Create a worker prompt with authority-research global rules prepended."""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


SKILL_DIR = Path(__file__).resolve().parents[1]
CONTRACTS_PATH = SKILL_DIR / "references" / "worker-contracts.md"

CONTRACT_ALIASES = {
    "axis-discovery": "Axis Discovery (Bootstrap)",
    "source-scout": "Source Scout",
    "site-profile": "Site Profiler",
    "site-profiler": "Site Profiler",
    "collection": "Collector",
    "collector": "Collector",
    "classification": "Classifier",
    "classifier": "Classifier",
    "source-verification": "Source Verifier",
    "source-verifier": "Source Verifier",
    "fact-verification": "Fact Verifier",
    "fact-verifier": "Fact Verifier",
    "editorial-curation": "Editorial Curator",
    "editorial-curator": "Editorial Curator",
    "claim-ledger": "Claim-Ledger Builder",
    "claim-ledger-builder": "Claim-Ledger Builder",
    "hallucination-audit": "Hallucination Auditor",
    "hallucination-auditor": "Hallucination Auditor",
    "topic-pack": "Topic-Pack Builder",
    "topic-pack-builder": "Topic-Pack Builder",
    "article-brief": "Article-Brief Writer",
    "article-brief-writer": "Article-Brief Writer",
    "design-synthesis": "Design Synthesis Writer",
    "design-synthesis-writer": "Design Synthesis Writer",
    "dedup": "Dedup Mapper",
    "dedup-mapper": "Dedup Mapper",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create an authority-research worker prompt from a schedule task.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--schedule", required=True, type=Path)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--contract", default=None, help="Worker contract name or alias. Defaults to schedule phase.")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--print", action="store_true", help="Print prompt after writing it.")
    return parser.parse_args()


def section(markdown: str, heading: str) -> str:
    pattern = re.compile(rf"^## {re.escape(heading)}\n(?P<body>.*?)(?=^## |\Z)", re.M | re.S)
    match = pattern.search(markdown)
    if not match:
        raise SystemExit(f"contract section not found: {heading}")
    return f"## {heading}\n{match.group('body').strip()}\n"


def load_schedule(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
        raise SystemExit(f"schedule does not contain tasks: {path}")
    return data


def find_task(schedule: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task in schedule["tasks"]:
        if str(task.get("task_id")) == str(task_id):
            return task
    raise SystemExit(f"task_id not found in schedule: {task_id}")


def infer_contract(schedule: dict[str, Any], task: dict[str, Any], explicit: str | None) -> str:
    key = explicit or task.get("contract") or schedule.get("phase") or ""
    key = str(key).strip().lower().replace("_", "-")
    if key in CONTRACT_ALIASES:
        return CONTRACT_ALIASES[key]
    expected = {str(item) for item in task.get("expected_outputs") or []}
    task_id = str(task.get("task_id") or "")
    if "curation" in expected or task_id.startswith("ec"):
        return "Editorial Curator"
    if "claim-ledger" in expected or task_id.startswith("cl"):
        return "Claim-Ledger Builder"
    if "hallucination-audits" in expected or task_id.startswith("ha"):
        return "Hallucination Auditor"
    if "topic-packs" in expected or task_id.startswith("tp"):
        return "Topic-Pack Builder"
    if "article-briefs" in expected or task_id.startswith("ab"):
        return "Article-Brief Writer"
    if "synthesis" in expected or task_id.startswith("ds"):
        return "Design Synthesis Writer"
    raise SystemExit(f"cannot infer worker contract; pass --contract. phase={schedule.get('phase')!r} task_id={task_id!r}")


def render_prompt(run_dir: Path, schedule_path: Path, schedule: dict[str, Any], task: dict[str, Any], contract_heading: str) -> str:
    contracts = CONTRACTS_PATH.read_text(encoding="utf-8")
    global_rules = section(contracts, "Global Rules")
    contract = section(contracts, contract_heading)
    task_yaml = yaml.safe_dump(task, allow_unicode=True, sort_keys=False, width=120).strip()
    return f"""# Authority Research Worker Prompt

Generated: {datetime.now(timezone.utc).isoformat()}
Run directory: `{run_dir}`
Schedule: `{schedule_path}`
Task ID: `{task.get('task_id')}`
Worker contract: `{contract_heading}`

{global_rules}

{contract}

## Assigned Task

```yaml
{task_yaml}
```

## Execution Requirements

- Treat this startup prompt as your only instruction source.
- Read only files needed for the assigned task.
- Write outputs under the run directory only.
- Always write `done/{task.get('task_id')}.yaml` with `status: done` or `status: failed`.
- Final chat response must contain only: `task_id`, `status`, `done_path`.
"""


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    schedule_path = args.schedule.expanduser().resolve()
    schedule = load_schedule(schedule_path)
    task = find_task(schedule, args.task_id)
    contract_heading = infer_contract(schedule, task, args.contract)
    prompt = render_prompt(run_dir, schedule_path, schedule, task, contract_heading)
    out = args.out.expanduser().resolve() if args.out else run_dir / "prompts" / f"{args.task_id}-{contract_heading.lower().replace(' ', '-').replace('(', '').replace(')', '')}.prompt.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(prompt, encoding="utf-8")
    print(f"prompt_path: {out}")
    if args.print:
        print(prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
