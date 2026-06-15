#!/usr/bin/env python3
"""Generate Pass-3 evidence-bound Audit prompts for AI-docs v3.

Runs AFTER merge, BEFORE render. One audit prompt per doc that has a draft.

Why this exists: the blind eval showed v3 anchored its *claims* but left *prose*
cross-file assertions unverified (e.g. "admin uses Bearer JWT" when it is actually an
X-ADMIN-KEY header). gate_v3 only checks that a claim's support anchor *resolves*, not
that the anchor actually *backs* the statement, and free-form prose escapes claim
checks entirely. The auditor closes that hole.

The auditor differs from the writer by FORCING per-statement evidence binding: it reads
the cited source line and actively searches for counter-evidence, instead of re-reading
the prose. It then fixes the draft in place (correct contradicted facts; hedge + open a
question for insufficient ones) and records audit_verdicts.ndjson.

Spawn one LLM auditor per generated prompt (like writers). Output goes back into the
same per-slot fragment dir, so render_v3.py picks up the corrected draft.
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

import modellib as ml


RISKY_CLASSES = [
    "auth / authz — who can call what; which header / token / role / scope is required",
    "DB constraints — uniqueness, foreign keys, indexes, primary keys, check constraints",
    "transactions / atomicity / idempotency / locking",
    "scheduling / cron / background-job ownership and triggers",
    "deployment / config / env / secrets handling",
    "money / orders / payments / trading / balances",
    "security guarantees (validation, sanitization, rate limits)",
    "any 'always / never / guarantees / prevents / requires / ensures' wording",
]


def render_audit_prompt(doc: dict, model: dict, model_dir: Path, frag_dir: str,
                        blueprint_facts: dict, blueprint_read: list[str]) -> str:
    frag_key = Path(doc["doc"]).stem
    slot = doc["slot"]
    owned = sorted(doc.get("owned_sources", []))
    claims = [c for c in model.get("claims", []) if c.get("doc") == doc["doc"]]
    bf = blueprint_facts or {}

    L: list[str] = []
    L.append(ml.INSTRUCTION_BOUNDARY)
    L.append("")
    L.append(f"# AI-docs v3 — Pass 3: Evidence-bound Audit for `{doc['doc']}` (slot: {slot})")
    L.append("")
    L.append("You audit ONE document's draft for risky, cross-file claims that may be")
    L.append("plausible-but-wrong. This is NOT a style or completeness review. You verify facts by")
    L.append("BINDING evidence — reading the cited source line and searching for counter-evidence —")
    L.append("never by re-reading the prose. A confident wrong claim (e.g. 'admin uses Bearer JWT'")
    L.append("when it is actually an X-ADMIN-KEY header) is the exact failure you exist to catch.")
    L.append("")
    L.append("## Risky claim classes — audit ONLY these; ignore safe descriptive prose")
    for rc in RISKY_CLASSES:
        L.append(f"- {rc}")
    L.append("")
    L.append("## Authoritative deterministic facts (parser-derived = ground truth)")
    L.append(f"Full data in `{model_dir.name}/blueprint_facts.json`. Headline facts:")
    if bf.get("routes"):
        L.append(f"- routes: {len(bf['routes'])} (exact method/path/file in blueprint_facts.json)")
    if bf.get("constraints"):
        cc = collections.Counter(c["kind"] for c in bf["constraints"])
        L.append(f"- DB constraints by kind: {json.dumps(dict(cc), ensure_ascii=False)} "
                 "— a uniqueness/FK/index claim is TRUE only if it appears in that list.")
    if bf.get("middleware"):
        L.append(f"- middleware/registration: "
                 f"{json.dumps([m['name'] for m in bf['middleware'][:20]], ensure_ascii=False)}")
    if bf.get("env_keys"):
        L.append(f"- env keys: {json.dumps(bf['env_keys'], ensure_ascii=False)}")
    if bf.get("services"):
        L.append(f"- service classes: {json.dumps([s['name'] for s in bf['services'][:30]], ensure_ascii=False)}")
    L.append("")
    L.append("## What to audit")
    L.append("")
    L.append(f"1. Draft to audit: `{frag_dir}/{frag_key}/draft.md` — read it in full.")
    L.append(f"2. Recorded claims for this doc ({len(claims)}) — verify the risky ones:")
    for c in claims[:60]:
        L.append(f"   - [{c.get('class')}] {str(c.get('text',''))[:140]}  "
                 f"support={json.dumps(c.get('support', []), ensure_ascii=False)}")
    if len(claims) > 60:
        L.append(f"   - … +{len(claims) - 60} more in `{model_dir.name}/claims.ndjson` (filter doc=={doc['doc']})")
    L.append("")
    L.append("## Source you may read (to bind evidence + hunt counter-evidence)")
    L.append("Read the cited anchor files, and grep their neighbors. Owned + shared blueprint files:")
    for p in owned:
        L.append(f"- `{p}`")
    for p in blueprint_read:
        L.append(f"- `{p}` (blueprint)")
    L.append("")
    L.append("## Procedure — per risky statement (from the draft prose OR the claims list)")
    L.append("1. Normalize it to a single checkable assertion.")
    L.append("2. BIND evidence: open the cited anchor's file at its line and read it. If there is no")
    L.append("   anchor, grep the owned/blueprint files for the relevant symbol/string.")
    L.append("3. SEARCH counter-evidence — actively try to FALSIFY it. E.g. for an auth claim grep")
    L.append("   `Authorization`, `Bearer`, `X-ADMIN-KEY`, `api_key`, middleware, `Depends`; for a")
    L.append("   uniqueness claim check the constraints list + migrations; for idempotency check for")
    L.append("   locks/unique keys/dedup.")
    L.append("4. Verdict: `supported` | `contradicted` | `insufficient`.")
    L.append("")
    L.append("## Fix the draft IN PLACE")
    L.append(f"Edit `{frag_dir}/{frag_key}/draft.md`:")
    L.append("- `contradicted` → replace with the correct fact from evidence (and cite an anchor).")
    L.append("- `insufficient` → hedge to only what IS supported, and file an open question; do not assert.")
    L.append("- `supported` → leave unchanged.")
    L.append("- Never weaken a correct statement, never invent, and keep all inventory/tables intact.")
    L.append(f"- For `insufficient`, append to `{frag_dir}/{frag_key}/open_questions.ndjson` "
             "(`{id, question, doc, raised_by, support}`, raised_by=\"audit\").")
    L.append("")
    L.append("## Record verdicts")
    L.append(f"Append one line per audited statement to `{frag_dir}/{frag_key}/audit_verdicts.ndjson`:")
    L.append("")
    L.append("```json")
    L.append(json.dumps({
        "id": f"audit:{slot}:<n>",
        "doc": doc["doc"],
        "statement": "<the risky assertion, normalized>",
        "verdict": "supported | contradicted | insufficient",
        "evidence": ["a:<path>:<line>"],
        "counter_evidence": "<what you found, or null>",
        "action": "kept | corrected | hedged",
        "corrected_text": "<new wording, or null>",
        "claim_id": "<claim id if it came from the claims list, else null>",
    }, ensure_ascii=False))
    L.append("```")
    L.append("")
    L.append("- HARD RULE: every `contradicted` or `insufficient` verdict MUST have a matching draft")
    L.append("  edit (action `corrected` or `hedged`). A `contradicted` left as `kept` is a gate fail.")
    L.append("- If you find NO risky statements, write a single line: verdict `supported`, statement")
    L.append("  \"(no risky cross-file assertions found)\", action `kept`.")
    return "\n".join(L) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--doc-plan", required=True, help="Path to doc_plan.json")
    parser.add_argument("--out-dir", required=True, help="Directory for generated audit prompts")
    parser.add_argument("--frag-dir", default="model-fragments",
                        help="Relative dir (under run) where fragments + drafts live")
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
        owned_set = set(doc.get("owned_sources", []))
        blueprint_read = sorted(p for p in blueprint_sources if p not in owned_set)
        prompt = render_audit_prompt(doc, model, model_dir, args.frag_dir,
                                     blueprint_facts, blueprint_read)
        fname = f"audit-{Path(doc['doc']).stem}.md"
        (out_dir / fname).write_text(prompt, encoding="utf-8")
        written.append({"slot": doc["slot"], "doc": doc["doc"], "prompt": fname})

    (out_dir / "audits-index.json").write_text(
        json.dumps({"version": 3, "audits": written}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps({"out_dir": str(out_dir), "audits": written}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
