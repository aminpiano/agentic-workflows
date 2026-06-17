#!/usr/bin/env python3
"""AI-docs v3 compose pass — deterministic stage (runs after merge, before gate).

merge_fragments_v3.py folds per-slot writer fragments into the model *mechanically*
(append + dedupe). Nothing synthesizes across slots, so two failure modes reach the
rendered docs untouched:

  1. open_questions pile up — including ones an audit pass already answered, and
     ones that are really code/doc discrepancies (findings), not genuine unknowns.
     The renderer appends every OQ verbatim, so a 36-OQ run reads as half-finished.
  2. the same infra topic (e.g. Redis) is asserted by claims scattered across N
     docs with no composed cross-cutting view — the reader must reconstruct it.

This stage is DETERMINISTIC and introduces NO new facts. It only *classifies* what
merge produced, so a later LLM compose pass (and the renderer) can act on it:

  OQ classification
    - resolved          : the OQ (or a sibling audit OQ) already states the answer.
    - finding           : reports a concrete two-value code/doc discrepancy ->
                          belongs in a Findings section, not Open questions.
    - cross_doc_candidate: the OQ is about a file/symbol another doc's claims cover
                          -> a later LLM pass can confirm and resolve it.
    - open              : a genuine unknown with no in-model answer (kept).

  cross-cutting clusters
    - claims sharing an infra topic but spread over >=2 docs -> one composed view
      candidate (the v1 "caching architecture table" effect).

Outputs compose-plan.json. With --apply, folds the deterministic verdicts
(status + category) back into open_questions.ndjson so the renderer can filter;
resolved/finding OQs leave the Open-questions section. No claim is rewritten here.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import modellib as ml

# An OQ whose own text says it is answered (audit Pass-3 writes these back as text
# but merge never flips the status).
RESOLVED_RE = re.compile(
    r"resolved by audit|audit resolution|no open question remains|"
    r"\bis answered\b|already (?:answered|resolved)",
    re.I,
)

# A concrete discrepancy: two sources state different values for the same thing
# (code vs docstring/spec/label, or two coexisting definitions). A contrast marker
# near a value-source word (says/label/default/docstring) counts even without an
# explicit "stale", because "X says A but code is B" is itself the finding.
FINDING_RE = re.compile(
    r"(?:\bbut\b|\bwhile\b|\bwhereas\b|\bvs\.?\b).{0,200}?"
    r"(?:stale|outdated|mismatch|diverg|do(?:es)?\s+not\s+match|inconsistent|"
    r"appears?\s+(?:to\s+be\s+)?(?:stale|outdated|wrong)|hardcoded|"
    r"docstring|\bsays?\b|\blabel(?:ed|s)?\b|\bdefault\b|coexist)"
    r"|partially\s+stale|divergent\s+defaults?|coexist\s+with\s+divergent|"
    r"docstring.{0,80}?(?:stale|outdated|appears|says?)",
    re.I,
)

# The OQ explicitly defers to another doc's ownership / an unread file -> another
# slot likely documented it, so the merged model may already answer it.
CROSSDOC_RE = re.compile(
    r"owned by (?:another|the)\b|outside (?:this|the)\b.{0,40}?(?:doc|owned|source|file)|"
    r"not (?:an |in )?(?:this )?(?:doc'?s? )?(?:owned|read)\b|was not read\b|"
    r"not in (?:this|the).{0,30}?(?:owned|read|source) set|owned elsewhere|"
    r"owned/blueprint set|another (?:doc|writer|slot)|not (?:an )?owned source",
    re.I,
)

# Infra topics that tend to span multiple docs. Value = regex over claim text.
TOPICS: dict[str, re.Pattern] = {
    "redis": re.compile(r"\bredis\b", re.I),
    "cache": re.compile(r"cache(?:service)?\b", re.I),
    "deal_lock": re.compile(r"deal[ _-]?lock", re.I),
    "rate_limit": re.compile(r"rate[ _-]?limit|slowapi|\blimiter\b", re.I),
    "auth": re.compile(r"\bjwt\b|bearer|x-admin-key|admin[ _-]?key|\bauthenticat", re.I),
    "telegram": re.compile(r"telegram|t\.me|webhook", re.I),
    "fcm_push": re.compile(r"\bfcm\b|firebase|push notif", re.I),
    "websocket": re.compile(r"websocket|\bws:|\bws\b", re.I),
    "scheduler": re.compile(r"scheduler|apscheduler|add_job|intervaltrigger", re.I),
}

_ANCHOR_PATH = re.compile(r"^a:(?:llm:)?(.+?):\d+")


def anchor_path(anchor_id: str) -> str | None:
    """Pull the file path out of an anchor id like a:backend/x.py:42:kind or a:llm:backend/x.py:42."""
    m = _ANCHOR_PATH.match(anchor_id or "")
    if m:
        return m.group(1)
    # tolerate a:llm:<path>:<line> with no trailing kind, already covered; fallback None
    return None


def oq_paths(oq: dict) -> set[str]:
    out: set[str] = set()
    for a in oq.get("support", []):
        p = anchor_path(a)
        if p:
            out.add(p)
    return out


def claim_paths(claim: dict) -> set[str]:
    out: set[str] = set(claim.get("dep_files", []) or [])
    for a in claim.get("support", []):
        p = anchor_path(a)
        if p:
            out.add(p)
    return out


def classify_oqs(oqs: list[dict], claims: list[dict]) -> list[dict]:
    # Index claims by the files they depend on, with their doc, for cross-doc lookup.
    claims_by_path: dict[str, list[dict]] = {}
    for c in claims:
        for p in claim_paths(c):
            claims_by_path.setdefault(p, []).append(c)
    # Drop hub files (entrypoint/config shared by many claims). Matching an OQ to
    # another doc *because both touch main.py* is a false resolver — everything
    # routes through the entrypoint. Keep only discriminating files.
    HUB_THRESHOLD = 6
    hub_paths = {p for p, cs in claims_by_path.items() if len(cs) > HUB_THRESHOLD}
    if hub_paths:
        claims_by_path = {p: cs for p, cs in claims_by_path.items() if p not in hub_paths}

    verdicts = []
    for oq in oqs:
        text = oq.get("question", "")
        oq_id = oq.get("id")
        doc = oq.get("doc")
        category = "open"
        evidence: dict = {}

        if RESOLVED_RE.search(text):
            category = "resolved"
        elif FINDING_RE.search(text):
            category = "finding"
        else:
            # cross-doc: this OQ is about files another doc's claims already cover.
            paths = oq_paths(oq)
            resolvers = []
            for p in paths:
                for c in claims_by_path.get(p, []):
                    if c.get("doc") != doc:  # answered by a *different* slot
                        resolvers.append({"claim": c.get("id"), "doc": c.get("doc"), "path": p})
            defers = bool(CROSSDOC_RE.search(text))
            if resolvers:
                category = "cross_doc_candidate"
                # de-dup resolvers, cap for readability
                seen = set()
                uniq = []
                for r in resolvers:
                    k = (r["claim"], r["path"])
                    if k not in seen:
                        seen.add(k)
                        uniq.append(r)
                evidence["resolvers"] = uniq[:8]
                evidence["defers_to_other_doc"] = defers
            elif defers:
                # defers to another doc but no claim covers it yet -> still a real gap,
                # but a *coverage* gap, not a genuine unknown. flag distinctly.
                category = "coverage_gap"

        verdicts.append({"id": oq_id, "doc": doc, "category": category, **evidence})
    return verdicts


def cluster_crosscutting(claims: list[dict]) -> list[dict]:
    clusters = []
    for topic, rx in TOPICS.items():
        hits = [c for c in claims if rx.search(c.get("text", ""))]
        docs = sorted({c.get("doc") for c in hits if c.get("doc")})
        if len(hits) >= 3 and len(docs) >= 2:
            clusters.append({
                "topic": topic,
                "claim_count": len(hits),
                "doc_spread": docs,
                "claims": [c.get("id") for c in hits],
            })
    clusters.sort(key=lambda x: (-len(x["doc_spread"]), -x["claim_count"]))
    return clusters


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--out", default=None, help="compose-plan.json path (default: <model-dir>/compose-plan.json)")
    ap.add_argument("--apply", action="store_true",
                    help="fold status/category back into open_questions.ndjson")
    args = ap.parse_args()

    model_dir = Path(args.model_dir).resolve()
    oqs = ml.load_ndjson(model_dir / "open_questions.ndjson")
    claims = ml.load_ndjson(model_dir / "claims.ndjson")

    verdicts = classify_oqs(oqs, claims)
    clusters = cluster_crosscutting(claims)

    counts: dict[str, int] = {}
    for v in verdicts:
        counts[v["category"]] = counts.get(v["category"], 0) + 1
    open_like = counts.get("open", 0) + counts.get("coverage_gap", 0)

    plan = {
        "version": 3,
        "input": {"open_questions": len(oqs), "claims": len(claims)},
        "oq_counts": counts,
        "oq_section_after_compose": open_like,  # what the renderer's OQ section would keep
        "oq_verdicts": verdicts,
        "crosscutting_clusters": clusters,
    }

    out = Path(args.out) if args.out else (model_dir / "compose-plan.json")
    ml.write_json(out, plan)

    if args.apply:
        vmap = {v["id"]: v for v in verdicts}
        for oq in oqs:
            v = vmap.get(oq.get("id"), {})
            oq["status"] = "open" if v.get("category") in ("open", "coverage_gap") else "closed"
            oq["category"] = v.get("category", "open")
            if v.get("resolvers"):
                oq["resolver_candidates"] = v["resolvers"]
        ml.write_ndjson(model_dir / "open_questions.ndjson", oqs)

    print(json.dumps({
        "open_questions_in": len(oqs),
        "oq_counts": counts,
        "oq_section_after_compose": open_like,
        "crosscutting_clusters": [(c["topic"], len(c["doc_spread"]), c["claim_count"]) for c in clusters],
        "plan": str(out),
        "applied": args.apply,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
