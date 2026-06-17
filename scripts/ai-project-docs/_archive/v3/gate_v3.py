#!/usr/bin/env python3
"""AI-docs v3 gate: model schema validator + deterministic catalog linter (decision 7).

Two independent gates, both deterministic (no LLM):

1. MODEL SCHEMA (always): validates .model/* structure and enforces the invariants —
   most importantly Invariant 2 (no claim/LLM-entity without a live support anchor) and
   dangling-reference checks (every support id resolves to a real anchor).

2. CATALOG LINTER (when --docs-dir given): rejects the v2 failure shape on rendered
   markdown — table/list ratio over threshold, claim ids leaking into body text,
   missing required diagram/router, and oversize docs.

Exit code 1 on any FAIL finding, 0 otherwise. --json prints the full report.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import modellib as ml


CATALOG_RATIO_THRESHOLD = 0.45
CLAIM_ID_RE = re.compile(r"\b[a-z][a-z_]*\.[a-z0-9_]+(?:\.\d+)?\b")


# ---------------- model schema validation ----------------

def validate_model(model_dir: Path) -> list[dict]:
    findings: list[dict] = []

    def fail(msg, **kw):
        findings.append({"severity": "fail", "gate": "model", "issue": msg, **kw})

    def warn(msg, **kw):
        findings.append({"severity": "warning", "gate": "model", "issue": msg, **kw})

    manifest = ml.load_json(model_dir / "manifest.json", default=None)
    if not manifest:
        fail("manifest.json missing or empty")
    else:
        for k in ("version", "kind", "counts"):
            if k not in manifest:
                fail(f"manifest missing field: {k}")

    anchors = ml.load_ndjson(model_dir / "anchors.ndjson")
    anchor_ids = set()
    for a in anchors:
        for k in ("id", "path", "anchor_text", "anchor_line", "file_sha256", "kind", "policy", "origin"):
            if k not in a:
                fail("anchor missing field", field=k, anchor=a.get("id"))
        anchor_ids.add(a.get("id"))

    file_index = ml.load_ndjson(model_dir / "file_index.ndjson")
    for f in file_index:
        for k in ("path", "tier", "role"):
            if k not in f:
                fail("file_index record missing field", field=k, path=f.get("path"))
        if f.get("tier") not in ("core", "defer", "exclude"):
            fail("invalid tier", path=f.get("path"), tier=f.get("tier"))

    # entities: Invariant 2 — every entity needs support; llm entities must resolve anchors
    entities = ml.load_ndjson(model_dir / "entities.ndjson")
    entity_ids = set()
    for e in entities:
        entity_ids.add(e.get("id"))
        for k in ("id", "kind", "name", "support", "origin"):
            if k not in e:
                fail("entity missing field", field=k, entity=e.get("id"))
        sup = e.get("support") or []
        if not sup:
            fail("entity has no support anchor (Invariant 2)", entity=e.get("id"))
        for s in sup:
            if s not in anchor_ids:
                fail("entity support anchor does not resolve", entity=e.get("id"), anchor=s)

    edges = ml.load_ndjson(model_dir / "edges.ndjson")
    for e in edges:
        for k in ("id", "kind", "src", "dst", "origin"):
            if k not in e:
                fail("edge missing field", field=k, edge=e.get("id"))
        # semantic (llm) edges must carry support; import edges are deterministic
        if e.get("origin") == "llm" and not (e.get("support") or []):
            fail("llm edge has no support anchor (Invariant 2)", edge=e.get("id"))

    # claims: Invariant 2 + class + no id-in-text
    claims = ml.load_ndjson(model_dir / "claims.ndjson")
    for c in claims:
        for k in ("id", "text", "class", "doc", "support"):
            if k not in c:
                fail("claim missing field", field=k, claim=c.get("id"))
        if c.get("class") not in ("direct", "inference", "diagram", "operational"):
            fail("invalid claim class", claim=c.get("id"), cls=c.get("class"))
        sup = c.get("support") or []
        if not sup:
            fail("claim has no support anchor (Invariant 2)", claim=c.get("id"))
        for s in sup:
            if s not in anchor_ids:
                fail("claim support anchor does not resolve", claim=c.get("id"), anchor=s)
        if c.get("id") and c.get("text") and c["id"] in c["text"]:
            fail("claim id leaks into claim text", claim=c.get("id"))

    flows = (ml.load_json(model_dir / "flows.json", default={}) or {}).get("flows", [])
    for fl in flows:
        for k in ("id", "kind", "steps"):
            if k not in fl:
                fail("flow missing field", field=k, flow=fl.get("id"))
        for st in fl.get("steps", []):
            ent = st.get("entity")
            if ent and ent not in entity_ids:
                warn("flow step references unknown entity", flow=fl.get("id"), entity=ent)

    # composed views (Pass-4 compose): structural fields + support must resolve to a
    # real anchor (Invariant 2 spirit — a cross-cutting view is still evidence-bound).
    composed = ml.load_ndjson(model_dir / "composed_views.ndjson")
    for v in composed:
        for k in ("id", "topic", "body_md", "support", "doc"):
            if k not in v:
                fail("composed view missing field", field=k, view=v.get("id"))
        sup = v.get("support") or []
        if not sup:
            fail("composed view has no support anchor (Invariant 2)", view=v.get("id"))
        for s in sup:
            if s not in anchor_ids:
                fail("composed view support anchor does not resolve", view=v.get("id"), anchor=s)

    return findings


# ---------------- catalog linter (markdown) ----------------

def classify_lines(text: str) -> dict:
    in_fence = False
    fence_lang = ""
    counts = {"table": 0, "list": 0, "heading": 0, "prose": 0, "code": 0, "mermaid": 0, "blank": 0}
    chars = {"table": 0, "list": 0, "prose": 0}
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        fence = re.match(r"^```(\w*)", stripped)
        if fence:
            if not in_fence:
                in_fence = True
                fence_lang = fence.group(1)
            else:
                in_fence = False
                fence_lang = ""
            continue
        if in_fence:
            counts["mermaid" if fence_lang == "mermaid" else "code"] += 1
            continue
        if not stripped:
            counts["blank"] += 1
        elif stripped.startswith("#"):
            counts["heading"] += 1
        elif stripped.startswith("|") or re.match(r"^\|?[-:\s|]+\|", stripped):
            counts["table"] += 1
            chars["table"] += len(stripped)
        elif re.match(r"^([-*+]\s|\d+[.)]\s)", stripped):
            counts["list"] += 1
            chars["list"] += len(stripped)
        else:
            counts["prose"] += 1
            chars["prose"] += len(stripped)
    counts["chars"] = chars
    return counts


def lint_doc(path: Path, rel: str, claim_ids: set[str], max_bytes: int | None,
             must_have: list[str] | None = None) -> list[dict]:
    findings: list[dict] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    size = len(text.encode("utf-8"))

    def fail(msg, **kw):
        findings.append({"severity": "fail", "gate": "catalog", "doc": rel, "issue": msg, **kw})

    def warn(msg, **kw):
        findings.append({"severity": "warning", "gate": "catalog", "doc": rel, "issue": msg, **kw})

    name = Path(rel).name.lower()
    counts = classify_lines(text)
    structural = counts["table"] + counts["list"] + counts["prose"]
    # 00_INDEX is intentionally a router (tables + links), so it is exempt from the ratio gate.
    if structural >= 12 and name != "00_index.md":
        # Char-based, not line-based: a long prose paragraph is one line of many chars,
        # while a table is many lines of few chars each. Line-based counting under-weights
        # narrative and false-flags well-explained architecture/workflow docs as catalogs.
        cc = counts["chars"]
        cstruct = cc["table"] + cc["list"] + cc["prose"]
        ratio = (cc["table"] + cc["list"]) / cstruct if cstruct else 0.0
        if ratio > CATALOG_RATIO_THRESHOLD:
            sev = fail if rel.startswith(("architecture", "workflows")) else warn
            sev(f"table/list ratio {ratio:.0%} exceeds {CATALOG_RATIO_THRESHOLD:.0%} (catalog shape)",
                ratio=round(ratio, 3), prose_lines=counts["prose"])

    leaked = sorted({cid for cid in claim_ids if cid and re.search(r"(^|[\s(`])" + re.escape(cid) + r"($|[\s).,:`])", text)})
    if leaked:
        fail("claim id(s) leak into doc body", claim_ids=leaked[:10])

    mh = must_have or []
    if "mermaid" in mh and "```mermaid" not in text:
        fail("doc requires a mermaid diagram (plan must_have) but has none")
    if ("task_router" in mh or name == "00_index.md") and not re.search(r"task[ _-]?router", text, re.IGNORECASE):
        fail("doc requires a Task Router but has none")

    if max_bytes and size > max_bytes:
        warn(f"doc size {size}B exceeds plan max_bytes {max_bytes}B", bytes=size, max_bytes=max_bytes)

    return findings


def lint_docs(docs_dir: Path, model_dir: Path) -> list[dict]:
    findings: list[dict] = []
    claims = ml.load_ndjson(model_dir / "claims.ndjson")
    claim_ids = {c.get("id") for c in claims if c.get("id")}
    doc_plan = ml.load_json(model_dir / "doc_plan.json", default={}) or {}
    max_bytes_by_doc = {d["doc"]: d.get("max_bytes") for d in doc_plan.get("docs", [])}
    must_have_by_doc = {d["doc"]: d.get("must_have", []) for d in doc_plan.get("docs", [])}

    md_files = []
    for p in docs_dir.rglob("*.md"):
        relparts = p.relative_to(docs_dir).parts
        if ".work" in relparts or ".model" in relparts:
            continue
        md_files.append(p)
    for p in sorted(md_files):
        rel = p.relative_to(docs_dir).as_posix()
        findings += lint_doc(p, rel, claim_ids, max_bytes_by_doc.get(rel), must_have_by_doc.get(rel, []))
    return findings


# ---------------- audit verdicts (Pass 3) ----------------

def validate_audit(frag_root: Path) -> list[dict]:
    """Check evidence-bound audit results: a contradicted/insufficient verdict must have
    been fixed in the draft (action != kept). An unfixed one is a fail."""
    findings: list[dict] = []
    if not frag_root or not frag_root.exists():
        return findings
    seen_any = False
    for slot_dir in sorted(p for p in frag_root.iterdir() if p.is_dir()):
        vf = slot_dir / "audit_verdicts.ndjson"
        if not vf.exists():
            continue
        seen_any = True
        for v in ml.load_ndjson(vf):
            if v.get("verdict") in ("contradicted", "insufficient") and v.get("action") == "kept":
                findings.append({"severity": "fail", "gate": "audit",
                                 "issue": f"{v.get('verdict')} statement left unfixed (action=kept)",
                                 "doc": v.get("doc"), "statement": str(v.get("statement", ""))[:100]})
    if not seen_any:
        findings.append({"severity": "warning", "gate": "audit",
                         "issue": "no audit_verdicts.ndjson found — Pass 3 audit may not have run"})
    return findings


# ---------------- open-question health (Pass 4 compose) ----------------

def lint_open_questions(model_dir: Path) -> list[dict]:
    """Flag compose-stage regressions. If OQs carry no compose `category`, the compose
    stage did not run (merge->compose->gate regression). If it ran but barely resolved
    anything, warn so a broken compose can't silently ship a half-finished-looking set."""
    oqs = ml.load_ndjson(model_dir / "open_questions.ndjson")
    if not oqs:
        return []
    findings: list[dict] = []
    if not any(o.get("category") for o in oqs):
        findings.append({"severity": "warning", "gate": "compose",
                         "issue": "open_questions carry no compose category — the compose "
                                  "stage did not run (merge->compose->gate regression)"})
        return findings
    open_like = [o for o in oqs if o.get("category", "open") in ("open", "coverage_gap")]
    ratio = len(open_like) / len(oqs)
    if len(oqs) >= 10 and ratio > 0.8:
        findings.append({"severity": "warning", "gate": "compose",
                         "issue": f"{len(open_like)}/{len(oqs)} open questions unresolved after "
                                  f"compose ({ratio:.0%}) — compose may be under-resolving"})
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--docs-dir", help="If given, run the catalog linter on markdown here")
    parser.add_argument("--frag-root", help="If given, validate Pass-3 audit_verdicts under here")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    model_dir = Path(args.model_dir).resolve()
    findings = validate_model(model_dir)
    findings += lint_open_questions(model_dir)
    if args.docs_dir:
        findings += lint_docs(Path(args.docs_dir).resolve(), model_dir)
    if args.frag_root:
        findings += validate_audit(Path(args.frag_root).resolve())

    fails = [f for f in findings if f["severity"] == "fail"]
    warns = [f for f in findings if f["severity"] == "warning"]
    status = "fail" if fails else ("warn" if warns else "pass")
    report = {"status": status, "fail": len(fails), "warn": len(warns), "findings": findings}

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"gate_v3: {status}  ({len(fails)} fail, {len(warns)} warn)")
        for f in findings:
            loc = f.get("doc") or f.get("claim") or f.get("entity") or f.get("anchor") or ""
            print(f"- [{f['severity']}] {f['gate']}: {f['issue']}  {loc}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
