#!/usr/bin/env python3
"""Create AI-docs v2 doc slots and source-scout schedule from a native index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_SLOT_TASK_LIMITS = {
    "overview": 8,
    "architecture": 24,
    "api_or_types": 10,
    "runtime_ops": 8,
}

SLOT_DEFS = {
    "overview": {
        "output_doc": "00_INDEX.md",
        "evidence_policy": "tracked",
        "description": "Project identity, stack, entry commands, and routing to leaf docs.",
    },
    "architecture": {
        "output_doc": "architecture/overview.md",
        "evidence_policy": "strict",
        "description": "Entrypoints, module boundaries, and data/control flow.",
    },
    "api_or_types": {
        "output_doc": "architecture/api-or-types.md",
        "evidence_policy": "strict",
        "description": "API surface, schemas, migrations, and important type contracts.",
    },
    "runtime_ops": {
        "output_doc": "operations/runtime.md",
        "evidence_policy": "tracked",
        "description": "Run, deploy, environment, logs, and production safety notes.",
    },
}

ROOT_OVERVIEW_DOCS = {
    "agents.md",
    "claude.md",
    "readme.md",
    "contributing.md",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "cargo.toml",
}

CONFIG_NAMES = {
    "alembic.ini",
    "dockerfile",
    "ecosystem.config.js",
    "next.config.js",
    "next.config.mjs",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "tsconfig.json",
    "vite.config.js",
    "vite.config.ts",
}


def yaml_scalar(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def write_simple_yaml(path: Path, value: object) -> None:
    path.write_text(to_yaml(value), encoding="utf-8")


def to_yaml(value: object, indent: int = 0) -> str:
    pad = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.append(to_yaml(item, indent + 2).rstrip())
            else:
                lines.append(f"{pad}{key}: {yaml_scalar(item)}")
        return "\n".join(lines) + "\n"
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                lines.append(f"{pad}-")
                lines.append(to_yaml(item, indent + 2).rstrip())
            else:
                lines.append(f"{pad}- {yaml_scalar(item)}")
        return "\n".join(lines) + "\n"
    return f"{pad}{yaml_scalar(value)}\n"


def slot_for(record: dict) -> str:
    path = record["path"].lower()
    role = record["role_guess"]
    name = Path(path).name
    if path.startswith("ai-docs/"):
        return "overview"
    if role in {"agent-instructions", "dependency-manifest"} or name in {"readme.md", "package.json"}:
        return "overview"
    if role in {"api", "schema"} or "/types/" in path or name.endswith(".d.ts"):
        return "api_or_types"
    if role == "runtime-ops" or "docker" in path or "compose" in path or "systemd" in path:
        return "runtime_ops"
    return "architecture"


def top_dir(path: str) -> str:
    return path.split("/", 1)[0]


def is_root_file(path: str) -> bool:
    return "/" not in path


def is_high_value_overview(record: dict) -> bool:
    path = record["path"].lower()
    name = Path(path).name
    return (
        is_root_file(path)
        and name in ROOT_OVERVIEW_DOCS
        or record["role_guess"] in {"agent-instructions", "dependency-manifest"}
    )


def is_config_support(record: dict) -> bool:
    path = record["path"].lower()
    name = Path(path).name
    return name in CONFIG_NAMES or path.startswith((".github/workflows/", "nginx/"))


def schedule_priority(record: dict, profile: str) -> tuple[int, int, str] | None:
    role = record["role_guess"]
    path = record["path"].lower()
    name = Path(path).name
    tokens = record.get("token_estimate") or 0
    if role in {"agent-instructions", "dependency-manifest"}:
        return (0, tokens, path)
    if role in {"runtime-ops", "api", "schema", "source"}:
        return (1, tokens, path)
    if role == "test":
        return (3, tokens, path)
    if role == "documentation":
        if is_high_value_overview(record) or path in {"docs/readme.md", "scripts/readme.md"}:
            return (2, tokens, path)
        if profile == "history-aware":
            return (5, tokens, path)
        return None
    if role == "support":
        if is_config_support(record):
            return (2, tokens, path)
        if profile == "history-aware":
            return (6, tokens, path)
        return None
    if name in ROOT_OVERVIEW_DOCS:
        return (2, tokens, path)
    return (7, tokens, path) if profile == "history-aware" else None


def make_ranges(files: list[dict], max_files: int, max_tokens: int) -> list[list[dict]]:
    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_tokens = 0
    for record in files:
        tokens = record.get("token_estimate") or 0
        if current and (len(current) >= max_files or current_tokens + tokens > max_tokens):
            chunks.append(current)
            current = []
            current_tokens = 0
        current.append(record)
        current_tokens += tokens
    if current:
        chunks.append(current)
    return chunks


def parse_slot_limits(value: str | None) -> dict[str, int]:
    limits = dict(DEFAULT_SLOT_TASK_LIMITS)
    if not value:
        return limits
    for part in value.split(","):
        if not part.strip():
            continue
        if "=" not in part:
            raise SystemExit(f"Invalid --slot-task-limits item: {part}")
        key, raw = part.split("=", 1)
        key = key.strip()
        if key not in SLOT_DEFS:
            raise SystemExit(f"Unknown slot in --slot-task-limits: {key}")
        limits[key] = int(raw)
    return limits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index_json", help="Path to source-index/index-final.json")
    parser.add_argument("--out-dir", help="Defaults to the sibling planning directory")
    parser.add_argument("--max-files", type=int, default=24)
    parser.add_argument("--max-tokens", type=int, default=18_000)
    parser.add_argument("--profile", choices=["code-first", "history-aware", "ops-heavy"], help="Defaults to the source index profile")
    parser.add_argument("--slot-task-limits", help="Comma list such as overview=8,architecture=24,api_or_types=10,runtime_ops=8")
    args = parser.parse_args()

    index_path = Path(args.index_json).resolve()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    profile = args.profile or index.get("profile") or "code-first"
    slot_task_limits = parse_slot_limits(args.slot_task_limits)
    run_dir = index_path.parent.parent
    out_dir = Path(args.out_dir).resolve() if args.out_dir else run_dir / "planning"
    out_dir.mkdir(parents=True, exist_ok=True)

    buckets = {slot_id: [] for slot_id in SLOT_DEFS}
    deferred = []
    for record in index["files"].values():
        priority = schedule_priority(record, profile)
        if priority is None:
            deferred.append(
                {
                    "path": record["path"],
                    "role_guess": record["role_guess"],
                    "reason": f"profile_skipped:{profile}",
                    "token_estimate": record.get("token_estimate"),
                }
            )
            continue
        copy = dict(record)
        copy["_schedule_priority"] = priority
        buckets[slot_for(copy)].append(copy)

    slots = []
    tasks = []
    for slot_id, definition in SLOT_DEFS.items():
        files = sorted(buckets[slot_id], key=lambda item: item["_schedule_priority"])
        chunks = make_ranges(files, args.max_files, args.max_tokens)
        limit = slot_task_limits[slot_id]
        scheduled_chunks = chunks[:limit]
        deferred_chunks = chunks[limit:]
        for chunk in deferred_chunks:
            for item in chunk:
                deferred.append(
                    {
                        "path": item["path"],
                        "role_guess": item["role_guess"],
                        "slot_id": slot_id,
                        "reason": f"slot_task_limit:{limit}",
                        "token_estimate": item.get("token_estimate"),
                    }
                )
        slot = {
            "slot_id": slot_id,
            "status": "planned",
            "output_doc": definition["output_doc"],
            "evidence_policy": definition["evidence_policy"],
            "description": definition["description"],
            "source_count": sum(len(chunk) for chunk in scheduled_chunks),
            "deferred_source_count": sum(len(chunk) for chunk in deferred_chunks),
            "task_limit": limit,
        }
        slots.append(slot)
        for idx, chunk in enumerate(scheduled_chunks, start=1):
            task_id = f"{slot_id}-scout-{idx:03d}"
            tasks.append(
                {
                    "task_id": task_id,
                    "role": "source-scout",
                    "target_slots": [slot_id],
                    "packet_output": f"packets/{task_id}.packet.json",
                    "done_marker": f"done/{task_id}.done.json",
                    "source_ranges": [
                        {
                            "path": item["path"],
                            "lines": item["lines"],
                            "sha256": item["sha256"],
                            "role_guess": item["role_guess"],
                            "token_estimate": item["token_estimate"],
                            "schedule_priority": item["_schedule_priority"][0],
                        }
                        for item in chunk
                    ],
                }
            )

    schedule = {
        "version": 2,
        "kind": "ai-docs-v2-schedule",
        "source_index": str(index_path),
        "profile": profile,
        "slot_task_limits": slot_task_limits,
        "task_count": len(tasks),
        "deferred_source_count": len(deferred),
        "tasks": tasks,
    }
    deferred_doc = {"version": 2, "kind": "ai-docs-v2-deferred-sources", "profile": profile, "sources": deferred}
    slot_doc = {"version": 2, "kind": "ai-docs-v2-doc-slots", "profile": profile, "slots": slots}
    (out_dir / "schedule.json").write_text(json.dumps(schedule, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "doc-slots.json").write_text(json.dumps(slot_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "deferred-sources.json").write_text(json.dumps(deferred_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_simple_yaml(out_dir / "schedule.yaml", schedule)
    write_simple_yaml(out_dir / "doc-slots.yaml", slot_doc)
    write_simple_yaml(out_dir / "deferred-sources.yaml", deferred_doc)
    print(
        json.dumps(
            {
                "out_dir": str(out_dir),
                "profile": profile,
                "tasks": len(tasks),
                "slots": len(slots),
                "deferred_sources": len(deferred),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
