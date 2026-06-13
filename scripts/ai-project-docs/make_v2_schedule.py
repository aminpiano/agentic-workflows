#!/usr/bin/env python3
"""Create AI-docs v2 doc slots and source-scout schedule from a native index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


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
    if role in {"agent-instructions", "dependency-manifest", "documentation"} or name in {"readme.md", "package.json"}:
        return "overview"
    if role in {"api", "schema"} or "/types/" in path or name.endswith(".d.ts"):
        return "api_or_types"
    if role in {"runtime-ops", "test"} or "docker" in path or "compose" in path or "systemd" in path:
        return "runtime_ops"
    return "architecture"


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index_json", help="Path to source-index/index-final.json")
    parser.add_argument("--out-dir", help="Defaults to the sibling planning directory")
    parser.add_argument("--max-files", type=int, default=24)
    parser.add_argument("--max-tokens", type=int, default=18_000)
    args = parser.parse_args()

    index_path = Path(args.index_json).resolve()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    run_dir = index_path.parent.parent
    out_dir = Path(args.out_dir).resolve() if args.out_dir else run_dir / "planning"
    out_dir.mkdir(parents=True, exist_ok=True)

    buckets = {slot_id: [] for slot_id in SLOT_DEFS}
    for record in index["files"].values():
        buckets[slot_for(record)].append(record)

    slots = []
    tasks = []
    for slot_id, definition in SLOT_DEFS.items():
        files = sorted(buckets[slot_id], key=lambda item: (item["role_guess"], item["path"]))
        slot = {
            "slot_id": slot_id,
            "status": "planned",
            "output_doc": definition["output_doc"],
            "evidence_policy": definition["evidence_policy"],
            "description": definition["description"],
            "source_count": len(files),
        }
        slots.append(slot)
        for idx, chunk in enumerate(make_ranges(files, args.max_files, args.max_tokens), start=1):
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
                        }
                        for item in chunk
                    ],
                }
            )

    schedule = {
        "version": 2,
        "kind": "ai-docs-v2-schedule",
        "source_index": str(index_path),
        "task_count": len(tasks),
        "tasks": tasks,
    }
    slot_doc = {"version": 2, "kind": "ai-docs-v2-doc-slots", "slots": slots}
    (out_dir / "schedule.json").write_text(json.dumps(schedule, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "doc-slots.json").write_text(json.dumps(slot_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_simple_yaml(out_dir / "schedule.yaml", schedule)
    write_simple_yaml(out_dir / "doc-slots.yaml", slot_doc)
    print(json.dumps({"out_dir": str(out_dir), "tasks": len(tasks), "slots": len(slots)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
