#!/usr/bin/env python3
"""Merge AI writer drafts and evidence fragments into staged AI-docs v2 docs."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def copy_tree(src: Path, dst: Path) -> None:
    for path in sorted(src.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    parser.add_argument("--apply", action="store_true", help="Also copy staged docs into project ai-docs/")
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    writer_dir = run_dir / "synthesis" / "writer-drafts"
    evidence_dir = run_dir / "synthesis" / "evidence-fragments"
    docs_dir = run_dir / "synthesis" / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    warnings: list[str] = []

    if not writer_dir.exists():
        errors.append(f"missing writer drafts directory: {writer_dir}")
    if not evidence_dir.exists():
        errors.append(f"missing evidence fragments directory: {evidence_dir}")
    if errors:
        print(json.dumps({"status": "fail", "errors": errors, "warnings": warnings}, indent=2))
        return 1

    copy_tree(writer_dir, docs_dir)
    evidence = []
    for path in sorted(evidence_dir.glob("*.evidence.json")):
        fragment = load_json(path)
        for item in fragment.get("evidence", []):
            evidence.append(item)
    if not evidence:
        warnings.append("no evidence records found in evidence fragments")

    state = {
        "version": 2,
        "source": "writer-fragments",
        "run_dir": str(run_dir),
        "evidence": evidence,
    }
    (docs_dir / "ai-docs-state.json").write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    applied = False
    if args.apply:
        project_root = Path(args.project_root).resolve()
        ai_docs = project_root / "ai-docs"
        ai_docs.mkdir(parents=True, exist_ok=True)
        copy_tree(docs_dir, ai_docs)
        applied = True

    print(
        json.dumps(
            {
                "status": "warn" if warnings else "pass",
                "docs_dir": str(docs_dir),
                "evidence_records": len(evidence),
                "applied": applied,
                "warnings": warnings,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
