#!/usr/bin/env python3
"""AI-docs v3 deterministic indexer.

Builds the deterministic layer of the architecture model (decision 3):
  - file_index.ndjson  (extends v2 source index with tier + read-ownership)
  - anchors.ndjson     (signatures, routes, imports, env, jobs, tables)
  - entities.ndjson    (deterministic candidates: route/table/job/service-class)
  - edges.ndjson       (same-repo import edges)
  - manifest.json      (run metadata + budget + counts; hashes finalized at apply)

Reuses scripts/ai-project-docs/repo_index.py for the file walk + per-file record. Adds the v3
literal extraction (scripts/ai-project-docs/v3/extract.py) and the tier/budget discipline that
keeps the LLM read-set to the top ~10% of files (decision 4 + 9).

Outputs into a model directory (default: ai-docs/.work/<run-id>/model). Apply to
ai-docs/.model/ happens later, after the gate passes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# reuse the v2 native indexer as a library
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import repo_index  # noqa: E402

import extract  # noqa: E402  (same dir)


MODE_CORE_CAP = {"full": 80, "fast": 50, "update": 50}

ROLE_WEIGHT = {
    "api": 5,
    "schema": 4,
    "runtime-ops": 4,
    "source": 3,
    "agent-instructions": 3,
    "dependency-manifest": 2,
    "documentation": 1,
    "test": 1,
    "support": 1,
    "unreadable": 0,
}

ENTRYPOINT_STEMS = {"main", "app", "index", "server", "cli", "__init__", "__main__", "mod", "lib", "wsgi", "asgi"}

SERVICE_CLASS_SUFFIXES = (
    "Service", "Manager", "Repository", "Controller", "Handler", "Client",
    "Store", "Provider", "Gateway", "Engine", "Worker", "Scheduler", "Server",
    "Router", "Registry", "Factory", "Queue", "Cache", "Pool", "Pipeline",
    "Orchestrator", "Dispatcher", "Processor", "Adapter", "Broker",
)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_ndjson(path: Path, rows: list[dict]) -> str:
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    path.write_text(text, encoding="utf-8")
    return sha256_bytes(text.encode("utf-8"))


def write_json(path: Path, obj) -> str:
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return sha256_bytes(text.encode("utf-8"))


def service_class_kind(symbol: str) -> str | None:
    if any(symbol.endswith(suf) for suf in SERVICE_CLASS_SUFFIXES):
        return "service"
    return None


def build_model(root: Path, profile: str, mode: str, args) -> dict:
    index = repo_index.build_index(
        root,
        args.max_bytes,
        args.max_doc_bytes,
        profile,
        args.include_history,
        args.include_existing_ai_docs,
        args.include_lockfiles,
    )
    indexed = index["files"]  # {path: record}
    repo_files = set(indexed.keys())

    anchors: list[dict] = []
    anchor_ids: set[str] = set()
    entities: dict[str, dict] = {}
    edges: dict[str, dict] = {}
    in_degree: Counter[str] = Counter()
    per_file_anchor_kinds: dict[str, set[str]] = defaultdict(set)
    bp_constraints_acc: list[dict] = []
    bp_middleware_acc: list[dict] = []

    def anchor_id(path: str, line: int, kind: str) -> str:
        base = f"a:{path}:{line}:{kind}"
        if base not in anchor_ids:
            return base
        n = 2
        while f"{base}:{n}" in anchor_ids:
            n += 1
        return f"{base}:{n}"

    def add_entity(eid: str, rec: dict) -> None:
        if eid in entities:
            # merge support anchors, keep first descriptor
            existing = entities[eid]
            for s in rec.get("support", []):
                if s not in existing["support"]:
                    existing["support"].append(s)
        else:
            entities[eid] = rec

    for path, rec in indexed.items():
        language = rec["language"]
        abs_path = root / path
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fsha = rec["sha256"]
        raw_anchors = extract.extract_file(path, language, text)
        for ra in raw_anchors:
            kind = ra["kind"]
            aid = anchor_id(path, ra["anchor_line"], kind)
            anchor_ids.add(aid)
            per_file_anchor_kinds[path].add(kind)
            anchors.append({
                "id": aid,
                "path": path,
                "anchor_text": ra["anchor_text"],
                "anchor_line": ra["anchor_line"],
                "file_sha256": fsha,
                "kind": kind,
                "policy": "tracked",
                "origin": "deterministic",
            })
            # deterministic entities
            if kind == "route":
                name = f"{ra.get('method', 'ANY')} {ra.get('route_path', ra['anchor_text'])}"
                add_entity(f"route:{name}", {
                    "id": f"route:{name}", "kind": "route", "name": name, "title": None,
                    "path": path, "anchor_id": aid, "importance": None, "summary": None,
                    "rationale": None, "origin": "deterministic", "support": [aid],
                })
            elif kind == "table":
                tname = ra.get("table_name", ra["anchor_text"])
                add_entity(f"table:{tname}", {
                    "id": f"table:{tname}", "kind": "table", "name": tname, "title": None,
                    "path": path, "anchor_id": aid, "importance": None, "summary": None,
                    "rationale": None, "origin": "deterministic", "support": [aid],
                })
            elif kind == "job":
                jid = f"job:{path}:{ra['anchor_line']}"
                add_entity(jid, {
                    "id": jid, "kind": "job", "name": f"job@{path}:{ra['anchor_line']}", "title": None,
                    "path": path, "anchor_id": aid, "importance": None, "summary": None,
                    "rationale": None, "origin": "deterministic", "support": [aid],
                })
            elif kind == "signature" and ra.get("sig_kind") == "class":
                symbol = ra.get("symbol", "")
                svc = service_class_kind(symbol)
                if svc:
                    add_entity(f"service:{symbol}", {
                        "id": f"service:{symbol}", "kind": "service", "name": symbol, "title": None,
                        "path": path, "anchor_id": aid, "importance": None, "summary": None,
                        "rationale": None, "origin": "deterministic", "support": [aid],
                    })
            elif kind == "import":
                target = ra.get("import_target", "")
                resolved = extract.resolve_import(language, target, path, repo_files)
                if resolved and resolved != path:
                    eid = f"import:file:{path}->|file:{resolved}"
                    if eid not in edges:
                        edges[eid] = {
                            "id": eid, "kind": "import",
                            "src": f"file:{path}", "dst": f"file:{resolved}",
                            "path": path, "anchor_id": aid,
                            "origin": "deterministic", "support": [aid], "rationale": None,
                        }
                        in_degree[resolved] += 1
            elif kind == "constraint":
                bp_constraints_acc.append({
                    "kind": ra.get("constraint_kind", "constraint"),
                    "file": path, "line": ra["anchor_line"],
                    "anchor_id": aid, "text": ra["anchor_text"],
                })
            elif kind == "middleware":
                bp_middleware_acc.append({
                    "name": ra.get("mw_name", ra["anchor_text"]),
                    "file": path, "line": ra["anchor_line"], "anchor_id": aid,
                })

    # ---- tier / budget ----
    def score(path: str, rec: dict) -> int:
        s = ROLE_WEIGHT.get(rec["role_guess"], 1)
        stem = Path(path).stem.lower()
        depth = len(Path(path).parts)
        if stem in ENTRYPOINT_STEMS or depth == 1:
            s += 2
        kinds = per_file_anchor_kinds.get(path, set())
        if "route" in kinds or "job" in kinds:
            s += 3
        if "table" in kinds:
            s += 2
        s += min(in_degree.get(path, 0), 4)
        b = rec.get("bytes") or 0
        if b < 150:
            s -= 2
        if b > 50_000:
            s -= 1
        return s

    scored = sorted(indexed.items(), key=lambda kv: (-score(kv[0], kv[1]), kv[0]))
    core_cap = MODE_CORE_CAP.get(mode, 80)
    core_paths: set[str] = set()
    for i, (path, _rec) in enumerate(scored):
        if i < core_cap and score(path, _rec) > 0:
            core_paths.add(path)

    file_rows: list[dict] = []
    for path, rec in sorted(indexed.items()):
        file_rows.append({
            "path": path,
            "language": rec["language"],
            "role": rec["role_guess"],
            "bytes": rec.get("bytes"),
            "lines": rec.get("lines"),
            "sha256": rec.get("sha256"),
            "token_estimate": rec.get("token_estimate"),
            "tier": "core" if path in core_paths else "defer",
            "owner_slot": None,
            "read_owner": None,
            "ignored": False,
            "ignore_reason": None,
        })
    for rec in index["ignored"]:
        file_rows.append({
            "path": rec["path"],
            "language": rec["language"],
            "role": rec["role_guess"],
            "bytes": rec.get("bytes"),
            "lines": rec.get("lines"),
            "sha256": rec.get("sha256"),
            "token_estimate": rec.get("token_estimate"),
            "tier": "exclude",
            "owner_slot": None,
            "read_owner": None,
            "ignored": True,
            "ignore_reason": rec.get("ignore_reason"),
        })

    # ---- blueprint facts: deterministic cross-file facts handed to EVERY writer ----
    # Read-isolation is dropped (it caused cross-file guessing); these authoritative,
    # parser-derived facts are what writers cite instead of inferring across files.
    bp_routes, bp_tables, bp_services, bp_jobs = [], [], [], []
    for e in entities.values():
        if e["kind"] == "route":
            bp_routes.append({"route": e["name"], "file": e["path"], "anchor_id": e.get("anchor_id")})
        elif e["kind"] == "table":
            bp_tables.append({"name": e["name"], "file": e["path"], "anchor_id": e.get("anchor_id")})
        elif e["kind"] == "service":
            bp_services.append({"name": e["name"], "file": e["path"]})
        elif e["kind"] == "job":
            bp_jobs.append({"name": e["name"], "file": e["path"], "anchor_id": e.get("anchor_id")})
    bp_env = sorted({a["anchor_text"] for a in anchors if a["kind"] == "env"})
    _noncode_roles = {"documentation", "dependency-manifest", "support", "unreadable"}
    bp_entrypoints = sorted(
        p for p in core_paths
        if (Path(p).stem.lower() in ENTRYPOINT_STEMS or len(Path(p).parts) == 1)
        and indexed[p].get("role_guess") not in _noncode_roles
    )
    bp_hubs = [{"file": p, "in_degree": c} for p, c in in_degree.most_common(15)]
    blueprint_facts = {
        "version": 3,
        "routes": sorted(bp_routes, key=lambda r: (r["file"], r["route"])),
        "tables": sorted(bp_tables, key=lambda t: t["name"]),
        "services": sorted(bp_services, key=lambda s: s["name"]),
        "jobs": sorted(bp_jobs, key=lambda j: j["file"]),
        "env_keys": bp_env,
        "constraints": sorted(bp_constraints_acc, key=lambda c: (c["file"], c["line"])),
        "middleware": sorted(bp_middleware_acc, key=lambda m: (m["file"], m["line"])),
        # planner picks the final blueprint_sources from these signals + role/by_role
        "candidates": {"entrypoints": bp_entrypoints, "import_hubs": bp_hubs},
    }

    return {
        "index": index,
        "file_rows": file_rows,
        "anchors": anchors,
        "entities": list(entities.values()),
        "edges": list(edges.values()),
        "core_paths": core_paths,
        "blueprint_facts": blueprint_facts,
        "profile": profile,
        "mode": mode,
        "est_input_tokens": sum((indexed[p].get("token_estimate") or 0) for p in core_paths),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", nargs="?", default=".")
    parser.add_argument("--out-dir", help="Model staging dir. Default ai-docs/.work/<ts>-v3/model")
    parser.add_argument("--mode", choices=["full", "fast", "update"], default="full")
    parser.add_argument("--profile", choices=["code-first", "history-aware", "ops-heavy"], default="code-first")
    parser.add_argument("--max-bytes", type=int, default=repo_index.DEFAULT_MAX_BYTES)
    parser.add_argument("--max-doc-bytes", type=int, default=120_000)
    parser.add_argument("--include-history", action="store_true")
    parser.add_argument("--include-existing-ai-docs", action="store_true")
    parser.add_argument("--include-lockfiles", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    if not root.exists():
        print(f"Project root does not exist: {root}", file=sys.stderr)
        return 2

    if args.out_dir:
        out_dir = Path(args.out_dir).resolve()
    else:
        run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S-v3")
        out_dir = root / "ai-docs" / ".work" / run_id / "model"
    out_dir.mkdir(parents=True, exist_ok=True)

    model = build_model(root, args.profile, args.mode, args)

    hashes = {}
    hashes["file_index.ndjson"] = write_ndjson(out_dir / "file_index.ndjson", model["file_rows"])
    hashes["anchors.ndjson"] = write_ndjson(out_dir / "anchors.ndjson", model["anchors"])
    hashes["entities.ndjson"] = write_ndjson(out_dir / "entities.ndjson", model["entities"])
    hashes["edges.ndjson"] = write_ndjson(out_dir / "edges.ndjson", model["edges"])

    # Deterministic cross-file facts shared with every writer (not drift-tracked: a view of entities/anchors).
    write_json(out_dir / "blueprint_facts.json", model["blueprint_facts"])

    # LLM-owned model files start as empty stubs; planner/writer/render fill them.
    write_json(out_dir / "flows.json", {"version": 3, "flows": []})
    write_json(out_dir / "claims.ndjson", []) if False else write_ndjson(out_dir / "claims.ndjson", [])
    write_ndjson(out_dir / "open_questions.ndjson", [])

    stats = model["index"]["stats"]
    counts = {
        "files": stats["total_files"],
        "files_core": len(model["core_paths"]),
        "files_defer": stats["indexed_files"] - len(model["core_paths"]),
        "files_exclude": stats["ignored_files"],
        "anchors": len(model["anchors"]),
        "entities": len(model["entities"]),
        "edges": len(model["edges"]),
        "claims": 0,
        "flows": 0,
        "open_questions": 0,
    }
    entity_kinds = dict(sorted(Counter(e["kind"] for e in model["entities"]).items()))

    manifest = {
        "version": 3,
        "kind": "ai-docs-v3-architecture-model",
        "generated_at": now_iso(),
        "root": str(root),
        "commit": _commit(root),
        "profile": args.profile,
        "mode": args.mode,
        "source": model["index"]["source"],
        "budget": {"wall_min": None, "llm_input_tokens": None, "output_tokens": None},
        "spend": {
            "files_indexed": stats["indexed_files"],
            "files_read_by_llm": 0,
            "est_input_tokens": model["est_input_tokens"],
        },
        "counts": counts,
        "entity_kinds": entity_kinds,
        "languages": stats["languages"],
        "model_files": hashes,
        "generators": {"index_v3.py": "deterministic"},
        "degraded": None,
    }
    write_json(out_dir / "manifest.json", manifest)

    bp = model["blueprint_facts"]
    print(json.dumps({
        "out_dir": str(out_dir),
        "counts": counts,
        "entity_kinds": entity_kinds,
        "est_input_tokens": model["est_input_tokens"],
        "blueprint": {
            "routes": len(bp["routes"]), "tables": len(bp["tables"]),
            "env_keys": len(bp["env_keys"]), "services": len(bp["services"]),
            "jobs": len(bp["jobs"]), "constraints": len(bp["constraints"]),
            "middleware": len(bp["middleware"]),
            "entrypoint_candidates": len(bp["candidates"]["entrypoints"]),
        },
    }, ensure_ascii=False))
    return 0


def _commit(root: Path) -> str:
    import subprocess
    try:
        proc = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root,
                              check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        return proc.stdout.strip() or "uncommitted"
    except Exception:
        return "uncommitted"


if __name__ == "__main__":
    raise SystemExit(main())
