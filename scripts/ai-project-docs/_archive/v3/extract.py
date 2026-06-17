#!/usr/bin/env python3
"""Deterministic literal extraction for AI-docs v3.

Language-aware regex extraction of the *facts* the model is allowed to assert
deterministically (decision 3): signatures, routes, imports, env keys, job
schedule literals, table definitions. No AST, no parsing, stdlib only.

Each extractor yields anchor dicts. The indexer turns anchors into anchors.ndjson
plus deterministic entity/edge candidates. LLM workers enrich; they never invent
structure without a support anchor (Invariant 2).
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath


# ---- signatures ----------------------------------------------------------

SIG_PATTERNS = {
    "python": [
        re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\("),
        re.compile(r"^\s*class\s+([A-Za-z_]\w*)"),
    ],
    "javascript": [
        re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)"),
        re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_]\w*)"),
        re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?\("),
    ],
    "go": [
        re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\("),
        re.compile(r"^type\s+([A-Za-z_]\w*)\s+struct"),
        re.compile(r"^type\s+([A-Za-z_]\w*)\s+interface"),
    ],
    "rust": [
        re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)"),
        re.compile(r"^\s*(?:pub\s+)?struct\s+([A-Za-z_]\w*)"),
        re.compile(r"^\s*(?:pub\s+)?enum\s+([A-Za-z_]\w*)"),
        re.compile(r"^\s*(?:pub\s+)?trait\s+([A-Za-z_]\w*)"),
    ],
}
SIG_PATTERNS["typescript"] = SIG_PATTERNS["javascript"]
SIG_PATTERNS["javascript-react"] = SIG_PATTERNS["javascript"]
SIG_PATTERNS["typescript-react"] = SIG_PATTERNS["javascript"]


# ---- routes --------------------------------------------------------------

ROUTE_PATTERNS = {
    "python": [
        # decorator routes only (FastAPI/Flask): @app.get("/"), @router.post("/x"), @bp.route("/y")
        re.compile(r"@\s*\w+\.(get|post|put|patch|delete|route)\s*\(\s*[\"']([^\"']+)[\"']", re.IGNORECASE),
        re.compile(r"\.add_url_rule\s*\(\s*[\"']([^\"']+)[\"']"),
        re.compile(r"\.add_api_route\s*\(\s*[\"']([^\"']+)[\"']"),
    ],
    "javascript": [
        re.compile(r"\b(?:app|router|api|server)\.(get|post|put|patch|delete|use|all)\s*\(\s*[\"'`]([^\"'`]+)", re.IGNORECASE),
        re.compile(r"\.route\s*\(\s*[\"'`]([^\"'`]+)", re.IGNORECASE),
    ],
    "go": [
        re.compile(r"\.(GET|POST|PUT|PATCH|DELETE|Handle|HandleFunc)\s*\(\s*[\"']([^\"']+)[\"']"),
    ],
}
ROUTE_PATTERNS["typescript"] = ROUTE_PATTERNS["javascript"]
ROUTE_PATTERNS["javascript-react"] = ROUTE_PATTERNS["javascript"]
ROUTE_PATTERNS["typescript-react"] = ROUTE_PATTERNS["javascript"]

# Multi-line decorator openers: `@router.post(` with the path literal on a FOLLOWING line
# (common FastAPI style with many kwargs). Pure line-scanning misses these, which both drops
# the route from blueprint_facts AND denies the endpoint file its +3 route tier score — so the
# file falls to `defer` and the planner never sees it. Detect the opener, then take the first
# string literal on the next few lines as the path.
ROUTE_DECORATOR_OPEN = {
    "python": re.compile(r"@\s*\w+\.(get|post|put|patch|delete|route)\s*\(\s*$", re.IGNORECASE),
}


# ---- imports -------------------------------------------------------------

IMPORT_PATTERNS = {
    "python": [
        re.compile(r"^\s*from\s+([.\w]+)\s+import\s+"),
        re.compile(r"^\s*import\s+([.\w]+)"),
    ],
    "javascript": [
        re.compile(r"^\s*import\s+(?:.+?\s+from\s+)?[\"']([^\"']+)[\"']"),
        re.compile(r"\brequire\s*\(\s*[\"']([^\"']+)[\"']\s*\)"),
        re.compile(r"^\s*export\s+(?:\*|\{[^}]*\})\s+from\s+[\"']([^\"']+)[\"']"),
    ],
    "go": [
        re.compile(r"^\s*[\"']([\w./-]+)[\"']\s*$"),  # inside import ( ... ) block
    ],
    "rust": [
        re.compile(r"^\s*(?:pub\s+)?use\s+([\w:]+)"),
    ],
}
IMPORT_PATTERNS["typescript"] = IMPORT_PATTERNS["javascript"]
IMPORT_PATTERNS["javascript-react"] = IMPORT_PATTERNS["javascript"]
IMPORT_PATTERNS["typescript-react"] = IMPORT_PATTERNS["javascript"]


# ---- env keys ------------------------------------------------------------

ENV_PATTERNS = {
    "python": [
        re.compile(r"os\.environ(?:\.get)?\s*[\(\[]\s*[\"']([A-Z][A-Z0-9_]+)[\"']"),
        re.compile(r"os\.getenv\s*\(\s*[\"']([A-Z][A-Z0-9_]+)[\"']"),
        re.compile(r"getenv\s*\(\s*[\"']([A-Z][A-Z0-9_]+)[\"']"),
    ],
    "javascript": [
        re.compile(r"process\.env\.([A-Z][A-Z0-9_]+)"),
        re.compile(r"process\.env\[\s*[\"']([A-Z][A-Z0-9_]+)[\"']"),
    ],
    "go": [
        re.compile(r"os\.Getenv\s*\(\s*[\"']([A-Z][A-Z0-9_]+)[\"']"),
    ],
}
ENV_PATTERNS["typescript"] = ENV_PATTERNS["javascript"]
ENV_PATTERNS["javascript-react"] = ENV_PATTERNS["javascript"]
ENV_PATTERNS["typescript-react"] = ENV_PATTERNS["javascript"]


# ---- job schedule literals ----------------------------------------------

JOB_PATTERNS = [
    re.compile(r"@(?:scheduled|cron|periodic_task|shared_task|repeat)\b", re.IGNORECASE),
    re.compile(r"\bCronTrigger\b"),
    re.compile(r"\bschedule\.every\b"),
    re.compile(r"\bnode-cron\b|\bcron\.schedule\b"),
    # explicit cron expression literal, e.g. cron: "0 3 * * *" (not bare setInterval — too noisy in UI code)
    re.compile(r"cron\s*[:=]\s*[\"']([\d*/, \-]+)[\"']"),
]

# ---- table definitions ---------------------------------------------------

TABLE_PATTERNS = [
    re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`]?([A-Za-z_]\w*)", re.IGNORECASE),
    re.compile(r"__tablename__\s*=\s*[\"']([A-Za-z_]\w*)[\"']"),
]


# ---- constraints (DB + ORM) — audit ground truth -------------------------
# (kind, label) pairs; first match per line wins. These let the audit answer
# "is there actually a unique index / FK on X?" deterministically.

CONSTRAINT_PATTERNS = {
    "sql": [
        (re.compile(r"\bPRIMARY\s+KEY\b", re.IGNORECASE), "primary_key"),
        (re.compile(r"\bFOREIGN\s+KEY\b|\bREFERENCES\b", re.IGNORECASE), "foreign_key"),
        (re.compile(r"\bUNIQUE\b", re.IGNORECASE), "unique"),
        (re.compile(r"\bCHECK\s*\(", re.IGNORECASE), "check"),
        (re.compile(r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\b", re.IGNORECASE), "index"),
    ],
    "python": [
        (re.compile(r"\bprimary_key\s*=\s*True\b"), "primary_key"),
        (re.compile(r"\bForeignKey\s*\(|\bForeignKeyConstraint\s*\("), "foreign_key"),
        (re.compile(r"\bUniqueConstraint\s*\(|\bunique\s*=\s*True\b|\bunique_together\b"), "unique"),
        (re.compile(r"\bCheckConstraint\s*\("), "check"),
        (re.compile(r"\bIndex\s*\(|\bindex\s*=\s*True\b"), "index"),
    ],
    "javascript": [
        (re.compile(r"@Unique\s*\(|\bunique\s*:\s*true\b"), "unique"),
        (re.compile(r"@Index\s*\("), "index"),
        (re.compile(r"@PrimaryColumn|@PrimaryGeneratedColumn"), "primary_key"),
        (re.compile(r"@ManyToOne|@OneToMany|@OneToOne|@ManyToMany|@JoinColumn"), "foreign_key"),
    ],
}
CONSTRAINT_PATTERNS["typescript"] = CONSTRAINT_PATTERNS["javascript"]
CONSTRAINT_PATTERNS["javascript-react"] = CONSTRAINT_PATTERNS["javascript"]
CONSTRAINT_PATTERNS["typescript-react"] = CONSTRAINT_PATTERNS["javascript"]


# ---- middleware registration ---------------------------------------------

MIDDLEWARE_PATTERNS = {
    "python": [
        re.compile(r"\.add_middleware\s*\(\s*([A-Za-z_][\w.]*)"),
        re.compile(r"app\.middleware\s*\(\s*[\"']([^\"']+)[\"']"),
    ],
    "javascript": [
        re.compile(r"\b(?:app|router|server)\.use\s*\(\s*([A-Za-z_][\w.]*)"),
    ],
}
MIDDLEWARE_PATTERNS["typescript"] = MIDDLEWARE_PATTERNS["javascript"]
MIDDLEWARE_PATTERNS["javascript-react"] = MIDDLEWARE_PATTERNS["javascript"]
MIDDLEWARE_PATTERNS["typescript-react"] = MIDDLEWARE_PATTERNS["javascript"]


def _short(line: str, limit: int = 120) -> str:
    return line.strip()[:limit]


def _emit(path, line_no, kind, anchor_text, extra=None):
    rec = {
        "path": path,
        "anchor_line": line_no,
        "kind": kind,
        "anchor_text": anchor_text,
    }
    if extra:
        rec.update(extra)
    return rec


def extract_file(rel_path: str, language: str, text: str) -> list[dict]:
    """Return a list of raw anchor records (no id/sha yet) for one file."""
    out: list[dict] = []
    lines = text.splitlines()
    sig_pats = SIG_PATTERNS.get(language, [])
    route_pats = ROUTE_PATTERNS.get(language, [])
    import_pats = IMPORT_PATTERNS.get(language, [])
    env_pats = ENV_PATTERNS.get(language, [])
    is_sql = language == "sql"
    in_go_import = False

    for i, raw in enumerate(lines, start=1):
        # routes — inline: @router.get("/x")
        route_hit = False
        for pat in route_pats:
            m = pat.search(raw)
            if m:
                groups = [g for g in m.groups() if g]
                path_lit = groups[-1] if groups else raw.strip()
                method = groups[0].upper() if len(groups) >= 2 else "ANY"
                out.append(_emit(rel_path, i, "route", path_lit,
                                 {"method": method, "route_path": path_lit}))
                route_hit = True
                break
        # routes — multi-line: @router.post(\n  "/x", ...): path is on a later line
        if not route_hit:
            dec = ROUTE_DECORATOR_OPEN.get(language)
            md = dec.search(raw) if dec else None
            if md:
                method = md.group(1).upper()
                for j in range(i, min(i + 6, len(lines))):
                    ps = re.search(r"[\"']([^\"']+)[\"']", lines[j])
                    if ps:
                        out.append(_emit(rel_path, i, "route", ps.group(1),
                                         {"method": method, "route_path": ps.group(1)}))
                        break
        # signatures
        for pat in sig_pats:
            m = pat.match(raw)
            if m:
                name = m.group(1)
                kw = "class" if "class" in raw or "struct" in raw or "interface" in raw or "trait" in raw or ("type " in raw and language == "go") or ("enum" in raw and language == "rust") else "def"
                anchor_text = _short(raw)
                out.append(_emit(rel_path, i, "signature", anchor_text,
                                 {"symbol": name, "sig_kind": "class" if kw == "class" else "func"}))
                break
        # imports
        if language == "go":
            if re.match(r"^\s*import\s*\(", raw):
                in_go_import = True
                continue
            if in_go_import and ")" in raw:
                in_go_import = False
            single = re.match(r'^\s*import\s+(?:\w+\s+)?[\"\']([\w./-]+)[\"\']', raw)
            if single:
                out.append(_emit(rel_path, i, "import", single.group(1), {"import_target": single.group(1)}))
            elif in_go_import:
                m = IMPORT_PATTERNS["go"][0].match(raw)
                if m:
                    out.append(_emit(rel_path, i, "import", m.group(1), {"import_target": m.group(1)}))
        else:
            for pat in import_pats:
                m = pat.search(raw)
                if m:
                    target = m.group(1)
                    out.append(_emit(rel_path, i, "import", target, {"import_target": target}))
                    break
        # env keys
        for pat in env_pats:
            for m in pat.finditer(raw):
                key = m.group(1)
                out.append(_emit(rel_path, i, "env", key, {"env_key": key}))
        # jobs
        for pat in JOB_PATTERNS:
            if pat.search(raw):
                out.append(_emit(rel_path, i, "job", _short(raw), {}))
                break
        # tables
        if is_sql or language == "python":
            for pat in TABLE_PATTERNS:
                m = pat.search(raw)
                if m:
                    out.append(_emit(rel_path, i, "table", m.group(1), {"table_name": m.group(1)}))
                    break
        # constraints (DB + ORM) — deterministic audit ground truth.
        # No break: a single line can carry several (PRIMARY KEY + UNIQUE + REFERENCES);
        # emit one anchor per distinct kind so the audit sees them all.
        cpats = CONSTRAINT_PATTERNS.get("sql" if is_sql else language, [])
        seen_ck = set()
        for pat, ckind in cpats:
            if ckind not in seen_ck and pat.search(raw):
                out.append(_emit(rel_path, i, "constraint", _short(raw), {"constraint_kind": ckind}))
                seen_ck.add(ckind)
        # middleware registration
        for pat in MIDDLEWARE_PATTERNS.get(language, []):
            m = pat.search(raw)
            if m:
                name = m.group(1) if m.groups() else _short(raw)
                out.append(_emit(rel_path, i, "middleware", name, {"mw_name": name}))
                break

    return out


# ---- import resolution (best-effort, same-repo only) ---------------------

def resolve_python_import(target: str, importer: str, repo_files: set[str]) -> str | None:
    """Resolve a python import target to a same-repo file path, best effort."""
    t = target.lstrip(".")
    if not t:
        return None
    rel = t.replace(".", "/")
    candidates = [f"{rel}.py", f"{rel}/__init__.py"]
    # relative import: resolve against importer's package
    if target.startswith("."):
        base = PurePosixPath(importer).parent
        up = len(target) - len(target.lstrip("."))
        for _ in range(max(0, up - 1)):
            base = base.parent
        rel2 = (base / t.replace(".", "/")).as_posix()
        candidates = [f"{rel2}.py", f"{rel2}/__init__.py"] + candidates
    for c in candidates:
        if c in repo_files:
            return c
    # also try basename match under any dir
    for c in candidates:
        name = PurePosixPath(c).name
        for f in repo_files:
            if f.endswith("/" + name) and f.endswith(c.split("/")[-1]):
                return f
    return None


def resolve_js_import(target: str, importer: str, repo_files: set[str]) -> str | None:
    if not target.startswith("."):
        return None  # bare package = external
    base = PurePosixPath(importer).parent
    joined = (base / target).as_posix()
    # normalize ../ ./
    parts: list[str] = []
    for seg in joined.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    stem = "/".join(parts)
    exts = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]
    candidates = [stem] + [stem + e for e in exts] + [stem + "/index" + e for e in exts]
    for c in candidates:
        if c in repo_files:
            return c
    return None


def resolve_import(language: str, target: str, importer: str, repo_files: set[str]) -> str | None:
    if language == "python":
        return resolve_python_import(target, importer, repo_files)
    if language in ("javascript", "typescript", "javascript-react", "typescript-react"):
        return resolve_js_import(target, importer, repo_files)
    return None
