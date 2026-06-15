#!/usr/bin/env python3
"""Generate Pass-2 slot Writer prompts for AI-docs v3 (decision 1 + 4 + 5).

One prompt per doc in doc_plan.json. Each writer:
  - reads ONLY its owned_sources directly (read ownership = cost discipline),
  - synthesizes the slot per its skeleton (v1-grade synthesis, the thing v2 lost),
  - records every non-trivial claim WITH a support anchor AS IT WRITES
    (evidence-aware synthesis, not post-hoc) into a per-slot fragment,
  - builds Mermaid/flows with dep_files so drift can flag them,
  - files open questions for gaps; never invents.

Writers write fragments under <run-dir>/model-fragments/<slot>/, which
merge_fragments_v3.py folds back into the model. This avoids concurrent writers
racing on the same model files.
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

import modellib as ml


def file_line_map(file_index: list[dict]) -> dict[str, list]:
    return {f["path"]: f.get("lines") for f in file_index}


def render_prompt(doc: dict, model: dict, model_dir: Path, frag_dir: str,
                  blueprint_sources: list[str], blueprint_facts: dict) -> str:
    slot = doc["slot"]
    frag_key = Path(doc["doc"]).stem  # fragment dir keyed by doc, not slot (slots repeat)
    owned = doc.get("owned_sources", [])
    owned_set = set(owned)
    lines_map = file_line_map(model["file_index"])

    ents = [e for e in model["entities"] if e.get("path") in owned_set]
    ent_by_kind = collections.defaultdict(list)
    for e in ents:
        ent_by_kind[e["kind"]].append(e)
    edges = [e for e in model["edges"]
             if e.get("src", "").removeprefix("file:") in owned_set
             or e.get("dst", "").removeprefix("file:") in owned_set]
    anchor_counts = collections.Counter(
        a["kind"] for a in model["anchors"] if a.get("path") in owned_set
    )

    L: list[str] = []
    L.append(ml.INSTRUCTION_BOUNDARY)
    L.append("")
    L.append(f"# AI-docs v3 — Pass 2: Writer for `{doc['doc']}` (slot: {slot})")
    L.append("")
    L.append(f"**Doc identity**: {doc.get('identity', '(none given)')}")
    L.append(f"**Token budget**: ~{doc.get('token_budget', 6000)} | **Max bytes**: {doc.get('max_bytes', 24000)}")
    L.append(f"**Must have**: {json.dumps(doc.get('must_have', []), ensure_ascii=False)}")
    L.append("")
    L.append("## Skeleton (write these sections, in order)")
    for sec in doc.get("skeleton", []):
        L.append(f"- {sec}")
    L.append("")
    L.append("## Your owned sources (write-ownership) — read these in full")
    L.append("")
    L.append("You are responsible for documenting these files. Read every one in full. This is a")
    L.append("WRITE boundary (you own the prose + claims about them), NOT a read cage — you may and")
    L.append("should also read the shared blueprint below for cross-file accuracy.")
    L.append("")
    for p in sorted(owned):
        rng = lines_map.get(p)
        rng_s = f" (lines {rng[0]}-{rng[1]})" if rng else ""
        L.append(f"- `{p}`{rng_s}")
    L.append("")
    bp_read = [p for p in (blueprint_sources or []) if p not in owned_set]
    if bp_read:
        L.append("## Shared blueprint — read these too (read-only context)")
        L.append("")
        L.append("These cross-file core files are read by ALL writers. Read them to get auth, routing,")
        L.append("shared models, config, and DB setup RIGHT — never guess these from your owned files.")
        L.append("Another doc owns the prose about them; when your owned code depends on one, list it in")
        L.append("`dep_files` and cite its anchor.")
        L.append("")
        for p in sorted(bp_read):
            rng = lines_map.get(p)
            rng_s = f" (lines {rng[0]}-{rng[1]})" if rng else ""
            L.append(f"- `{p}`{rng_s}")
        L.append("")
    bf = blueprint_facts or {}
    if bf.get("routes") or bf.get("tables") or bf.get("env_keys") or bf.get("services"):
        L.append("## Deterministic cross-file facts (authoritative — never contradict these)")
        L.append("")
        L.append("Parser-extracted, repo-wide. When you state a route / table / env / service fact it")
        L.append(f"MUST match this. Full data in `{model_dir.name}/blueprint_facts.json`. If your prose")
        L.append("would contradict these, your prose is wrong — fix it.")
        L.append("")
        routes = bf.get("routes", [])
        if routes:
            L.append(f"**Routes** ({len(routes)}):")
            for r in routes[:40]:
                L.append(f"- `{r['route']}` — {r['file']}")
            if len(routes) > 40:
                L.append(f"- … +{len(routes) - 40} more (see blueprint_facts.json)")
            L.append("")
        if bf.get("tables"):
            L.append(f"**Tables** ({len(bf['tables'])}): "
                     f"{json.dumps([t['name'] for t in bf['tables']], ensure_ascii=False)}")
            L.append("")
        if bf.get("env_keys"):
            L.append(f"**Env keys** ({len(bf['env_keys'])}): "
                     f"{json.dumps(bf['env_keys'], ensure_ascii=False)}")
            L.append("")
        if bf.get("services"):
            L.append(f"**Service classes** ({len(bf['services'])}): "
                     f"{json.dumps([s['name'] for s in bf['services']], ensure_ascii=False)}")
            L.append("")
        if bf.get("constraints"):
            cc = collections.Counter(c["kind"] for c in bf["constraints"])
            L.append(f"**DB constraints** ({len(bf['constraints'])}) by kind: "
                     f"{json.dumps(dict(cc), ensure_ascii=False)} — full file:line list in blueprint_facts.json.")
            L.append("  Do NOT assert a uniqueness / FK / index guarantee unless it appears in that list.")
            L.append("")
        if bf.get("middleware"):
            mw = [f"{m['name']} ({m['file']})" for m in bf["middleware"][:20]]
            L.append(f"**Middleware / registration order** ({len(bf['middleware'])}): "
                     f"{json.dumps(mw, ensure_ascii=False)}")
            L.append("")
    L.append("## Deterministic anchors & entities for your sources")
    L.append("")
    L.append(f"- Read `{model_dir.name}/anchors.ndjson` and filter to your owned paths for stable")
    L.append("  anchor ids to cite as claim support. Anchor kinds present in your sources:")
    L.append(f"  {json.dumps(dict(anchor_counts), ensure_ascii=False)}")
    L.append("- Deterministic entities in your sources (enrich these with importance/summary/rationale):")
    for kind, items in sorted(ent_by_kind.items()):
        names = [e["name"] for e in items][:20]
        L.append(f"  - {kind}: {json.dumps(names, ensure_ascii=False)}")
    if edges:
        L.append(f"- Import edges touching your sources: {len(edges)} (see edges.ndjson).")
    L.append("")
    L.append("## Evidence-aware synthesis (the core rule)")
    L.append("")
    L.append("As you write each non-trivial claim, record it AT THE SAME TIME. Do not write prose")
    L.append("first and add evidence later. For every claim append a line to")
    L.append(f"`{frag_dir}/{frag_key}/claims.ndjson`:")
    L.append("")
    L.append("```json")
    L.append(json.dumps({
        "id": f"{slot}.<topic>",
        "text": "<the human-readable claim — never contains the id>",
        "class": "direct | inference | diagram | operational",
        "doc": doc["doc"],
        "support": ["a:<path>:<line>:<kind>"],
        "dep_files": ["<path>"],
        "confidence": "high | med | low",
        "rendered": True,
    }, ensure_ascii=False))
    L.append("```")
    L.append("")
    L.append("- `direct`: one anchor on one file. `inference`: cross-file; list every file in dep_files.")
    L.append("- `diagram`: backs a Mermaid edge; dep_files = files the diagram asserts.")
    L.append("- `operational`: from runtime.json (compose/process/env/port).")
    L.append("- HARD RULE: no claim without at least one support anchor. If you cannot anchor it,")
    L.append("  it is an open question, not a claim.")
    L.append("- If you read a line that has no deterministic anchor but you need to cite it, append a")
    L.append(f"  new anchor to `{frag_dir}/{frag_key}/anchors.ndjson` with `origin:\"llm\"` and an EXACT")
    L.append("  substring from that line as `anchor_text`.")
    L.append("- RISKY CLAIMS — auth/authz, DB constraints & uniqueness, transactions, idempotency,")
    L.append("  scheduling, money/orders, security, and any 'always/never/guarantees/prevents/requires'")
    L.append("  wording — will be AUDITED against source after you write. State them ONLY from the")
    L.append("  deterministic facts above or an anchor you actually read in your owned/blueprint files;")
    L.append("  never infer them from a neighboring file's name or convention. If unsure, file an open")
    L.append("  question instead. A confident wrong claim here is the single worst failure mode.")
    L.append("")
    if "mermaid" in doc.get("must_have", []):
        L.append("## Flows & diagrams")
        L.append("")
        L.append(f"Build at least one Mermaid diagram for the main flow(s). Record each flow in")
        L.append(f"`{frag_dir}/{frag_key}/flows.json` (a JSON object `{{\"flows\": [...]}}`):")
        L.append("")
        L.append("```json")
        L.append(json.dumps({
            "flows": [{
                "id": "flow:request:<slug>",
                "kind": "request | data | scheduler | worker | startup",
                "title": "<title>",
                "steps": [{"entity": "<entity id>", "note": "<what happens>"}],
                "support": ["a:<path>:<line>:<kind>"],
                "dep_files": ["<path>"],
                "origin": "llm",
            }]
        }, ensure_ascii=False))
        L.append("```")
        L.append("")
    L.append("## Entity enrichment & open questions")
    L.append("")
    L.append(f"- Append enriched entities (same id, with importance/summary/rationale filled) to")
    L.append(f"  `{frag_dir}/{frag_key}/entities.ndjson`. You may also add module/service entities that")
    L.append("  require judgment — each MUST carry a support anchor.")
    L.append(f"- File gaps in `{frag_dir}/{frag_key}/open_questions.ndjson` "
             "(`{id, question, doc, raised_by, support}`). Never fill a gap with invention.")
    L.append("")
    L.append("## Markdown draft")
    L.append("")
    L.append(f"Write the human-readable view to `{frag_dir}/{frag_key}/draft.md`. Balance synthesis")
    L.append("and inventory — AI agents need BOTH:")
    L.append("- Lead each major section with synthesis (how things connect, *why*/*how*), THEN give the")
    L.append("  concrete inventory. Synthesis-only is the v1 gap; inventory-only was the v2 catalog")
    L.append("  failure. Do both, in that order.")
    L.append("- KEEP detailed tables — full route tables (method/path/handler/auth), table-column")
    L.append("  schemas, env/config lists, job schedules. These are high-value for AI agents; do NOT")
    L.append("  thin them out to avoid 'cataloging'. Each table just needs a short prose lead.")
    L.append("- NEVER print claim ids (e.g. `architecture.001`) in the body text.")
    L.append("- Do NOT add an 'Open questions' section to draft.md — record them only in")
    L.append("  open_questions.ndjson; the renderer appends that section from the model.")
    L.append("- Include the required Mermaid diagram(s).")
    L.append("- Stay within max_bytes. If you can't, that's a planning split — file an open question.")
    return "\n".join(L) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--doc-plan", required=True, help="Path to doc_plan.json")
    parser.add_argument("--out-dir", required=True, help="Directory for generated writer prompts")
    parser.add_argument("--frag-dir", default="model-fragments",
                        help="Relative dir (under run) where writers write fragments")
    args = parser.parse_args()

    model_dir = Path(args.model_dir).resolve()
    model = ml.load_model(model_dir)
    doc_plan = ml.load_json(Path(args.doc_plan).resolve(), default={})
    if not doc_plan.get("docs"):
        print(json.dumps({"error": "doc_plan has no docs", "doc_plan": args.doc_plan}))
        return 2

    blueprint_sources = doc_plan.get("blueprint_sources", [])
    blueprint_facts = model.get("blueprint_facts") or {}

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for doc in doc_plan["docs"]:
        prompt = render_prompt(doc, model, model_dir, args.frag_dir, blueprint_sources, blueprint_facts)
        fname = f"writer-{Path(doc['doc']).stem}.md"
        (out_dir / fname).write_text(prompt, encoding="utf-8")
        written.append({"slot": doc["slot"], "doc": doc["doc"],
                        "owned": len(doc.get("owned_sources", [])), "prompt": fname})

    (out_dir / "writers-index.json").write_text(
        json.dumps({"version": 3, "writers": written}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps({"out_dir": str(out_dir), "writers": written}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
