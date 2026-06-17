#!/usr/bin/env python3
"""Build .model/runtime.json from the deterministic ops inventory (decision 2/3).

Reuses scripts/ai-project-docs/ops_inventory.py for the repo-only ops scan (compose, Dockerfiles,
systemd units, nginx/traefik/caddy, CI, env files; secret values never recorded),
then projects it into the v3 runtime model and appends ops anchors to
anchors.ndjson so the drift checker can track them.

repo-only by default; --host-readonly opts into read-only host probes (no sudo).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ops_inventory as ops  # noqa: E402


SERVICE_KINDS = {"docker-compose", "dockerfile", "nginx", "traefik", "caddy"}


def collect(root: Path, include_ops_docs: bool, host_readonly: bool) -> dict:
    candidates = ops.git_files(root) or ops.walk_files(root)
    repo_ops = []
    for rel in sorted(dict.fromkeys(candidates)):
        if rel.startswith("ai-docs/.work/") or rel.startswith("ai-docs/.model/"):
            continue
        p = root / rel
        if p.is_file() and ops.is_ops_candidate(rel, include_ops_docs=include_ops_docs):
            try:
                repo_ops.append(ops.inspect_ops_file(root, rel))
            except OSError:
                continue
    host = ops.collect_host_readonly() if host_readonly else None
    return {"repo_ops_files": repo_ops, "host_readonly": host}


def classify_process_manager(path: str, kind: str) -> str | None:
    lower = path.lower()
    if kind == "systemd":
        return "systemd"
    if "ecosystem.config" in lower or "pm2" in lower:
        return "pm2"
    if Path(lower).name == "procfile":
        return "procfile"
    if "supervisord" in lower:
        return "supervisor"
    return None


def build_runtime(inv: dict, existing_anchor_ids: set[str]) -> tuple[dict, list[dict]]:
    processes: list[dict] = []
    services: list[dict] = []
    env_keys: list[dict] = []
    new_anchors: list[dict] = []

    def anchor_id(path: str, line, kind: str) -> str:
        base = f"a:{path}:{line if line else 1}:{kind}"
        candidate = base
        n = 2
        while candidate in existing_anchor_ids:
            candidate = f"{base}:{n}"
            n += 1
        existing_anchor_ids.add(candidate)
        return candidate

    for item in inv["repo_ops_files"]:
        path = item["path"]
        kind = item["kind"]
        if kind == "ops-doc":
            continue
        manager = classify_process_manager(path, kind)
        anchor_kind = "process" if manager else ("config" if kind in SERVICE_KINDS else "config")
        aid = anchor_id(path, item.get("anchor_line"), anchor_kind)
        new_anchors.append({
            "id": aid,
            "path": path,
            "anchor_text": item["anchor"],
            "anchor_line": item.get("anchor_line"),
            "file_sha256": item["sha256"],
            "kind": anchor_kind,
            "policy": "tracked",
            "origin": "deterministic",
        })
        stem = Path(path).stem
        if manager:
            processes.append({
                "name": stem,
                "manager": manager,
                "command": None,
                "path": path,
                "anchor_id": aid,
                "port": item["ports"][0] if item["ports"] else None,
            })
        if kind in SERVICE_KINDS:
            services.append({
                "name": stem if stem not in ("docker-compose", "compose") else "compose",
                "kind": kind,
                "path": path,
                "ports": item["ports"],
                "domains": item["domains"],
                "anchor_id": aid,
            })
        for key in item["env_keys"]:
            env_keys.append({"key": key, "path": path, "anchor_id": aid})

    runtime = {
        "version": 3,
        "kind": "ai-docs-v3-runtime",
        "mode": "host-readonly" if inv["host_readonly"] else "repo-only",
        "processes": processes,
        "services": services,
        "env_keys": env_keys,
        "topology": [],
        "host_readonly": inv["host_readonly"],
        "safety": {"writes_performed": False, "sudo_used": False, "secret_values_recorded": False},
    }
    return runtime, new_anchors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", nargs="?", default=".")
    parser.add_argument("--model-dir", required=True, help="Model staging dir containing anchors.ndjson; runtime.json is written here")
    parser.add_argument("--include-ops-docs", action="store_true")
    parser.add_argument("--host-readonly", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    model_dir = Path(args.model_dir).resolve()
    model_dir.mkdir(parents=True, exist_ok=True)
    anchors_path = model_dir / "anchors.ndjson"

    existing = []
    existing_ids: set[str] = set()
    if anchors_path.exists():
        for line in anchors_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                existing.append(rec)
                existing_ids.add(rec["id"])

    inv = collect(root, args.include_ops_docs, args.host_readonly)
    runtime, new_anchors = build_runtime(inv, existing_ids)

    with anchors_path.open("w", encoding="utf-8") as fh:
        for rec in existing + new_anchors:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    (model_dir / "runtime.json").write_text(json.dumps(runtime, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({
        "runtime": str(model_dir / "runtime.json"),
        "processes": len(runtime["processes"]),
        "services": len(runtime["services"]),
        "env_keys": len(runtime["env_keys"]),
        "ops_anchors_added": len(new_anchors),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
