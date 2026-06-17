#!/usr/bin/env python3
"""Fold per-slot writer fragments back into the model (AI-docs v3).

Writers emit fragments under <run>/model-fragments/<slot>/{claims,anchors,
entities,open_questions}.ndjson + flows.json + draft.md. This merges the data
files into the staged model. draft.md files are left for render_v3.py to assemble.

Merge rules:
  - claims: append (warn on duplicate id)
  - anchors: append llm anchors, skip ids already present
  - entities: same id -> overwrite non-null enriched fields; new id -> add
  - flows: concatenate all flows[]
  - open_questions: append (dedupe by id)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import modellib as ml


def normalize_anchor(a: dict, root: Path, sha_cache: dict) -> tuple[dict | None, str | None]:
    """Fill deterministic fields on an LLM-authored anchor and verify it is real.

    LLMs cannot compute file_sha256, so writers omit it; we fill it here. We also
    require the anchor_text to actually exist in the file (exact substring) — this
    drops hallucinated anchors before they can back a claim (evidence guard)."""
    path = a.get("path")
    if not path:
        return None, "no path"
    p = root / path
    if not p.exists():
        return None, "file missing"
    text = a.get("anchor_text") or ""
    if not text:
        return None, "no anchor_text"
    try:
        body = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, "unreadable"
    if text not in body:
        return None, "anchor_text not found in file (hallucinated)"
    sha = sha_cache.get(path)
    if sha is None:
        sha = ml.sha256_file(p)
        sha_cache[path] = sha
    a["file_sha256"] = sha
    # LLMs can't reliably count line numbers; fill anchor_line from the first
    # line that contains the exact substring (deterministic, same idea as sha).
    if not a.get("anchor_line"):
        a["anchor_line"] = next(
            (i for i, line in enumerate(body.splitlines(), 1) if text in line), 1)
    a.setdefault("policy", "tracked")
    a.setdefault("origin", "llm")
    a.setdefault("kind", "generic")
    return a, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--frag-root", required=True, help="Dir containing per-slot fragment subdirs")
    parser.add_argument("--project-root", default=".", help="Repo root, to verify/normalize llm anchors")
    args = parser.parse_args()

    model_dir = Path(args.model_dir).resolve()
    frag_root = Path(args.frag_root).resolve()
    root = Path(args.project_root).resolve()
    sha_cache: dict[str, str] = {}
    if not frag_root.exists():
        print(json.dumps({"error": "frag root missing", "frag_root": str(frag_root)}))
        return 2

    anchors = ml.load_ndjson(model_dir / "anchors.ndjson")
    anchor_ids = {a["id"] for a in anchors}
    entities = {e["id"]: e for e in ml.load_ndjson(model_dir / "entities.ndjson")}
    claims = ml.load_ndjson(model_dir / "claims.ndjson")
    claim_ids = {c["id"] for c in claims}
    flows = (ml.load_json(model_dir / "flows.json", default={}) or {}).get("flows", [])
    oqs = ml.load_ndjson(model_dir / "open_questions.ndjson")
    oq_ids = {o["id"] for o in oqs}

    report = {"slots": [], "warnings": []}
    for slot_dir in sorted(p for p in frag_root.iterdir() if p.is_dir()):
        slot = slot_dir.name
        added = {"claims": 0, "anchors": 0, "entities_new": 0, "entities_enriched": 0, "flows": 0, "open_questions": 0}

        for c in ml.load_ndjson(slot_dir / "claims.ndjson"):
            if c.get("id") in claim_ids:
                report["warnings"].append(f"duplicate claim id {c['id']} in {slot}")
            claim_ids.add(c.get("id"))
            claims.append(c)
            added["claims"] += 1

        for a in ml.load_ndjson(slot_dir / "anchors.ndjson"):
            if a.get("id") in anchor_ids:
                continue
            norm, err = normalize_anchor(a, root, sha_cache)
            if err:
                report["warnings"].append(f"dropped llm anchor {a.get('id')} in {slot}: {err}")
                continue
            anchors.append(norm)
            anchor_ids.add(norm["id"])
            added["anchors"] += 1

        for e in ml.load_ndjson(slot_dir / "entities.ndjson"):
            eid = e.get("id")
            # Writers often drop the "<kind>:" id prefix when enriching (the prompt lists
            # deterministic entities by bare name), which would duplicate the entity as a
            # new, field-incomplete record. Recover the canonical id so it enriches.
            if eid not in entities:
                kind = e.get("kind")
                if kind and f"{kind}:{eid}" in entities:
                    eid = f"{kind}:{eid}"
                    e["id"] = eid
            if eid in entities:
                base = entities[eid]
                for k, v in e.items():
                    if v is not None and (k not in base or base.get(k) is None or k in ("importance", "summary", "rationale", "title")):
                        base[k] = v
                for s in e.get("support", []):
                    if s not in base.setdefault("support", []):
                        base["support"].append(s)
                added["entities_enriched"] += 1
            else:
                # Genuinely new llm entity: backfill schema-required fields the writer
                # may have omitted so the model gate (id/kind/name/support/origin) passes.
                e.setdefault("name", eid.split(":", 1)[-1])
                e.setdefault("origin", "llm")
                e.setdefault("support", e.get("support") or [])
                entities[eid] = e
                added["entities_new"] += 1

        frag_flows = (ml.load_json(slot_dir / "flows.json", default={}) or {}).get("flows", [])
        for f in frag_flows:
            f.setdefault("kind", "generic")  # writers often encode kind in the id; ensure the field exists
            flows.append(f)
            added["flows"] += 1

        for o in ml.load_ndjson(slot_dir / "open_questions.ndjson"):
            if o.get("id") in oq_ids:
                continue
            oqs.append(o)
            oq_ids.add(o["id"])
            added["open_questions"] += 1

        report["slots"].append({"slot": slot, **added})

    ml.write_ndjson(model_dir / "anchors.ndjson", anchors)
    ml.write_ndjson(model_dir / "entities.ndjson", list(entities.values()))
    ml.write_ndjson(model_dir / "claims.ndjson", claims)
    ml.write_ndjson(model_dir / "open_questions.ndjson", oqs)
    ml.write_json(model_dir / "flows.json", {"version": 3, "flows": flows})

    report["totals"] = {
        "anchors": len(anchors), "entities": len(entities),
        "claims": len(claims), "flows": len(flows), "open_questions": len(oqs),
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
