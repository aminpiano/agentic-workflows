#!/usr/bin/env python3
"""Canonical contract — single source of truth for authority-research artifacts.

Consumed by validators (membership checks), the normalizer (alias mapping),
the public-material gate, the synthesis-quality report, the run dashboard,
measure scripts, init_run, and worker-prompt rendering. Every enum, status,
public-use bucket, verdict, and run-layout directory is defined here exactly
once so the pipeline cannot drift the way it did before (gate vs synthesis
counting public_use differently, three copies of the status-alias table,
`drafted`/Phase-2 dirs present in some scripts and missing in others).

BOUNDARY (P0 design rule — do not cross):
  This module declares WHICH values are valid and applies DETERMINISTIC
  alias tables only. It must NEVER extract claims, infer a verdict, judge
  evidence strength, decide public-use from content, or interpret meaning
  in any way. Validators check set membership; the normalizer maps known
  aliases to canonical values; nothing here reads a claim and decides what
  it means. Semantic judgment stays in the worker prompts and human review.
  The fuzzy, run-specific heuristics (free-text temporal phrasings, keyword
  angle inference, prefix fallbacks) deliberately stay in normalize_run.py;
  only their canonical *targets* are anchored here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "1.0"

# ── claim verdict ───────────────────────────────────────────────────────────
VERDICT = frozenset({"SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONFLICT", "UNKNOWN"})
# Stable display order for reports/gates that iterate verdicts.
VERDICT_ORDER = ("SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONFLICT", "UNKNOWN")

# ── public use ──────────────────────────────────────────────────────────────
PUBLIC_USE = frozenset({"usable", "usable_with_caveat", "do_not_use"})
PUBLIC_USE_ORDER = ("usable", "usable_with_caveat", "do_not_use")
# Bucket label for public_use values outside the vocabulary; gate and synthesis
# surface these separately instead of silently folding them into do_not_use.
UNRECOGNIZED_PUBLIC_USE = "_unrecognized"

# ── task / schedule status ──────────────────────────────────────────────────
DONE_STATUS = frozenset({"done", "failed"})
SCHEDULE_STATUS = frozenset({"pending", "running", "done", "failed", "skipped"})
# The only alias table that was duplicated across validate_run / measure_run /
# measure_curation. Single home now.
STATUS_ALIASES = {"completed": "done", "complete": "done"}

# ── workers ─────────────────────────────────────────────────────────────────
# Distinct concepts kept distinct: WORKER is the schedule task executor;
# RECOMMENDED_WORKER is the suggestion attached to a source during profiling;
# AXIS_WORKER is the human-pickable subset on a domain-map axis.
WORKER = frozenset({"codex", "agy", "either", "codex-subagent", "claude-agent", "workflow"})
RECOMMENDED_WORKER = frozenset({"codex", "agy", "either", "collector"})
AXIS_WORKER = frozenset({"codex", "agy", "either"})

# ── priority / value ────────────────────────────────────────────────────────
PRIORITY = frozenset({"critical", "high", "medium", "low"})
LIKELY_VALUE = frozenset({"high", "medium", "low"})

# ── source / claim metadata enums ───────────────────────────────────────────
TRUST_GRADE = frozenset({"S", "A", "B", "C", "D", "UNKNOWN"})
INFO_ANGLE = frozenset({
    "origin_primary",
    "academic_evidence",
    "implementation_artifact",
    "practitioner_ops",
    "comparative_industry",
    "critical_risk",
})
TEMPORAL_POSITION = frozenset({"foundational", "current", "frontier", "deprecated", "UNKNOWN"})
TOPIC_RELATION = frozenset({"core", "adjacent", "historical", "counterframe"})
SOURCE_SCALE = frozenset({"point", "collection", "mega"})
SOURCE_ROLE = frozenset({"primary", "secondary", "derivative", "index"})
DERIVATIVE_RISK = frozenset({"low", "medium", "high"})
# `collect` is NOT canonical: the normalizer maps collect→profile. Validators
# should check the canonical set (post-normalize values never contain collect).
PREFERRED_ACTION = frozenset({"profile", "expand_children", "use_as_index_only", "skip"})
PARSE_FEASIBILITY = frozenset({"easy", "medium", "hard", "unknown"})
ACCESS_METHOD = frozenset({"search", "sitemap", "rss", "list_pages", "site_search", "manual_web", "api", "unknown"})

# ── deterministic alias tables (used by the normalize step) ─────────────────
# Only the simple, stable representational aliases live here. Free-text and
# heuristic mappings stay in normalize_run.py (see BOUNDARY note above).
TRUST_ALIASES = {
    "s": "S", "a": "A", "a-": "A", "a+": "A",
    "b": "B", "b+": "B", "b-": "B", "c": "C", "d": "D",
    "unknown": "UNKNOWN",
}
# Alias keys validators must also ACCEPT as input (a run may be checked before
# normalize_run.py collapses them); each maps to a canonical value.
PREFERRED_ACTION_ALIASES = {"collect": "profile"}
ACCESS_METHOD_ALIASES = {"direct_html": "manual_web"}

# ── run layout ──────────────────────────────────────────────────────────────
# Phase 1 = source collection → verification. Phase 2 = curation → synthesis.
# Ordered tuples: pipeline order is meaningful (dashboards, measure progress).
PHASE1_DIRS = (
    "inventory", "profiles", "schedule", "raw", "triaged", "rejected",
    "classified", "verified", "drafted", "done", "logs", "prompts",
)
PHASE2_DIRS = (
    "curation", "claim-ledger", "hallucination-audits", "topic-packs",
    "article-briefs", "synthesis", "dedup",
)
ALL_DIRS = PHASE1_DIRS + PHASE2_DIRS

# ── schedule files ──────────────────────────────────────────────────────────
# Two rules that exist because breaking either one silently destroys the only
# record of what was supposed to run:
#
# 1. Schedules ACCUMULATE. Re-running a phase writes a new wave file instead of
#    overwriting the previous one. `done/` markers accumulate forever, so if a
#    schedule is overwritten its finished tasks become unattributable orphans
#    and completion can no longer be computed for that run at all.
# 2. Schedules are identified by SHAPE, not by folder or filename. `schedule/`
#    also holds the domain map, axis candidates, and the completeness review —
#    documents with entirely different schemas. Validating those as schedules
#    (or counting their ids as tasks) produces nonsense.
SCHEDULE_STEM = "-schedule"


def is_schedule_doc(doc: Any) -> bool:
    """True if a parsed YAML document is a work schedule.

    Shape check only: a schedule is a mapping carrying a `tasks` list. No
    filename guessing, no content interpretation.
    """
    return isinstance(doc, dict) and isinstance(doc.get("tasks"), list)


def schedule_filename(phase: str, wave: int = 1) -> str:
    """Filename for a phase's schedule at a given wave.

    Wave 1 keeps the historical `<phase>-schedule.yaml` name so runs created
    before waves existed stay readable by the same globs.
    """
    if wave < 1:
        raise ValueError(f"wave must be >= 1, got {wave}")
    return f"{phase}{SCHEDULE_STEM}.yaml" if wave == 1 else f"{phase}{SCHEDULE_STEM}-w{wave}.yaml"


def next_schedule_path(schedule_dir: Path, phase: str) -> Path:
    """Path for a NEW schedule of `phase`, never overwriting an existing one.

    Touches the filesystem (existence only) to pick the next free wave — it
    applies the naming rule above rather than interpreting any content, so it
    stays inside this module's boundary.
    """
    wave = 1
    while True:
        candidate = schedule_dir / schedule_filename(phase, wave)
        if not candidate.exists():
            return candidate
        wave += 1


# ── helpers ─────────────────────────────────────────────────────────────────
def normalize_status(value: Any) -> Any:
    """Map a status alias (completed/complete) to its canonical form.

    Returns the value unchanged if it is not a known alias. Deterministic —
    no inference. Mirrors the historical exact-key behaviour (no lowercasing)
    to avoid any behaviour change during the P0 migration.
    """
    return STATUS_ALIASES.get(value, value)


def apply_alias(value: Any, aliases: dict[str, str]) -> Any:
    """Look up a lowercased/stripped value in an alias table; passthrough on miss."""
    if value is None:
        return value
    key = str(value).strip().strip('"').strip("'").lower()
    return aliases.get(key, value)


def is_member(value: Any, canonical: Iterable[str]) -> bool:
    """True if value is in the canonical set. Pure membership, no coercion."""
    return value in canonical


def _check_invariants() -> None:
    """Fail fast at import time if an alias target is not a canonical value.

    This is what makes the contract a single source of truth: an alias can
    never point at a value the validators would reject.
    """
    assert set(STATUS_ALIASES.values()) <= DONE_STATUS, "status alias target outside DONE_STATUS"
    assert set(TRUST_ALIASES.values()) <= TRUST_GRADE, "trust alias target outside TRUST_GRADE"
    assert set(PREFERRED_ACTION_ALIASES.values()) <= PREFERRED_ACTION, "preferred-action alias target outside PREFERRED_ACTION"
    assert set(ACCESS_METHOD_ALIASES.values()) <= ACCESS_METHOD, "access-method alias target outside ACCESS_METHOD"
    assert AXIS_WORKER <= WORKER, "AXIS_WORKER not a subset of WORKER"
    assert set(VERDICT_ORDER) == set(VERDICT), "VERDICT_ORDER and VERDICT disagree"
    assert set(PUBLIC_USE_ORDER) == set(PUBLIC_USE), "PUBLIC_USE_ORDER and PUBLIC_USE disagree"
    assert len(set(ALL_DIRS)) == len(ALL_DIRS), "duplicate directory in run layout"


_check_invariants()
