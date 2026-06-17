#!/usr/bin/env python3
"""Generate the Pass-1 Planner/Mapper prompt for AI-docs v3 (decision 4 + 8).

The planner does NOT read source bodies. It reads the deterministic model summary
(file index by role, entity inventory, runtime, edge stats) and decides document
boundaries up front — because "an 82KB catalog is a planning failure, not a writing
failure" (decision 8). It emits doc_plan.json: doc identities, skeletons, per-doc
read ownership over core files, token budgets, and a Task Router.
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

import modellib as ml


def summarize(model: dict) -> dict:
    fi = model["file_index"]
    core = [f for f in fi if f.get("tier") == "core"]
    by_role = collections.defaultdict(list)
    for f in core:
        by_role[f["role"]].append(f["path"])
    ent_by_kind = collections.defaultdict(list)
    for e in model["entities"]:
        ent_by_kind[e["kind"]].append(e["name"])
    rt = model["runtime"] or {}
    bp = model.get("blueprint_facts") or {}
    cand = bp.get("candidates", {})
    core_tokens = sum((f.get("token_estimate") or 0) for f in core)
    return {
        "core_count": len(core),
        "core_token_estimate": core_tokens,
        "by_role": {k: sorted(v) for k, v in sorted(by_role.items())},
        "entity_kinds": {k: len(v) for k, v in sorted(ent_by_kind.items())},
        "entities_sample": {k: v[:12] for k, v in sorted(ent_by_kind.items())},
        "services": [s.get("name") for s in rt.get("services", [])],
        "processes": [f"{p.get('name')}({p.get('manager')})" for p in rt.get("processes", [])],
        "env_key_count": len(rt.get("env_keys", [])),
        "edge_count": len(model["edges"]),
        "blueprint": {
            "routes": len(bp.get("routes", [])),
            "tables": len(bp.get("tables", [])),
            "env_keys": len(bp.get("env_keys", [])),
            "services": len(bp.get("services", [])),
            "entrypoints": cand.get("entrypoints", []),
            "import_hubs": cand.get("import_hubs", []),
        },
    }


def render_prompt(model: dict, model_dir: Path, doc_plan_out: str) -> str:
    s = summarize(model)
    lines: list[str] = []
    lines.append(ml.INSTRUCTION_BOUNDARY)
    lines.append("")
    lines.append("# AI-docs v3 — Pass 1: Planner / Mapper")
    lines.append("")
    lines.append("You are the planner for a structured architecture model. You design the")
    lines.append("document set BEFORE any synthesis, so the writers never fall back to a flat")
    lines.append("catalog. You do not read source file bodies in this pass — you reason from the")
    lines.append("deterministic model summary below.")
    lines.append("")
    lines.append("## Deterministic model summary")
    lines.append("")
    lines.append(f"- core files (top-tier, read by writers): {s['core_count']} (~{s['core_token_estimate']:,} input tokens total)")
    lines.append(f"- entity inventory: {json.dumps(s['entity_kinds'], ensure_ascii=False)}")
    lines.append(f"- import edges: {s['edge_count']}")
    lines.append(f"- runtime services: {json.dumps(s['services'], ensure_ascii=False)}")
    lines.append(f"- runtime processes: {json.dumps(s['processes'], ensure_ascii=False)}")
    lines.append(f"- env keys: {s['env_key_count']}")
    lines.append("")
    lines.append("### Blueprint candidates (shared read-context — pick blueprint_sources from these)")
    bpc = s["blueprint"]
    lines.append(f"- deterministic facts ready for writers: {bpc['routes']} routes, "
                 f"{bpc['tables']} tables, {bpc['env_keys']} env keys, {bpc['services']} service classes")
    lines.append(f"- entrypoint files: {json.dumps(bpc['entrypoints'], ensure_ascii=False)}")
    hubs = [f"{h['file']} (imported by {h['in_degree']})" for h in bpc["import_hubs"][:10]]
    lines.append(f"- import hubs (most-imported = likely shared models/utils/config): {json.dumps(hubs, ensure_ascii=False)}")
    lines.append("")
    lines.append("### Entity samples")
    for k, names in s["entities_sample"].items():
        lines.append(f"- {k}: {json.dumps(names, ensure_ascii=False)}")
    lines.append("")
    lines.append("### Core files by role")
    for role, paths in s["by_role"].items():
        lines.append(f"- **{role}** ({len(paths)}):")
        for p in paths:
            lines.append(f"  - {p}")
    lines.append("")
    lines.append("## Your task")
    lines.append("")
    lines.append("1. Decide the project `profile` (webapp | cli | library | service | monorepo).")
    lines.append("2. Design the document set. Keep the default profile identities — index/router,")
    lines.append("   architecture, workflows, data_model, api, operations, testing, troubleshooting,")
    lines.append("   todo — but SPLIT or MERGE by scale. Do NOT force a fixed 12-file layout, and do")
    lines.append("   NOT create one doc per source file.")
    lines.append("3. Assign every core file to exactly ONE owning doc (`owned_sources`). This is the")
    lines.append("   WRITE-ownership boundary: exactly one writer is responsible for documenting (and")
    lines.append("   later re-generating) each file. It is NOT a read boundary — every writer also reads")
    lines.append("   the shared blueprint (step 4). Adaptive split: keep each doc under ~25 owned files")
    lines.append("   AND under ~100k owned input tokens (use the token total above as a guide); set")
    lines.append("   `split_of` and divide a slot when EITHER limit would be exceeded.")
    lines.append("4. Pick `blueprint_sources`: 5-20 cross-file core files that EVERY writer reads as")
    lines.append("   shared read-context — router/mount entrypoints, shared models/schemas, auth, config,")
    lines.append("   DB setup. Choose from the blueprint candidates above. These kill the cross-file")
    lines.append("   guessing that hurt accuracy. NOTE: each blueprint file is still owned by exactly one")
    lines.append("   doc in step 3 (blueprint_sources is a READ overlay, not a separate ownership).")
    lines.append("5. For each doc, write a one-sentence `identity`, a `skeleton` (section list), and")
    lines.append("   `must_have` markers (e.g. `mermaid`, `process_topology`, `task_router`).")
    lines.append("6. Build a `task_router`: common change-intents mapped to the doc + entities a")
    lines.append("   future agent should open first. The router is what makes 00_INDEX.md useful.")
    lines.append("")
    lines.append("## Output")
    lines.append("")
    lines.append(f"Write `{doc_plan_out}` as JSON conforming to this schema:")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps({
        "version": 3,
        "profile": "<webapp|cli|library|service|monorepo>",
        "mode": (model.get("manifest") or {}).get("mode", "full"),
        "blueprint_sources": ["<cross-file core file every writer reads>", "..."],
        "docs": [{
            "doc": "architecture.md",
            "slot": "architecture",
            "identity": "<one sentence>",
            "skeleton": ["<section>", "..."],
            "must_have": ["mermaid", "process_topology"],
            "owned_sources": ["<path>", "..."],
            "token_budget": 6000,
            "max_bytes": 24000,
            "split_of": None,
        }],
        "task_router": [{"intent": "<change intent>", "doc": "api.md", "entities": ["route:GET /x"]}],
    }, indent=2, ensure_ascii=False))
    lines.append("```")
    lines.append("")
    lines.append("Rules:")
    lines.append("- 00_INDEX.md is a thin router (Task Router + pointers into .model/), not a content dump.")
    lines.append("- Every core file appears in exactly one `owned_sources` (write-ownership). List")
    lines.append("  unassigned core files under a catch-all doc rather than dropping them.")
    lines.append("- EVERY file containing routes/endpoints MUST be owned by a doc whose skeleton actually")
    lines.append("  documents those endpoints. If you put an 'endpoints'/'API' section in a doc's")
    lines.append("  skeleton, that doc MUST own the source files behind it — never write a skeleton")
    lines.append("  section whose source files you leave unowned or assign to an engine-internals doc.")
    lines.append("- `blueprint_sources` is a separate READ overlay (5-20 files); each must ALSO appear")
    lines.append("  in exactly one `owned_sources`. Pick the files whose facts the most docs depend on.")
    lines.append("- Prefer fewer, well-bounded docs over many thin ones.")
    lines.append("- Do not invent files that are not in the core list above.")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--out", required=True, help="Where to write the planner prompt (.md)")
    parser.add_argument("--doc-plan-out", default="ai-docs/.work/<run-id>/planning/doc_plan.json",
                        help="Path the planner should write its doc_plan.json to")
    args = parser.parse_args()

    model_dir = Path(args.model_dir).resolve()
    model = ml.load_model(model_dir)
    prompt = render_prompt(model, model_dir, args.doc_plan_out)
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(prompt, encoding="utf-8")
    print(json.dumps({"prompt": str(out), "bytes": len(prompt), "core_files": summarize(model)["core_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
