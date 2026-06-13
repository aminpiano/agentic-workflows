#!/usr/bin/env python3
"""Validate authority-research run contracts without reading raw source bodies."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


REQUIRED_DIRS = [
    "inventory",
    "profiles",
    "schedule",
    "raw",
    "triaged",
    "rejected",
    "classified",
    "verified",
    "curation",
    "claim-ledger",
    "hallucination-audits",
    "topic-packs",
    "article-briefs",
    "synthesis",
    "dedup",
    "done",
    "logs",
    "prompts",
]

DONE_STATUS = {"done", "failed"}
DONE_STATUS_ALIASES = {"completed": "done", "complete": "done"}
SCHEDULE_STATUS = {"pending", "running", "done", "failed", "skipped"}
WORKER = {"codex", "agy", "either", "codex-subagent", "claude-agent", "workflow"}
PRIORITY = {"critical", "high", "medium", "low"}
LIKELY_VALUE = {"high", "medium", "low"}
TRUST_GRADE = {"S", "A", "B", "C", "D", "UNKNOWN"}
INFO_ANGLE = {
    "origin_primary",
    "academic_evidence",
    "implementation_artifact",
    "practitioner_ops",
    "comparative_industry",
    "critical_risk",
}
TEMPORAL_POSITION = {"foundational", "current", "frontier", "deprecated", "UNKNOWN"}
TOPIC_RELATION = {"core", "adjacent", "historical", "counterframe"}
SOURCE_SCALE = {"point", "collection", "mega"}
SOURCE_ROLE = {"primary", "secondary", "derivative", "index"}
DERIVATIVE_RISK = {"low", "medium", "high"}
PREFERRED_ACTION = {"profile", "expand_children", "use_as_index_only", "skip", "collect"}
PARSE_FEASIBILITY = {"easy", "medium", "hard", "unknown"}
RECOMMENDED_WORKER = {"codex", "agy", "either", "collector"}
VERDICT = {"SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONFLICT", "UNKNOWN"}
PUBLIC_USE = {"usable", "usable_with_caveat", "do_not_use"}


@dataclass
class Issue:
    severity: str
    path: str
    field: str
    message: str
    value: Any = None
    allowed: list[str] | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate an authority-research run folder.")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as validation failures.")
    parser.add_argument("--warning-threshold", type=int, default=None, help="Fail when warnings exceed this threshold.")
    parser.add_argument("--max-issues", type=int, default=50, help="Maximum issues to print; full report is still written.")
    parser.add_argument("--all-issues", action="store_true", help="Print every issue.")
    return parser.parse_args()


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def load_yaml(path: Path, root: Path, issues: list[Issue]) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001 - validator must report parser failures tersely.
        issues.append(Issue("error", rel(path, root), "$", f"YAML parse failed: {exc.__class__.__name__}: {exc}"))
        return None


def yaml_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted([p for p in path.rglob("*") if p.is_file() and p.suffix in {".yaml", ".yml"}])


def issue(
    issues: list[Issue],
    severity: str,
    path: Path,
    root: Path,
    field: str,
    message: str,
    value: Any = None,
    allowed: set[str] | None = None,
) -> None:
    issues.append(
        Issue(
            severity=severity,
            path=rel(path, root),
            field=field,
            message=message,
            value=value,
            allowed=sorted(allowed) if allowed else None,
        )
    )


def normalized_lower(value: Any) -> str:
    return str(value or "").strip().strip('"').strip("'").lower()


def normalized_status(value: Any) -> tuple[str, bool]:
    raw = normalized_lower(value)
    if raw in DONE_STATUS:
        return raw, False
    if raw in DONE_STATUS_ALIASES:
        return DONE_STATUS_ALIASES[raw], True
    return raw or "UNKNOWN", False


def field_group(field: str) -> str:
    cleaned = re.sub(r"\[[0-9]+\]\.?", "", field)
    return cleaned or field


def validate_enum(
    issues: list[Issue],
    path: Path,
    root: Path,
    field: str,
    value: Any,
    allowed: set[str],
    *,
    severity: str = "warning",
    case_sensitive: bool = False,
) -> None:
    if value is None:
        return
    raw = str(value).strip().strip('"').strip("'")
    candidate = raw if case_sensitive else raw.lower()
    allowed_cmp = allowed if case_sensitive else {item.lower() for item in allowed}
    if candidate not in allowed_cmp:
        issue(issues, severity, path, root, field, "value outside controlled vocabulary", value, allowed)


def validate_domain_map(run_dir: Path, issues: list[Issue]) -> None:
    path = run_dir / "schedule" / "domain-map.yaml"
    if not path.exists():
        return
    data = load_yaml(path, run_dir, issues)
    if data is None:
        return
    if not isinstance(data, dict):
        issue(issues, "error", path, run_dir, "$", "domain map must be a mapping")
        return
    axes = data.get("axes")
    if not isinstance(axes, list) or not axes:
        issue(issues, "error", path, run_dir, "axes", "domain map must contain a non-empty axes list")
        return
    seen: set[str] = set()
    for index, axis in enumerate(axes):
        field = f"axes[{index}]"
        if not isinstance(axis, dict):
            issue(issues, "error", path, run_dir, field, "axis must be a mapping")
            continue
        axis_id = str(axis.get("id") or "").strip()
        if not axis_id:
            issue(issues, "error", path, run_dir, f"{field}.id", "axis id is required")
        elif axis_id in seen:
            issue(issues, "error", path, run_dir, f"{field}.id", "axis id is duplicated", axis_id)
        seen.add(axis_id)
        if not axis.get("scope"):
            issue(issues, "warning", path, run_dir, f"{field}.scope", "axis scope is missing")
        validate_enum(issues, path, run_dir, f"{field}.priority", axis.get("priority"), PRIORITY)
        validate_enum(issues, path, run_dir, f"{field}.preferred_worker", axis.get("preferred_worker"), {"codex", "agy", "either"})


def validate_schedule_file(path: Path, run_dir: Path, issues: list[Issue]) -> None:
    data = load_yaml(path, run_dir, issues)
    if data is None:
        return
    if not isinstance(data, dict):
        issue(issues, "error", path, run_dir, "$", "schedule must be a mapping")
        return
    tasks = data.get("tasks")
    if tasks is None:
        return
    if not isinstance(tasks, list):
        issue(issues, "error", path, run_dir, "tasks", "schedule tasks must be a list")
        return
    seen: set[str] = set()
    for index, task in enumerate(tasks):
        field = f"tasks[{index}]"
        if not isinstance(task, dict):
            issue(issues, "error", path, run_dir, field, "task must be a mapping")
            continue
        task_id = str(task.get("task_id") or "").strip()
        if not task_id:
            issue(issues, "error", path, run_dir, f"{field}.task_id", "task_id is required")
        elif task_id in seen:
            issue(issues, "error", path, run_dir, f"{field}.task_id", "task_id is duplicated", task_id)
        seen.add(task_id)
        validate_enum(issues, path, run_dir, f"{field}.status", task.get("status"), SCHEDULE_STATUS)
        validate_enum(issues, path, run_dir, f"{field}.worker", task.get("worker"), WORKER)
        if "expected_outputs" in task and not isinstance(task.get("expected_outputs"), list):
            issue(issues, "warning", path, run_dir, f"{field}.expected_outputs", "expected_outputs should be a list")


def validate_done_file(path: Path, run_dir: Path, issues: list[Issue], status_counts: dict[str, int]) -> None:
    data = load_yaml(path, run_dir, issues)
    if data is None:
        status_counts["other"] += 1
        return
    if not isinstance(data, dict):
        issue(issues, "error", path, run_dir, "$", "done marker must be a mapping")
        status_counts["other"] += 1
        return
    status, aliased = normalized_status(data.get("status"))
    if status in DONE_STATUS:
        status_counts[status] += 1
    else:
        status_counts["other"] += 1
        issue(issues, "error", path, run_dir, "status", "done status must be done or failed", data.get("status"), DONE_STATUS)
    if aliased:
        issue(issues, "warning", path, run_dir, "status", "status alias normalized to done", data.get("status"), DONE_STATUS)
    if not data.get("task_id"):
        issue(issues, "warning", path, run_dir, "task_id", "done marker should include task_id")
    if "output_files" in data and not isinstance(data.get("output_files"), list):
        issue(issues, "warning", path, run_dir, "output_files", "output_files should be a list")


def validate_inventory_item(path: Path, run_dir: Path, issues: list[Issue], item: dict[str, Any], index: int) -> None:
    base = f"[{index}]"
    for required in ["source_name", "source_url"]:
        if not item.get(required):
            issue(issues, "warning", path, run_dir, f"{base}.{required}", "inventory item missing recommended field")
    validate_enum(issues, path, run_dir, f"{base}.likely_value", item.get("likely_value"), LIKELY_VALUE)
    validate_enum(issues, path, run_dir, f"{base}.trust_grade_hint", item.get("trust_grade_hint"), TRUST_GRADE, case_sensitive=True)
    validate_enum(issues, path, run_dir, f"{base}.information_angle", item.get("information_angle"), INFO_ANGLE)
    validate_enum(issues, path, run_dir, f"{base}.temporal_position", item.get("temporal_position"), TEMPORAL_POSITION)
    validate_enum(issues, path, run_dir, f"{base}.topic_relation", item.get("topic_relation"), TOPIC_RELATION)
    validate_enum(issues, path, run_dir, f"{base}.source_scale", item.get("source_scale"), SOURCE_SCALE)
    validate_enum(issues, path, run_dir, f"{base}.source_role", item.get("source_role"), SOURCE_ROLE)
    validate_enum(issues, path, run_dir, f"{base}.derivative_risk", item.get("derivative_risk"), DERIVATIVE_RISK)
    validate_enum(issues, path, run_dir, f"{base}.preferred_action", item.get("preferred_action"), PREFERRED_ACTION)


def validate_inventory_file(path: Path, run_dir: Path, issues: list[Issue]) -> None:
    data = load_yaml(path, run_dir, issues)
    if data is None:
        return
    items = data if isinstance(data, list) else data.get("sources") if isinstance(data, dict) else None
    if not isinstance(items, list):
        issue(issues, "warning", path, run_dir, "$", "inventory output should be a list or mapping with sources")
        return
    for index, item in enumerate(items):
        if isinstance(item, dict):
            validate_inventory_item(path, run_dir, issues, item, index)
        else:
            issue(issues, "warning", path, run_dir, f"[{index}]", "inventory item should be a mapping")


def validate_profile_file(path: Path, run_dir: Path, issues: list[Issue]) -> None:
    data = load_yaml(path, run_dir, issues)
    if data is None:
        return
    items = data if isinstance(data, list) else data.get("profiles") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            issue(issues, "warning", path, run_dir, f"[{index}]", "profile item should be a mapping")
            continue
        base = f"[{index}]"
        validate_enum(issues, path, run_dir, f"{base}.access_method", item.get("access_method"), {"search", "sitemap", "rss", "list_pages", "site_search", "manual_web", "api", "unknown", "direct_html"})
        validate_enum(issues, path, run_dir, f"{base}.parse_feasibility", item.get("parse_feasibility"), PARSE_FEASIBILITY)
        validate_enum(issues, path, run_dir, f"{base}.recommended_worker", item.get("recommended_worker"), RECOMMENDED_WORKER)


def validate_curation_file(path: Path, run_dir: Path, issues: list[Issue]) -> None:
    data = load_yaml(path, run_dir, issues)
    if data is None or not isinstance(data, dict):
        return
    curated = data.get("curated_sources")
    if curated is None:
        issue(issues, "warning", path, run_dir, "curated_sources", "curation file lacks curated_sources; design synthesis should be a separate output")
        return
    if not isinstance(curated, list):
        issue(issues, "error", path, run_dir, "curated_sources", "curated_sources must be a list")
        return
    for index, item in enumerate(curated):
        if not isinstance(item, dict):
            issue(issues, "warning", path, run_dir, f"curated_sources[{index}]", "curated source should be a mapping")
            continue
        if not item.get("source_file") and not item.get("source_url"):
            issue(issues, "warning", path, run_dir, f"curated_sources[{index}]", "curated source should retain source_file or source_url")


def validate_claim_ledger_file(path: Path, run_dir: Path, issues: list[Issue]) -> None:
    data = load_yaml(path, run_dir, issues)
    if data is None or not isinstance(data, dict):
        return
    claims = data.get("claims")
    if not isinstance(claims, list):
        issue(issues, "error", path, run_dir, "claims", "claim ledger must contain claims list")
        return
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            issue(issues, "error", path, run_dir, f"claims[{index}]", "claim must be a mapping")
            continue
        base = f"claims[{index}]"
        if not claim.get("claim_id"):
            issue(issues, "error", path, run_dir, f"{base}.claim_id", "claim_id is required")
        if not claim.get("claim_text"):
            issue(issues, "error", path, run_dir, f"{base}.claim_text", "claim_text is required")
        if not claim.get("source_files") and not claim.get("source_urls"):
            issue(issues, "error", path, run_dir, f"{base}.source_files", "every claim needs source_files or source_urls")


def validate_audit_file(path: Path, run_dir: Path, issues: list[Issue]) -> None:
    data = load_yaml(path, run_dir, issues)
    if data is None or not isinstance(data, dict):
        return
    claims = data.get("audited_claims")
    if not isinstance(claims, list):
        issue(issues, "error", path, run_dir, "audited_claims", "audit must contain audited_claims list")
        return
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            issue(issues, "error", path, run_dir, f"audited_claims[{index}]", "audited claim must be a mapping")
            continue
        base = f"audited_claims[{index}]"
        verdict = str(claim.get("verdict") or "").strip()
        public_use = str(claim.get("public_use") or "").strip()
        validate_enum(issues, path, run_dir, f"{base}.verdict", verdict, VERDICT, severity="error", case_sensitive=True)
        validate_enum(issues, path, run_dir, f"{base}.public_use", public_use, PUBLIC_USE, severity="error")
        if verdict == "PARTIALLY_SUPPORTED" and not claim.get("required_caveat"):
            issue(issues, "error", path, run_dir, f"{base}.required_caveat", "PARTIALLY_SUPPORTED needs required_caveat")
        if verdict in {"UNSUPPORTED", "CONFLICT", "UNKNOWN"} and public_use != "do_not_use":
            issue(issues, "error", path, run_dir, f"{base}.public_use", "blocked verdicts must use do_not_use", public_use)
        if public_use == "usable" and verdict != "SUPPORTED":
            issue(issues, "error", path, run_dir, f"{base}.public_use", "usable requires SUPPORTED verdict", {"verdict": verdict, "public_use": public_use})


def validate_topic_pack_file(path: Path, run_dir: Path, issues: list[Issue]) -> None:
    data = load_yaml(path, run_dir, issues)
    if data is None or not isinstance(data, dict):
        return
    if not data.get("topic_slug"):
        issue(issues, "warning", path, run_dir, "topic_slug", "topic pack should include topic_slug")
    if not isinstance(data.get("source_groups"), dict):
        issue(issues, "warning", path, run_dir, "source_groups", "topic pack should include source_groups mapping")
    if "audited_claim_refs" in data and not isinstance(data.get("audited_claim_refs"), list):
        issue(issues, "warning", path, run_dir, "audited_claim_refs", "audited_claim_refs should be a list")


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    issues: list[Issue] = []
    if not run_dir.exists():
        raise SystemExit(f"run directory not found: {run_dir}")

    for name in REQUIRED_DIRS:
        if not (run_dir / name).exists():
            issue(issues, "error", run_dir / name, run_dir, "$", "required run directory is missing")

    validate_domain_map(run_dir, issues)
    for path in yaml_files(run_dir / "schedule"):
        if path.name != "domain-map.yaml":
            validate_schedule_file(path, run_dir, issues)

    status_counts = {"done": 0, "failed": 0, "other": 0}
    for path in yaml_files(run_dir / "done"):
        validate_done_file(path, run_dir, issues, status_counts)

    for path in yaml_files(run_dir / "inventory"):
        validate_inventory_file(path, run_dir, issues)
    for path in yaml_files(run_dir / "profiles"):
        validate_profile_file(path, run_dir, issues)
    for path in yaml_files(run_dir / "curation"):
        validate_curation_file(path, run_dir, issues)
    for path in yaml_files(run_dir / "claim-ledger"):
        validate_claim_ledger_file(path, run_dir, issues)
    for path in yaml_files(run_dir / "hallucination-audits"):
        validate_audit_file(path, run_dir, issues)
    for path in yaml_files(run_dir / "topic-packs"):
        validate_topic_pack_file(path, run_dir, issues)

    errors = sum(1 for item in issues if item.severity == "error")
    warnings = sum(1 for item in issues if item.severity == "warning")
    warning_fields: dict[str, int] = {}
    warning_paths: dict[str, int] = {}
    for item in issues:
        if item.severity != "warning":
            continue
        grouped_field = field_group(item.field)
        warning_fields[grouped_field] = warning_fields.get(grouped_field, 0) + 1
        warning_paths[item.path] = warning_paths.get(item.path, 0) + 1
    gate_status = "fail" if errors or args.strict and warnings or (args.warning_threshold is not None and warnings > args.warning_threshold) else "pass"
    report = {
        "run_dir": str(run_dir),
        "summary": {
            "gate_status": gate_status,
            "errors": errors,
            "warnings": warnings,
            "checked_files": sum(1 for _ in run_dir.rglob("*") if _.is_file()),
            "done_status": status_counts,
            "top_warning_fields": sorted(warning_fields.items(), key=lambda item: item[1], reverse=True)[:20],
            "top_warning_paths": sorted(warning_paths.items(), key=lambda item: item[1], reverse=True)[:20],
        },
        "issues": [asdict(item) for item in issues],
    }

    if not args.no_write:
        out = run_dir / "logs" / "validation-report.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.safe_dump(report, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
        report["report_path"] = str(out)

    print_report = report
    if not args.all_issues:
        print_report = {
            "run_dir": report["run_dir"],
            "summary": report["summary"],
            "issues": report["issues"][: max(args.max_issues, 0)],
            "issues_truncated": max(0, len(report["issues"]) - max(args.max_issues, 0)),
        }
        if "report_path" in report:
            print_report["report_path"] = report["report_path"]

    if args.json:
        print(json.dumps(print_report, ensure_ascii=False, indent=2))
    else:
        print(yaml.safe_dump(print_report, allow_unicode=True, sort_keys=False, width=120).strip())

    if gate_status == "fail":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
