#!/usr/bin/env python3
"""Render the model into markdown views (AI-docs v3, decision 1 + 4).

Markdown is a 2nd-class, regeneratable view of .model/. This renderer:
  - assembles each doc from its writer draft (model-fragments/<slot>/draft.md) when
    present (the synthesis path), or emits a deterministic baseline view when not,
  - always emits 00_INDEX.md as a thin Task Router pointing into .model/,
  - emits render_state.json linking each view to the model hashes it came from
    (the substrate for layer-2 drift).

Tables/inventories are deterministic stdlib templates; rationale/mermaid/router come
from the model (writer-authored). No external template engine (stdlib only).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from collections import defaultdict
from pathlib import Path

import modellib as ml


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def node_id(path: str) -> str:
    return "n_" + re.sub(r"[^a-zA-Z0-9]", "_", path)[-40:]


def import_graph_mermaid(edges: list[dict], owned: set[str], limit: int = 30) -> str:
    rel = [e for e in edges if e.get("kind") == "import"
           and (e["src"].removeprefix("file:") in owned or e["dst"].removeprefix("file:") in owned)]
    rel = rel[:limit]
    if not rel:
        return ""
    lines = ["```mermaid", "graph LR"]
    seen = set()
    for e in rel:
        s = e["src"].removeprefix("file:")
        d = e["dst"].removeprefix("file:")
        for p in (s, d):
            nid = node_id(p)
            if nid not in seen:
                seen.add(nid)
                lines.append(f'  {nid}["{Path(p).name}"]')
        lines.append(f"  {node_id(s)} --> {node_id(d)}")
    lines.append("```")
    return "\n".join(lines)


def flow_mermaid(flow: dict) -> str:
    lines = ["```mermaid", "graph TD"]
    steps = flow.get("steps", [])
    for i, st in enumerate(steps):
        ent = st.get("entity", f"step{i}")
        nid = node_id(ent + str(i))
        label = (st.get("note") or ent).replace('"', "'")
        lines.append(f'  {nid}["{label}"]')
        if i > 0:
            prev = node_id((steps[i-1].get("entity", f"step{i-1}")) + str(i-1))
            lines.append(f"  {prev} --> {nid}")
    lines.append("```")
    return "\n".join(lines)


def entity_tables(entities: list[dict], owned: set[str]) -> str:
    ents = [e for e in entities if e.get("path") in owned]
    by_kind = defaultdict(list)
    for e in ents:
        by_kind[e["kind"]].append(e)
    out = []
    for kind in sorted(by_kind):
        out.append(f"### {kind.capitalize()} ({len(by_kind[kind])})")
        out.append("")
        out.append("| name | file | summary |")
        out.append("|---|---|---|")
        for e in by_kind[kind]:
            summ = (e.get("summary") or "").replace("|", "\\|")
            out.append(f"| `{e['name']}` | `{e.get('path','')}` | {summ} |")
        out.append("")
    return "\n".join(out)


def render_doc(doc: dict, model: dict, frag_root: Path | None) -> str:
    slot = doc["slot"]
    owned = set(doc.get("owned_sources", []))

    # synthesis path: writer draft present (fragment dir keyed by doc, not slot)
    draft = None
    if frag_root:
        cand = frag_root / Path(doc["doc"]).stem / "draft.md"
        if cand.exists():
            draft = cand.read_text(encoding="utf-8", errors="replace")

    L: list[str] = []
    L.append(f"# {doc.get('doc', slot)}")
    L.append("")
    L.append(f"> {doc.get('identity', '')}")
    L.append("")

    if draft:
        L.append(draft.strip())
        L.append("")
    else:
        # deterministic baseline view
        L.append("_Baseline view generated from the model. Synthesis (rationale, flows) is")
        L.append("added when a writer fills this slot; until then this is structural inventory only._")
        L.append("")
        mer = import_graph_mermaid(model["edges"], owned)
        if mer and "mermaid" in doc.get("must_have", []):
            L.append("## Module import graph")
            L.append("")
            L.append(mer)
            L.append("")
        tbls = entity_tables(model["entities"], owned)
        if tbls.strip():
            L.append("## Entities")
            L.append("")
            L.append(tbls)

    # claims as a fallback "Key facts" list ONLY for baseline views; a writer draft
    # already weaves its claims into prose, so re-listing them would inflate the
    # table/list ratio toward the catalog shape we reject.
    if not draft:
        claims = [c for c in model["claims"] if c.get("doc") == doc.get("doc")]
        if claims:
            L.append("## Key facts")
            L.append("")
            for c in claims:
                L.append(f"- {c['text']}")
            L.append("")

    # baseline flows. Normal docs: only flows whose dep_files intersect their owned
    # sources. Cross-cutting docs (owned 0, e.g. workflows) that require a diagram:
    # render the global flow set, since their job is to trace flows across the system.
    if not draft:
        all_flows = (model["flows"] or {}).get("flows", [])
        if owned:
            chosen = [f for f in all_flows if set(f.get("dep_files", [])) & owned]
        elif "mermaid" in doc.get("must_have", []):
            chosen = all_flows[:8]
        else:
            chosen = []
        for f in chosen:
            L.append(f"## Flow: {f.get('title', f['id'])}")
            L.append("")
            L.append(flow_mermaid(f))
            L.append("")

    # model open_questions are the source of truth; skip if the writer draft already
    # rendered its own Open questions section (avoids a duplicate section).
    oqs = [o for o in model["open_questions"] if o.get("doc") == doc.get("doc")]
    draft_has_oq = bool(draft and re.search(r"^#+\s*open questions", draft, re.IGNORECASE | re.MULTILINE))
    if oqs and not draft_has_oq:
        L.append("## Open questions")
        L.append("")
        for o in oqs:
            L.append(f"- {o['question']}")
        L.append("")

    return "\n".join(L).rstrip() + "\n"


def render_index(doc_plan: dict, model: dict) -> str:
    L: list[str] = []
    L.append("# 00_INDEX — AI entrypoint (Task Router)")
    L.append("")
    L.append(f"> Profile: **{doc_plan.get('profile', 'auto')}**. This is a thin router. The")
    L.append("> source of truth is the architecture model in `.model/` (machine-readable).")
    L.append("> Markdown docs are regeneratable views.")
    L.append("")
    L.append("## Task Router")
    L.append("")
    L.append("| If you want to… | Open this doc | Start from entities |")
    L.append("|---|---|---|")
    for r in doc_plan.get("task_router", []):
        ents = ", ".join(f"`{e}`" for e in r.get("entities", [])) or "—"
        L.append(f"| {r.get('intent','')} | `{r.get('doc','')}` | {ents} |")
    L.append("")
    L.append("## Documents")
    L.append("")
    L.append("| doc | what it covers |")
    L.append("|---|---|")
    for d in doc_plan.get("docs", []):
        L.append(f"| `{d['doc']}` | {d.get('identity','')} |")
    L.append("")
    L.append("## Model files (`.model/`)")
    L.append("")
    counts = (model.get("manifest") or {}).get("counts", {})
    L.append(f"- `entities.ndjson` — {counts.get('entities','?')} architectural units")
    L.append(f"- `edges.ndjson` — {counts.get('edges','?')} relationships")
    L.append(f"- `claims.ndjson` — {counts.get('claims','?')} evidence-backed claims")
    L.append(f"- `flows.json` — {counts.get('flows','?')} flows")
    L.append(f"- `anchors.ndjson` — {counts.get('anchors','?')} source anchors (drift substrate)")
    L.append(f"- `runtime.json` — process/service/env topology")
    L.append("")
    return "\n".join(L) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--doc-plan", required=True)
    parser.add_argument("--out-dir", required=True, help="Where to write rendered markdown")
    parser.add_argument("--frag-root", help="Writer fragment root (for draft assembly)")
    args = parser.parse_args()

    model_dir = Path(args.model_dir).resolve()
    model = ml.load_model(model_dir)
    doc_plan = ml.load_json(Path(args.doc_plan).resolve(), default={})
    if not doc_plan.get("docs"):
        print(json.dumps({"error": "doc_plan has no docs"}))
        return 2
    frag_root = Path(args.frag_root).resolve() if args.frag_root else None

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    render_state = {"version": 3, "rendered_at": now_iso(), "docs": []}
    model_hashes = {
        "claims_sha256": ml.sha256_file(model_dir / "claims.ndjson") if (model_dir / "claims.ndjson").exists() else None,
        "entities_sha256": ml.sha256_file(model_dir / "entities.ndjson") if (model_dir / "entities.ndjson").exists() else None,
        "edges_sha256": ml.sha256_file(model_dir / "edges.ndjson") if (model_dir / "edges.ndjson").exists() else None,
        "flows_sha256": ml.sha256_file(model_dir / "flows.json") if (model_dir / "flows.json").exists() else None,
    }

    written = []
    # index
    idx = render_index(doc_plan, model)
    (out_dir / "00_INDEX.md").write_text(idx, encoding="utf-8")
    render_state["docs"].append({"doc": "00_INDEX.md", "rendered_at": now_iso(),
                                 "doc_sha256": ml.sha256_text(idx), "model_inputs": model_hashes, "gate": None})
    written.append("00_INDEX.md")

    for doc in doc_plan["docs"]:
        if doc["doc"] == "00_INDEX.md":
            continue  # the router is authored by render_index, not as a baseline doc
        text = render_doc(doc, model, frag_root)
        path = out_dir / doc["doc"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        render_state["docs"].append({"doc": doc["doc"], "rendered_at": now_iso(),
                                     "doc_sha256": ml.sha256_text(text), "model_inputs": model_hashes, "gate": None})
        written.append(doc["doc"])

    ml.write_json(model_dir / "render_state.json", render_state)
    print(json.dumps({"out_dir": str(out_dir), "written": written,
                      "mode": "assembled" if frag_root else "baseline"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
