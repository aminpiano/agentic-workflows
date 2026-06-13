#!/usr/bin/env python3
"""Normalize common authority-research metadata drift in inventory/profile YAML."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


TRUST = {"s": "S", "a": "A", "a-": "A", "a+": "A", "b": "B", "b+": "B", "b-": "B", "c": "C", "d": "D", "unknown": "UNKNOWN"}
LIKELY = {"high": "high", "medium": "medium", "low": "low"}
TEMPORAL = {
    "current": "current",
    "current_maintained": "current",
    "living": "current",
    "living repo": "current",
    "living benchmark hub; current as of 2026": "current",
    "foundational": "foundational",
    "foundation": "foundational",
    "historical": "foundational",
    "historical_still_relevant": "foundational",
    "frontier": "frontier",
    "emerging": "frontier",
    "emerging_standard": "frontier",
    "deprecated": "deprecated",
    "unknown": "UNKNOWN",
}
TOPIC_RELATION = {
    "core": "core",
    "central": "core",
    "adjacent": "adjacent",
    "historical": "historical",
    "counterframe": "counterframe",
}
SOURCE_SCALE = {
    "point": "point",
    "article": "point",
    "paper": "point",
    "standard": "point",
    "product": "point",
    "project": "point",
    "repo": "point",
    "collection": "collection",
    "source_family": "collection",
    "benchmark family": "collection",
    "large open-source benchmark repo": "collection",
    "mega": "mega",
}
SOURCE_ROLE = {
    "primary": "primary",
    "primary_evidence": "primary",
    "anchor": "primary",
    "artifact": "primary",
    "evidence_corpus": "primary",
    "secondary": "secondary",
    "design_rationale": "secondary",
    "vendor_explanation": "secondary",
    "comparative_source": "secondary",
    "derivative": "derivative",
    "index": "index",
}
PREFERRED_ACTION = {
    "profile": "profile",
    "collect": "profile",
    "expand_children": "expand_children",
    "use_as_index_only": "use_as_index_only",
    "skip": "skip",
}
ACCESS_METHOD = {
    "search": "search",
    "sitemap": "sitemap",
    "rss": "rss",
    "list_pages": "list_pages",
    "site_search": "site_search",
    "manual_web": "manual_web",
    "api": "api",
    "unknown": "unknown",
    "direct_html": "manual_web",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize inventory/profile enum drift.")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--write", action="store_true", help="Rewrite YAML files in place. Default is dry-run.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def norm_key(value: Any) -> str:
    return str(value or "").strip().strip('"').strip("'").lower()


def infer_information_angle(value: Any, item: dict[str, Any]) -> str | None:
    raw = " ".join(str(part or "") for part in [value, item.get("source_type"), item.get("reason"), item.get("source_name")]).lower()
    if not raw.strip():
        return None
    if any(term in raw for term in ["risk", "security", "prompt injection", "attack", "failure", "critique", "controversy"]):
        return "critical_risk"
    if any(term in raw for term in ["paper", "arxiv", "academic", "research", "benchmark", "evaluation", "eval"]):
        return "academic_evidence"
    if any(term in raw for term in ["runbook", "ops", "incident", "deploy", "rollback", "practitioner", "sre"]):
        return "practitioner_ops"
    if any(term in raw for term in ["market", "competitor", "comparative", "landscape", "industry"]):
        return "comparative_industry"
    if any(term in raw for term in ["repo", "github", "tool", "implementation", "api", "generator", "cli", "code"]):
        return "implementation_artifact"
    if any(term in raw for term in ["official", "docs", "spec", "standard", "primary", "canonical"]):
        return "origin_primary"
    return None


def map_value(value: Any, mapping: dict[str, str]) -> str | None:
    key = norm_key(value)
    if key in mapping:
        return mapping[key]
    for prefix, mapped in mapping.items():
        if prefix and key.startswith(prefix):
            return mapped
    return None


def add_note(item: dict[str, Any], field: str, old: Any) -> None:
    note_key = f"{field}_note"
    if old and note_key not in item:
        item[note_key] = str(old)


def normalize_inventory_item(item: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []

    def set_field(field: str, new: str | None, *, keep_note: bool = False) -> None:
        if not new:
            return
        old = item.get(field)
        if old != new:
            if keep_note:
                add_note(item, field, old)
            item[field] = new
            changes.append({"field": field, "old": old, "new": new})

    set_field("likely_value", map_value(item.get("likely_value"), LIKELY))
    set_field("trust_grade_hint", map_value(item.get("trust_grade_hint"), TRUST))
    set_field("temporal_position", map_value(item.get("temporal_position"), TEMPORAL), keep_note=True)
    set_field("topic_relation", map_value(item.get("topic_relation"), TOPIC_RELATION), keep_note=True)
    set_field("source_scale", map_value(item.get("source_scale"), SOURCE_SCALE), keep_note=True)
    set_field("source_role", map_value(item.get("source_role"), SOURCE_ROLE), keep_note=True)
    set_field("preferred_action", map_value(item.get("preferred_action"), PREFERRED_ACTION), keep_note=True)

    angle = norm_key(item.get("information_angle"))
    allowed_angles = {"origin_primary", "academic_evidence", "implementation_artifact", "practitioner_ops", "comparative_industry", "critical_risk"}
    if angle not in allowed_angles:
        set_field("information_angle", infer_information_angle(item.get("information_angle"), item), keep_note=True)
    return changes


def normalize_profile_item(item: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []

    def set_field(field: str, new: str | None, *, keep_note: bool = False) -> None:
        if not new:
            return
        old = item.get(field)
        if old != new:
            if keep_note:
                add_note(item, field, old)
            item[field] = new
            changes.append({"field": field, "old": old, "new": new})

    access = norm_key(item.get("access_method"))
    if access not in ACCESS_METHOD:
        if "api" in access:
            mapped = "api"
        elif any(term in access for term in ["rss", "feed"]):
            mapped = "rss"
        elif any(term in access for term in ["sitemap"]):
            mapped = "sitemap"
        elif any(term in access for term in ["search"]):
            mapped = "search"
        elif access:
            mapped = "manual_web"
        else:
            mapped = None
        set_field("access_method", mapped, keep_note=True)
    else:
        set_field("access_method", ACCESS_METHOD[access], keep_note=True)

    feas = norm_key(item.get("parse_feasibility"))
    if feas not in {"easy", "medium", "hard", "unknown"}:
        if any(term in feas for term in ["high", "easy"]):
            mapped = "easy"
        elif any(term in feas for term in ["low", "hard", "difficult"]):
            mapped = "hard"
        elif any(term in feas for term in ["medium", "moderate"]):
            mapped = "medium"
        else:
            mapped = "unknown" if feas else None
        set_field("parse_feasibility", mapped, keep_note=True)
    return changes


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def write_yaml(path: Path, data: Any) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")


def normalize_file(path: Path, kind: str, write: bool) -> list[dict[str, Any]]:
    data = load_yaml(path)
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("sources") if kind == "inventory" else data.get("profiles")
    else:
        return []
    if not isinstance(items, list):
        return []
    changes: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        item_changes = normalize_inventory_item(item) if kind == "inventory" else normalize_profile_item(item)
        for change in item_changes:
            change["item_index"] = index
            changes.append(change)
    if write and changes:
        write_yaml(path, data)
    return changes


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    if not run_dir.exists():
        raise SystemExit(f"run directory not found: {run_dir}")
    report: dict[str, Any] = {"run_dir": str(run_dir), "mode": "write" if args.write else "dry-run", "files": [], "total_changes": 0}
    for kind, dirname in [("inventory", "inventory"), ("profiles", "profiles")]:
        for path in sorted((run_dir / dirname).glob("*.y*ml")):
            changes = normalize_file(path, kind, args.write)
            if changes:
                report["files"].append({"path": str(path.relative_to(run_dir)), "kind": kind, "changes": changes})
                report["total_changes"] += len(changes)
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    out = logs_dir / "normalization-report.yaml"
    out.write_text(yaml.safe_dump(report, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    report["report_path"] = str(out)
    if args.json:
        import json

        print(json.dumps({"run_dir": report["run_dir"], "mode": report["mode"], "total_changes": report["total_changes"], "report_path": report["report_path"]}, ensure_ascii=False, indent=2))
    else:
        print(yaml.safe_dump({"run_dir": report["run_dir"], "mode": report["mode"], "total_changes": report["total_changes"], "report_path": report["report_path"]}, allow_unicode=True, sort_keys=False).strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
