#!/usr/bin/env python3
"""Validate AI-docs v2 staged docs, evidence coverage, and obvious secret leaks."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{16,}"),
]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def scan_secret_like(text: str) -> list[str]:
    matches = []
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            matches.append(pattern.pattern)
    return matches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    docs_dir = run_dir / "synthesis" / "docs"
    slots = load_json(run_dir / "planning" / "doc-slots.json").get("slots", [])
    state_path = docs_dir / "ai-docs-state.json"
    errors: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    if not docs_dir.exists():
        errors.append(f"missing staged docs directory: {docs_dir}")
    if not state_path.exists():
        errors.append(f"missing evidence state: {state_path}")
        state = {"evidence": []}
    else:
        state = load_json(state_path)

    evidence = state.get("evidence", [])
    evidence_by_doc: dict[str, list[dict]] = {}
    for item in evidence:
        evidence_by_doc.setdefault(item.get("doc", ""), []).append(item)
        if item.get("policy", "tracked") != "none":
            for key in ["path", "anchor", "file_sha256", "policy"]:
                if not item.get(key):
                    errors.append(f"evidence {item.get('claim_id', '<unknown>')}: missing {key}")

    for slot in slots:
        output_doc = slot["output_doc"]
        doc_path = docs_dir / output_doc
        if not doc_path.exists():
            errors.append(f"missing output doc {output_doc}")
            continue
        text = doc_path.read_text(encoding="utf-8", errors="replace")
        if "## Evidence" not in text:
            errors.append(f"{output_doc}: missing ## Evidence section")
        if scan_secret_like(text):
            errors.append(f"{output_doc}: contains secret-like text")
        policy = slot.get("evidence_policy", "tracked")
        if policy in {"strict", "tracked"} and not evidence_by_doc.get(output_doc):
            warnings.append(f"{output_doc}: no evidence records for {policy} slot")
        if "UNKNOWN" in text or re.search(r"(?im)^-\s+(?!None recorded\.?$).+", text.split("## Open Questions", 1)[-1] if "## Open Questions" in text else ""):
            notes.append(f"{output_doc}: contains unknowns/open questions")

    summary = {
        "status": "fail" if errors else ("warn" if warnings else "pass"),
        "errors": errors,
        "warnings": warnings,
        "notes": notes,
        "docs_dir": str(docs_dir),
        "evidence_records": len(evidence),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False) if args.json else summary)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
