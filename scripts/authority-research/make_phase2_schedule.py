#!/usr/bin/env python3
"""Create simple Phase 2 schedules for claim, synthesis, topic-pack, and brief tasks."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import yaml
from _contract import next_schedule_path


PHASES = {
    "claim-ledger": {
        "task_prefix": "cl",
        "worker": "codex",
        "expected_outputs": ["claim-ledger", "done"],
        "title": "Build claim ledger from curated sources",
        "instruction": "Read assigned curation files and extract public/design claims with source_files or source_urls. Do not invent unsupported claims.",
    },
    "design-synthesis": {
        "task_prefix": "ds",
        "worker": "codex",
        "expected_outputs": ["synthesis", "done"],
        "title": "Build traceable design synthesis",
        "instruction": "Read audited claims, public material gate, curation files, and topic packs. Produce synthesis YAML with claim_refs/source pointers and blocked_or_unknown_items.",
    },
    "topic-pack": {
        "task_prefix": "tp",
        "worker": "codex",
        "expected_outputs": ["topic-packs", "done"],
        "title": "Build topic packs from audited material",
        "instruction": "Group curated sources and audited usable/caveated claims into article-ready topic packs. Preserve weak/conflicting sources as cautions.",
    },
    "article-brief": {
        "task_prefix": "ab",
        "worker": "codex",
        "expected_outputs": ["article-briefs", "done"],
        "title": "Build decision-ready article brief",
        "instruction": "Create an article/research brief from topic packs and audited claims. Include thesis, usable claims, excluded claims, caveats, and next verifier tasks.",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a Phase 2 authority-research schedule.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--phase", required=True, choices=sorted(PHASES))
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--task-count", type=int, default=1)
    return parser.parse_args()


def files_under(run_dir: Path, folder: str, pattern: str = "*.y*ml") -> list[str]:
    path = run_dir / folder
    if not path.exists():
        return []
    return [str(item.relative_to(run_dir)) for item in sorted(path.glob(pattern)) if item.is_file()]


def phase_inputs(run_dir: Path, phase: str) -> dict[str, list[str]]:
    if phase == "claim-ledger":
        return {"curation": files_under(run_dir, "curation")}
    if phase == "design-synthesis":
        return {
            "curation": files_under(run_dir, "curation"),
            "claim_ledger": files_under(run_dir, "claim-ledger"),
            "hallucination_audits": files_under(run_dir, "hallucination-audits"),
            "topic_packs": files_under(run_dir, "topic-packs"),
            "gates": [item for item in ["logs/public-material-gate.yaml"] if (run_dir / item).exists()],
        }
    if phase == "topic-pack":
        return {
            "curation": files_under(run_dir, "curation"),
            "hallucination_audits": files_under(run_dir, "hallucination-audits"),
            "gates": [item for item in ["logs/public-material-gate.yaml"] if (run_dir / item).exists()],
        }
    if phase == "article-brief":
        return {
            "topic_packs": files_under(run_dir, "topic-packs"),
            "hallucination_audits": files_under(run_dir, "hallucination-audits"),
            "gates": [item for item in ["logs/public-material-gate.yaml", "logs/synthesis-quality-report.yaml"] if (run_dir / item).exists()],
        }
    return {}


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    if not run_dir.exists():
        raise SystemExit(f"run directory not found: {run_dir}")
    phase = PHASES[args.phase]
    for dirname in ["claim-ledger", "hallucination-audits", "topic-packs", "article-briefs", "synthesis", "schedule", "done", "prompts", "logs"]:
        (run_dir / dirname).mkdir(parents=True, exist_ok=True)
    inputs = phase_inputs(run_dir, args.phase)
    tasks = []
    for index in range(1, args.task_count + 1):
        task_id = f"{phase['task_prefix']}{index:03d}"
        tasks.append(
            {
                "task_id": task_id,
                "status": "pending",
                "worker": phase["worker"],
                "contract": args.phase,
                "title": phase["title"],
                "input_files": inputs,
                "expected_outputs": phase["expected_outputs"],
                "instruction": phase["instruction"],
            }
        )
    schedule = {
        "version": "authority_phase2_schedule_v0_1",
        "phase": args.phase,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_dir),
        "assignment_policy": {"codex_direction": "ascending", "agy_direction": "descending", "codex_batch_size": 5, "agy_concurrency": 1},
        "tasks": tasks,
    }
    out = args.out.expanduser().resolve() if args.out else next_schedule_path(run_dir / "schedule", args.phase)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(schedule, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(yaml.safe_dump({"schedule_path": str(out), "phase": args.phase, "tasks": len(tasks), "input_groups": {key: len(value) for key, value in inputs.items()}}, allow_unicode=True, sort_keys=False).strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
