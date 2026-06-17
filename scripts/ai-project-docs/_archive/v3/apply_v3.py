#!/usr/bin/env python3
"""Finalize + apply an AI-docs v3 run.

Finalize: recompute manifest counts and per-file hashes from the final staged model,
and fill budget from ai-project.yaml. Apply (only with --apply): copy the staged
model to ai-docs/.model/ and staged markdown views to ai-docs/. Refuses to overwrite
existing non-v3 docs unless --force-apply.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
from pathlib import Path

import modellib as ml


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def parse_budget(config_path: Path, mode: str) -> dict:
    if not config_path.exists():
        return {"wall_min": None, "llm_input_tokens": None, "output_tokens": None}
    text = config_path.read_text(encoding="utf-8")
    m = re.search(rf"^\s*{mode}:\s*\{{([^}}]*)\}}", text, re.MULTILINE)
    out = {"wall_min": None, "llm_input_tokens": None, "output_tokens": None}
    if m:
        body = m.group(1)
        for key, dst in (("wall_min", "wall_min"), ("llm_input_tokens", "llm_input_tokens"), ("output_tokens", "output_tokens")):
            km = re.search(rf"{key}:\s*(\d+)", body)
            if km:
                out[dst] = int(km.group(1))
    return out


def finalize(model_dir: Path, config_path: Path) -> dict:
    manifest = ml.load_json(model_dir / "manifest.json", default={}) or {}
    file_index = ml.load_ndjson(model_dir / "file_index.ndjson")
    anchors = ml.load_ndjson(model_dir / "anchors.ndjson")
    entities = ml.load_ndjson(model_dir / "entities.ndjson")
    edges = ml.load_ndjson(model_dir / "edges.ndjson")
    claims = ml.load_ndjson(model_dir / "claims.ndjson")
    oqs = ml.load_ndjson(model_dir / "open_questions.ndjson")
    flows = (ml.load_json(model_dir / "flows.json", default={}) or {}).get("flows", [])

    tier = {"core": 0, "defer": 0, "exclude": 0}
    for f in file_index:
        tier[f.get("tier", "defer")] = tier.get(f.get("tier", "defer"), 0) + 1

    manifest["counts"] = {
        "files": len(file_index),
        "files_core": tier["core"], "files_defer": tier["defer"], "files_exclude": tier["exclude"],
        "anchors": len(anchors), "entities": len(entities), "edges": len(edges),
        "claims": len(claims), "flows": len(flows), "open_questions": len(oqs),
    }
    hashes = {}
    for name in ("file_index.ndjson", "anchors.ndjson", "entities.ndjson", "edges.ndjson",
                 "claims.ndjson", "flows.json", "runtime.json", "doc_plan.json"):
        p = model_dir / name
        if p.exists():
            hashes[name] = ml.sha256_file(p)
    manifest["model_files"] = hashes
    manifest["budget"] = parse_budget(config_path, manifest.get("mode", "full"))
    manifest["finalized_at"] = now_iso()
    ml.write_json(model_dir / "manifest.json", manifest)
    return manifest


def detect_existing_generation(ai_docs: Path) -> str | None:
    cfg = ai_docs / "ai-project.yaml"
    if cfg.exists():
        txt = cfg.read_text(encoding="utf-8")
        m = re.search(r"version:\s*(\d+)", txt)
        if m:
            return f"v{m.group(1)}"
    if (ai_docs / "00_INDEX.md").exists() or any(ai_docs.glob("0*.md")):
        return "v1-or-legacy"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", nargs="?", default=".")
    parser.add_argument("--staging-model", required=True)
    parser.add_argument("--staging-render", required=True)
    parser.add_argument("--apply", action="store_true", help="Actually write to ai-docs/ (default: finalize only)")
    parser.add_argument("--force-apply", action="store_true", help="Overwrite existing non-v3 docs")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    ai_docs = root / "ai-docs"
    config_path = ai_docs / "ai-project.yaml"
    model_dir = Path(args.staging_model).resolve()
    render_dir = Path(args.staging_render).resolve()

    manifest = finalize(model_dir, config_path)

    if not args.apply:
        print(json.dumps({"finalized": True, "applied": False, "counts": manifest["counts"]}, ensure_ascii=False))
        return 0

    gen = detect_existing_generation(ai_docs)
    if gen and gen not in ("v3",) and not args.force_apply:
        print(json.dumps({"error": "refusing to overwrite existing docs", "detected": gen,
                          "hint": "use --force-apply after migration review"}, ensure_ascii=False))
        return 3

    final_model = ai_docs / ".model"
    final_model.mkdir(parents=True, exist_ok=True)
    for p in model_dir.iterdir():
        if p.is_file():
            shutil.copy2(p, final_model / p.name)
    written = []
    for p in render_dir.rglob("*.md"):
        rel = p.relative_to(render_dir)
        dst = ai_docs / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)
        written.append(rel.as_posix())

    print(json.dumps({"finalized": True, "applied": True, "model_dir": str(final_model),
                      "docs": written, "counts": manifest["counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
