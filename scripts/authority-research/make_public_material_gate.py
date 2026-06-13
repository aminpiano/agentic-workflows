#!/usr/bin/env python3
"""Create a publication-use gate from hallucination audit outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


PUBLIC_BUCKETS = ["usable", "usable_with_caveat", "do_not_use"]
VERDICTS = ["SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONFLICT", "UNKNOWN"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a public-material gate report from hallucination audits.")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-markdown", action="store_true")
    parser.add_argument("--full", action="store_true", help="Print full claim lists; full report is always written to logs.")
    return parser.parse_args()


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def compact_claim(claim: dict[str, Any], audit_file: Path, run_dir: Path) -> dict[str, Any]:
    return {
        "claim_id": claim.get("claim_id"),
        "claim_text": claim.get("claim_text"),
        "verdict": claim.get("verdict"),
        "public_use": claim.get("public_use"),
        "required_caveat": claim.get("required_caveat") or "",
        "risk_flags": claim.get("risk_flags") or [],
        "source_files": claim.get("source_files") or [],
        "source_urls": claim.get("source_urls") or [],
        "audit_file": str(audit_file.relative_to(run_dir)),
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines: list[str] = []
    lines.append("# Public Material Gate")
    lines.append("")
    lines.append(f"Run: `{report['run_dir']}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    for key, value in report["summary"].items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Publication Buckets")
    lines.append("")
    for bucket in PUBLIC_BUCKETS:
        claims = report["claims_by_public_use"].get(bucket, [])
        lines.append(f"### {bucket} ({len(claims)})")
        lines.append("")
        for claim in claims:
            claim_id = claim.get("claim_id") or "UNKNOWN"
            verdict = claim.get("verdict") or "UNKNOWN"
            text = " ".join(str(claim.get("claim_text") or "").split())
            caveat = claim.get("required_caveat") or ""
            lines.append(f"- `{claim_id}` · {verdict}: {text}")
            if caveat:
                lines.append(f"  - Caveat: {caveat}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    audit_dir = run_dir / "hallucination-audits"
    if not audit_dir.exists():
        raise SystemExit(f"hallucination-audits directory not found: {audit_dir}")

    claims_by_public_use: dict[str, list[dict[str, Any]]] = {key: [] for key in PUBLIC_BUCKETS}
    counts_by_verdict = {key: 0 for key in VERDICTS}
    invalid_claims: list[dict[str, Any]] = []
    audit_files = sorted(p for p in audit_dir.glob("*.y*ml") if p.is_file())
    for audit_file in audit_files:
        data = load_yaml(audit_file)
        for claim in data.get("audited_claims") or []:
            if not isinstance(claim, dict):
                continue
            public_use = str(claim.get("public_use") or "do_not_use")
            verdict = str(claim.get("verdict") or "UNKNOWN")
            if verdict in counts_by_verdict:
                counts_by_verdict[verdict] += 1
            else:
                counts_by_verdict["UNKNOWN"] += 1
            compact = compact_claim(claim, audit_file, run_dir)
            if public_use not in claims_by_public_use:
                public_use = "do_not_use"
                compact["gate_note"] = "unknown public_use normalized to do_not_use"
            if verdict in {"UNSUPPORTED", "CONFLICT", "UNKNOWN"} and public_use != "do_not_use":
                invalid_claims.append(compact)
            claims_by_public_use[public_use].append(compact)

    summary = {
        "audit_files": len(audit_files),
        "total_claims": sum(len(items) for items in claims_by_public_use.values()),
        "usable": len(claims_by_public_use["usable"]),
        "usable_with_caveat": len(claims_by_public_use["usable_with_caveat"]),
        "do_not_use": len(claims_by_public_use["do_not_use"]),
        "invalid_public_use": len(invalid_claims),
    }
    report = {
        "run_dir": str(run_dir),
        "summary": summary,
        "counts_by_verdict": counts_by_verdict,
        "claims_by_public_use": claims_by_public_use,
        "invalid_claims": invalid_claims,
    }

    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = logs_dir / "public-material-gate.yaml"
    yaml_path.write_text(yaml.safe_dump(report, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    report["report_path"] = str(yaml_path)
    if not args.no_markdown:
        md_path = logs_dir / "public-material-gate.md"
        write_markdown(report, md_path)
        report["markdown_path"] = str(md_path)

    print_report = report if args.full else {
        "run_dir": report["run_dir"],
        "summary": report["summary"],
        "counts_by_verdict": report["counts_by_verdict"],
        "invalid_claims": report["invalid_claims"],
        "report_path": report["report_path"],
    }
    if "markdown_path" in report:
        print_report["markdown_path"] = report["markdown_path"]

    if args.json:
        print(json.dumps(print_report, ensure_ascii=False, indent=2))
    else:
        print(yaml.safe_dump(print_report, allow_unicode=True, sort_keys=False, width=120).strip())
    return 1 if invalid_claims else 0


if __name__ == "__main__":
    raise SystemExit(main())
