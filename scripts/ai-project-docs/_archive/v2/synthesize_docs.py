#!/usr/bin/env python3
"""Synthesize baseline AI-docs v2 markdown and evidence state from merged packets."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def current_commit(root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "uncommitted"
    return proc.stdout.strip() or "uncommitted"


def title_for(slot_id: str) -> str:
    return slot_id.replace("_", " ").replace("-", " ").title()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug or "claim"


def md_escape(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def render_slot_doc(slot: dict, findings: list[dict], generated: str, commit: str) -> tuple[str, list[dict]]:
    slot_id = slot["slot_id"]
    title = "AI Docs Index" if slot_id == "overview" else title_for(slot_id)
    lines = [
        f"# {title}",
        "",
        f"> Generated: {generated} | Based on commit: {commit} | AI-docs v2",
        "",
        "## Summary",
        "",
    ]
    evidence_state: list[dict] = []
    if findings:
        lines.extend(["| Claim ID | Claim | Confidence |", "|---|---|---|"])
        for idx, finding in enumerate(findings, start=1):
            claim_id = f"{slot_id}.{idx:03d}.{slugify(finding.get('claim', 'claim'))[:48]}"
            finding["_claim_id"] = claim_id
            lines.append(
                f"| `{claim_id}` | {md_escape(finding.get('claim'))} | {md_escape(finding.get('confidence', 'unknown'))} |"
            )
    else:
        lines.append("- No verified findings were provided for this slot.")
    lines.extend(["", "## Evidence", ""])
    if findings:
        lines.extend(
            [
                "| Claim ID | Source | Anchor | Policy | Hash |",
                "|---|---|---|---|---|",
            ]
        )
        for finding in findings:
            claim_id = finding["_claim_id"]
            for evidence in finding.get("evidence", []):
                hash_value = evidence.get("file_sha256") or evidence.get("sha256") or ""
                lines.append(
                    f"| `{claim_id}` | `{md_escape(evidence.get('path'))}` | "
                    f"{md_escape(evidence.get('anchor'))} | `{md_escape(evidence.get('policy', 'tracked'))}` | "
                    f"`{hash_value[:12]}` |"
                )
                evidence_state.append(
                    {
                        "doc": slot["output_doc"],
                        "claim_id": claim_id,
                        "path": evidence.get("path"),
                        "anchor": evidence.get("anchor"),
                        "anchor_line": evidence.get("anchor_line"),
                        "file_sha256": evidence.get("file_sha256") or evidence.get("sha256"),
                        "policy": evidence.get("policy", slot.get("evidence_policy", "tracked")),
                    }
                )
    else:
        lines.append("- No evidence records.")
    open_questions = []
    for finding in findings:
        for question in finding.get("open_questions", []):
            open_questions.append(question)
    lines.extend(["", "## Open Questions", ""])
    if open_questions:
        for question in open_questions:
            lines.append(f"- {question}")
    else:
        lines.append("- None recorded.")
    lines.append("")
    return "\n".join(lines), evidence_state


def copy_tree(src: Path, dst: Path) -> None:
    for path in sorted(src.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def has_v2_state(ai_docs: Path) -> bool:
    state_path = ai_docs / "ai-docs-state.json"
    if not state_path.exists():
        return False
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return state.get("version") == 2


def apply_conflicts(staged_docs: Path, ai_docs: Path) -> list[str]:
    if has_v2_state(ai_docs):
        return []
    conflicts = []
    for path in sorted(staged_docs.rglob("*")):
        if path.is_dir() or path.name == "ai-docs-state.json":
            continue
        rel = path.relative_to(staged_docs)
        target = ai_docs / rel
        if target.exists():
            conflicts.append(rel.as_posix())
    return conflicts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--apply", action="store_true", help="Write docs into <project-root>/ai-docs instead of staging only")
    parser.add_argument(
        "--force-apply",
        action="store_true",
        help="Allow --apply to overwrite existing non-v2 ai-docs files after explicit review",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    project_root = Path(args.project_root).resolve()
    slots = load_json(run_dir / "planning" / "doc-slots.json").get("slots", [])
    merged_path = run_dir / "synthesis" / "merged-packets.json"
    if not merged_path.exists():
        raise SystemExit(f"Missing merged packets: {merged_path}. Run merge_packets.py first.")
    merged = load_json(merged_path)
    findings_by_slot = merged.get("findings_by_slot", {})
    generated = dt.date.today().isoformat()
    commit = current_commit(project_root)
    out_dir = run_dir / "synthesis" / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)

    state_evidence: list[dict] = []
    for slot in slots:
        findings = findings_by_slot.get(slot["slot_id"], [])
        content, evidence = render_slot_doc(slot, findings, generated, commit)
        target = out_dir / slot["output_doc"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        state_evidence.extend(evidence)

    state = {
        "version": 2,
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "commit": commit,
        "run_dir": str(run_dir),
        "evidence": state_evidence,
    }
    (out_dir / "ai-docs-state.json").write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if args.apply:
        ai_docs = project_root / "ai-docs"
        ai_docs.mkdir(parents=True, exist_ok=True)
        conflicts = apply_conflicts(out_dir, ai_docs)
        if conflicts and not args.force_apply:
            raise SystemExit(
                "Refusing to overwrite existing non-v2 ai-docs files without --force-apply: "
                + ", ".join(conflicts[:12])
                + (" ..." if len(conflicts) > 12 else "")
            )
        copy_tree(out_dir, ai_docs)
    print(
        json.dumps(
            {
                "status": "pass",
                "docs_dir": str(out_dir),
                "applied": args.apply,
                "evidence_records": len(state_evidence),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
