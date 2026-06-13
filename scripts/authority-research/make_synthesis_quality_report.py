#!/usr/bin/env python3
"""Heuristically check whether final synthesis preserves enough evidence for decisions."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml


CLAIM_ID_RE = re.compile(r"\b[a-z]{1,4}\d{3}-c\d{3}\b", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a synthesis quality report for an authority-research run.")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--full", action="store_true", help="Print full claim id lists; full report is always written to logs.")
    return parser.parse_args()


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def read_texts(paths: list[Path]) -> str:
    chunks: list[str] = []
    for path in paths:
        chunks.append(str(path))
        chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n\n".join(chunks)


def status(pass_condition: bool, warn_condition: bool = False) -> str:
    if pass_condition:
        return "pass"
    if warn_condition:
        return "warn"
    return "fail"


def collect_axes(run_dir: Path) -> list[dict[str, str]]:
    path = run_dir / "schedule" / "domain-map.yaml"
    if not path.exists():
        return []
    data = load_yaml(path)
    axes: list[dict[str, str]] = []
    for item in data.get("axes") or []:
        if isinstance(item, dict):
            axes.append(
                {
                    "id": str(item.get("id") or ""),
                    "label": str(item.get("label") or item.get("name") or item.get("id") or ""),
                }
            )
    return axes


def collect_audit_counts(run_dir: Path) -> dict[str, Any]:
    counts = {
        "total": 0,
        "usable": 0,
        "usable_with_caveat": 0,
        "do_not_use": 0,
        "SUPPORTED": 0,
        "PARTIALLY_SUPPORTED": 0,
        "UNSUPPORTED": 0,
        "CONFLICT": 0,
        "UNKNOWN": 0,
    }
    blocked_ids: list[str] = []
    usable_ids: list[str] = []
    for path in sorted((run_dir / "hallucination-audits").glob("*.y*ml")):
        data = load_yaml(path)
        for claim in data.get("audited_claims") or []:
            if not isinstance(claim, dict):
                continue
            counts["total"] += 1
            verdict = str(claim.get("verdict") or "UNKNOWN")
            public_use = str(claim.get("public_use") or "do_not_use")
            if verdict in counts:
                counts[verdict] += 1
            if public_use in counts:
                counts[public_use] += 1
            claim_id = str(claim.get("claim_id") or "")
            if public_use == "do_not_use":
                blocked_ids.append(claim_id)
            else:
                usable_ids.append(claim_id)
    counts["blocked_claim_ids"] = [item for item in blocked_ids if item]
    counts["usable_claim_ids"] = [item for item in usable_ids if item]
    return counts


def check_axis_coverage(axes: list[dict[str, str]], synthesis_text: str) -> dict[str, Any]:
    if not axes:
        return {"status": "warn", "reason": "no domain-map axes found", "axes_total": 0}
    text = synthesis_text.lower()
    covered: list[str] = []
    missing: list[str] = []
    for axis in axes:
        axis_id = axis["id"].lower()
        label = axis["label"].lower()
        terms = [term for term in {axis_id, label} if term]
        if any(term and term in text for term in terms):
            covered.append(axis["id"] or axis["label"])
        else:
            missing.append(axis["id"] or axis["label"])
    return {
        "status": status(not missing, bool(covered)),
        "axes_total": len(axes),
        "covered_axes": covered,
        "missing_axes": missing,
        "note": "Heuristic string check against article briefs and topic packs; reviewers should inspect missing axes manually.",
    }


def check_claim_trace(synthesis_text: str, audit_counts: dict[str, Any]) -> dict[str, Any]:
    claim_ids = sorted(set(match.group(0) for match in CLAIM_ID_RE.finditer(synthesis_text)))
    usable_ids = set(audit_counts.get("usable_claim_ids") or [])
    referenced_usable = sorted(usable_ids.intersection(claim_ids))
    return {
        "status": status(bool(claim_ids), audit_counts.get("total", 0) > 0),
        "claim_refs_in_synthesis": claim_ids,
        "referenced_usable_claims": referenced_usable,
        "usable_or_caveated_claims": audit_counts.get("usable", 0) + audit_counts.get("usable_with_caveat", 0),
        "note": "Final prose can cite source names instead of claim IDs; missing claim IDs is a warning, not automatic failure.",
    }


def check_uncertainty(synthesis_text: str, audit_counts: dict[str, Any]) -> dict[str, Any]:
    blocked_ids = set(audit_counts.get("blocked_claim_ids") or [])
    mentioned_blocked = sorted(blocked_ids.intersection(set(CLAIM_ID_RE.findall(synthesis_text))))
    uncertainty_terms = ["unknown", "partially_supported", "caveat", "unsupported", "do_not_use", "불확실", "주의", "제외"]
    has_uncertainty_language = any(term.lower() in synthesis_text.lower() for term in uncertainty_terms)
    check_status = "pass"
    if mentioned_blocked and has_uncertainty_language:
        check_status = "warn"
    elif mentioned_blocked:
        check_status = "fail"
    return {
        "status": check_status,
        "blocked_claim_ids_mentioned": mentioned_blocked,
        "has_uncertainty_language": has_uncertainty_language,
        "blocked_claims": audit_counts.get("do_not_use", 0),
        "note": "Blocked claim IDs may be mentioned when clearly labeled as excluded/UNKNOWN; that is a warning, not an automatic failure.",
    }


def check_decision_readiness(synthesis_text: str) -> dict[str, Any]:
    lower = synthesis_text.lower()
    signals = {
        "thesis": any(term in lower for term in ["thesis", "핵심 결론", "결론", "draft thesis"]),
        "recommendation": any(term in lower for term in ["recommend", "recommended", "should", "필요", "추천", "다음 활용"]),
        "risks": any(term in lower for term in ["risk", "caveat", "warning", "주의", "리스크", "unknown"]),
        "artifacts": any(term in lower for term in ["source pointers", "artifact", "산출물", "run directory", "claim-ledger"]),
    }
    passed = sum(1 for value in signals.values() if value)
    return {
        "status": status(passed >= 3, passed >= 2),
        "signals": signals,
        "passed_signals": passed,
        "note": "Checks whether a reader can see conclusion, recommendation, risk, and artifact pointers.",
    }


def check_perspective_preservation(synthesis_text: str) -> dict[str, Any]:
    lower = synthesis_text.lower()
    terms = ["controversy", "conflict", "critic", "risk", "caveat", "unknown", "balance", "반대", "리스크", "주의", "불확실"]
    hits = sorted(term for term in terms if term in lower)
    return {
        "status": status(len(hits) >= 3, len(hits) >= 1),
        "signals": hits,
        "note": "A good synthesis should not erase caveats, conflicts, and excluded claims.",
    }


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    if not run_dir.exists():
        raise SystemExit(f"run directory not found: {run_dir}")

    article_paths = sorted((run_dir / "article-briefs").glob("*.md"))
    topic_paths = sorted((run_dir / "topic-packs").glob("*.y*ml"))
    synthesis_text = read_texts(article_paths + topic_paths)
    axes = collect_axes(run_dir)
    audit_counts = collect_audit_counts(run_dir)

    checks = {
        "coverage_check": check_axis_coverage(axes, synthesis_text),
        "claim_trace_check": check_claim_trace(synthesis_text, audit_counts),
        "uncertainty_check": check_uncertainty(synthesis_text, audit_counts),
        "decision_readiness_check": check_decision_readiness(synthesis_text),
        "perspective_preservation_check": check_perspective_preservation(synthesis_text),
    }
    failed = [name for name, check in checks.items() if check["status"] == "fail"]
    warned = [name for name, check in checks.items() if check["status"] == "warn"]
    report = {
        "run_dir": str(run_dir),
        "inputs": {
            "article_briefs": [str(path.relative_to(run_dir)) for path in article_paths],
            "topic_packs": [str(path.relative_to(run_dir)) for path in topic_paths],
        },
        "audit_counts": audit_counts,
        "summary": {
            "status": "fail" if failed else "warn" if warned else "pass",
            "failed_checks": failed,
            "warned_checks": warned,
            "note": "This is a synthesis usefulness gate, not a token compression metric.",
        },
        "checks": checks,
    }

    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    out = logs_dir / "synthesis-quality-report.yaml"
    out.write_text(yaml.safe_dump(report, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    report["report_path"] = str(out)

    print_report = report
    if not args.full:
        compact_audit_counts = {key: value for key, value in audit_counts.items() if not key.endswith("_claim_ids")}
        compact_checks = dict(checks)
        compact_claim_trace = dict(compact_checks["claim_trace_check"])
        compact_claim_trace["claim_refs_in_synthesis_count"] = len(compact_claim_trace.pop("claim_refs_in_synthesis", []))
        compact_claim_trace["referenced_usable_claims_count"] = len(compact_claim_trace.pop("referenced_usable_claims", []))
        compact_uncertainty = dict(compact_checks["uncertainty_check"])
        blocked_ids = compact_uncertainty.pop("blocked_claim_ids_mentioned", [])
        compact_uncertainty["blocked_claim_ids_mentioned_count"] = len(blocked_ids)
        compact_uncertainty["blocked_claim_ids_mentioned_sample"] = blocked_ids[:10]
        compact_checks["claim_trace_check"] = compact_claim_trace
        compact_checks["uncertainty_check"] = compact_uncertainty
        print_report = {
            "run_dir": report["run_dir"],
            "inputs": {
                "article_briefs": len(article_paths),
                "topic_packs": len(topic_paths),
            },
            "audit_counts": compact_audit_counts,
            "summary": report["summary"],
            "checks": compact_checks,
            "report_path": report["report_path"],
        }

    if args.json:
        print(json.dumps(print_report, ensure_ascii=False, indent=2))
    else:
        print(yaml.safe_dump(print_report, allow_unicode=True, sort_keys=False, width=120).strip())
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
