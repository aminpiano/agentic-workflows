#!/usr/bin/env python3
"""Create a native, dependency-free source index for AI-docs v2."""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
import xml.sax.saxutils
from collections import Counter
from pathlib import Path


DEFAULT_MAX_BYTES = 1_048_576
DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".next",
    ".nuxt",
    ".cache",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".work",
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".venv",
    "venv",
    "__pycache__",
    "vendor",
}

PROFILE_EXCLUDED_TOP_DIRS = {
    "code-first": {
        ".claude",
        ".cass",
        ".codex",
        ".cursor",
        ".github/copilot",
        "ai-docs-old",
        "ai_docs_old",
        "context",
        "contexts",
        "logs",
    },
    "history-aware": {
        ".claude",
        ".cass",
        ".codex",
        ".cursor",
        ".github/copilot",
    },
    "ops-heavy": {
        ".claude",
        ".cass",
        ".codex",
        ".cursor",
        ".github/copilot",
        "ai-docs-old",
        "ai_docs_old",
        "context",
        "contexts",
        "logs",
    },
}

DEFAULT_LOCKFILES = {
    "bun.lock",
    "bun.lockb",
    "cargo.lock",
    "composer.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "yarn.lock",
}

EXISTING_AI_DOCS_KEEP = {
    "ai-docs/ai-project.yaml",
    "ai-docs/README.md",
}

CODE_LANGS = {
    "python",
    "javascript",
    "javascript-react",
    "typescript",
    "typescript-react",
    "go",
    "rust",
    "java",
    "kotlin",
    "ruby",
    "php",
    "csharp",
    "c",
    "c-header",
    "cpp",
    "cpp-header",
    "swift",
}

LANG_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript-react",
    ".ts": "typescript",
    ".tsx": "typescript-react",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".c": "c",
    ".h": "c-header",
    ".cpp": "cpp",
    ".hpp": "cpp-header",
    ".swift": "swift",
    ".sql": "sql",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".md": "markdown",
    ".mdx": "mdx",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".ps1": "powershell",
    ".dockerfile": "dockerfile",
}

SECRET_NAME_HINTS = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.prod",
    ".npmrc",
    ".pypirc",
    ".netrc",
}

SECRET_PART_HINTS = (
    "secret",
    "secrets",
    "credential",
    "credentials",
    "private-key",
    "id_rsa",
    "id_ed25519",
)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def run_git_files(root: Path) -> list[str] | None:
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z", "-co", "--exclude-standard"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return [p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p]


def walk_files(root: Path) -> list[str]:
    result: list[str] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDED_DIRS]
        current_path = Path(current)
        for name in files:
            path = current_path / name
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                continue
            result.append(rel)
    return sorted(result)


def is_secret_candidate(rel_path: str) -> bool:
    parts = [p.lower() for p in Path(rel_path).parts]
    name = parts[-1] if parts else rel_path.lower()
    if name in SECRET_NAME_HINTS:
        return True
    return any(hint in part for part in parts for hint in SECRET_PART_HINTS)


def is_binary(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:8192]
    except OSError:
        return True
    return b"\0" in chunk


def line_count(data: bytes) -> int:
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def language_for(path: str) -> str:
    lower = path.lower()
    if lower.endswith("dockerfile") or "/dockerfile" in lower:
        return "dockerfile"
    suffix = Path(lower).suffix
    return LANG_BY_EXT.get(suffix, suffix[1:] if suffix else "unknown")


def guess_role(path: str, language: str) -> str:
    lower = path.lower()
    name = Path(lower).name
    if name in {"agents.md", "claude.md"} or "copilot-instructions" in lower:
        return "agent-instructions"
    if name in {"package.json", "pyproject.toml", "go.mod", "cargo.toml", "requirements.txt"}:
        return "dependency-manifest"
    if "docker-compose" in name or name == "dockerfile" or "/deploy" in lower or "/infra" in lower:
        return "runtime-ops"
    if language in {"markdown", "mdx"}:
        return "documentation"
    if "/migrations/" in lower or "schema" in name:
        return "schema"
    if "/api/" in lower or "/routes/" in lower or "route." in name or "controller" in name:
        return "api"
    if "/test" in lower or ".test." in name or "_test." in name or ".spec." in name:
        return "test"
    if language in CODE_LANGS and lower.startswith(("backend/", "frontend/", "frontend-admin/", "src/", "app/", "lib/")):
        return "source"
    if language in CODE_LANGS and any(part in Path(lower).parts for part in {"services", "models", "components", "pages", "hooks"}):
        return "source"
    if "/src/" in lower or "/app/" in lower or "/internal/" in lower:
        return "source"
    return "support"


def ignore_record(root: Path, rel_path: str, reason: str) -> dict:
    abs_path = root / rel_path
    try:
        stat = abs_path.stat()
        bytes_value = stat.st_size
    except OSError:
        bytes_value = None
    language = language_for(rel_path)
    return {
        "path": rel_path,
        "bytes": bytes_value,
        "language": language,
        "role_guess": guess_role(rel_path, language),
        "ignored": True,
        "ignore_reason": reason,
        "lines": None,
        "sha256": None,
        "token_estimate": None,
    }


def make_record(root: Path, rel_path: str, max_bytes: int, max_doc_bytes: int) -> dict:
    abs_path = root / rel_path
    stat = abs_path.stat()
    language = language_for(rel_path)
    base = {
        "path": rel_path,
        "bytes": stat.st_size,
        "language": language,
        "role_guess": guess_role(rel_path, language),
        "ignored": False,
        "ignore_reason": None,
    }
    if is_secret_candidate(rel_path):
        return {
            **base,
            "ignored": True,
            "ignore_reason": "secret_candidate",
            "lines": None,
            "sha256": None,
            "token_estimate": None,
        }
    if language in {"markdown", "mdx"} and stat.st_size > max_doc_bytes:
        return {
            **base,
            "ignored": True,
            "ignore_reason": f"large_doc_gt_{max_doc_bytes}",
            "lines": None,
            "sha256": None,
            "token_estimate": None,
        }
    if stat.st_size > max_bytes:
        return {
            **base,
            "ignored": True,
            "ignore_reason": f"large_file_gt_{max_bytes}",
            "lines": None,
            "sha256": None,
            "token_estimate": None,
        }
    if is_binary(abs_path):
        return {
            **base,
            "ignored": True,
            "ignore_reason": "binary_file",
            "lines": None,
            "sha256": None,
            "token_estimate": None,
        }
    data = abs_path.read_bytes()
    return {
        **base,
        "lines": [1, max(1, line_count(data))],
        "sha256": hashlib.sha256(data).hexdigest(),
        "token_estimate": max(1, len(data) // 4),
    }


def load_ai_docsignore(root: Path) -> list[str]:
    path = root / ".ai-docsignore"
    if not path.exists():
        return []
    patterns = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


def matches_pattern(rel_path: str, pattern: str) -> bool:
    normalized = rel_path.strip("/")
    pat = pattern.strip("/")
    if pattern.endswith("/"):
        return normalized == pat or normalized.startswith(pat + "/")
    return fnmatch.fnmatch(normalized, pat) or fnmatch.fnmatch(Path(normalized).name, pat)


def profile_ignore_reason(
    rel_path: str,
    profile: str,
    ignore_patterns: list[str],
    include_history: bool,
    include_existing_ai_docs: bool,
    include_lockfiles: bool,
) -> str | None:
    normalized = rel_path.strip("/")
    parts = Path(normalized).parts
    name = Path(normalized).name.lower()
    for pattern in ignore_patterns:
        if matches_pattern(normalized, pattern):
            return "ai_docsignore"
    if not include_lockfiles and name in DEFAULT_LOCKFILES:
        return "lockfile"
    if not include_history:
        for excluded in PROFILE_EXCLUDED_TOP_DIRS.get(profile, set()):
            if normalized == excluded or normalized.startswith(excluded + "/"):
                return f"profile_excluded:{excluded}"
    if not include_existing_ai_docs and normalized.startswith("ai-docs/") and normalized not in EXISTING_AI_DOCS_KEEP:
        return "existing_ai_docs"
    if len(parts) >= 2 and parts[0].lower() in {"docs", "seogo"} and parts[1].lower() in {"archive", "archives", "old"}:
        return "archive_docs"
    return None


def is_internal_ai_docs_work(rel_path: str) -> bool:
    parts = Path(rel_path).parts
    return len(parts) >= 2 and parts[0] == "ai-docs" and parts[1] == ".work"


def write_yaml_inventory(path: Path, index: dict) -> None:
    stats = index["stats"]
    lines = [
        "version: 2",
        f"generated_at: {index['generated_at']}",
        f"root: {json.dumps(index['root'])}",
        "stats:",
        f"  total_files: {stats['total_files']}",
        f"  indexed_files: {stats['indexed_files']}",
        f"  ignored_files: {stats['ignored_files']}",
        f"  total_bytes: {stats['total_bytes']}",
        f"  indexed_lines: {stats['indexed_lines']}",
        "languages:",
    ]
    for key, value in stats["languages"].items():
        lines.append(f"  {json.dumps(key)}: {value}")
    lines.append("roles:")
    for key, value in stats["roles"].items():
        lines.append(f"  {json.dumps(key)}: {value}")
    lines.append("ignored:")
    for record in index["ignored"]:
        lines.append(f"  - path: {json.dumps(record['path'])}")
        lines.append(f"    reason: {json.dumps(record['ignore_reason'])}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_pack_xml(path: Path, root: Path, records: list[dict]) -> None:
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', "<repository>"]
    for record in records:
        if record["ignored"]:
            continue
        rel = record["path"]
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        parts.append(
            f'<file path="{xml.sax.saxutils.escape(rel)}" '
            f'lines="{record["lines"][0]}-{record["lines"][1]}" '
            f'sha256="{record["sha256"]}">'
        )
        parts.append(xml.sax.saxutils.escape(text))
        parts.append("</file>")
    parts.append("</repository>")
    path.write_text("\n".join(parts), encoding="utf-8")


def build_index(
    root: Path,
    max_bytes: int,
    max_doc_bytes: int,
    profile: str,
    include_history: bool,
    include_existing_ai_docs: bool,
    include_lockfiles: bool,
) -> dict:
    file_list = run_git_files(root)
    source = "git-ls-files" if file_list is not None else "os-walk"
    if file_list is None:
        file_list = walk_files(root)
    ignore_patterns = load_ai_docsignore(root)
    records: list[dict] = []
    for rel in sorted(dict.fromkeys(file_list)):
        abs_path = root / rel
        if not abs_path.is_file():
            continue
        if is_internal_ai_docs_work(rel):
            continue
        if any(part in DEFAULT_EXCLUDED_DIRS for part in Path(rel).parts):
            continue
        ignore_reason = profile_ignore_reason(
            rel,
            profile,
            ignore_patterns,
            include_history,
            include_existing_ai_docs,
            include_lockfiles,
        )
        if ignore_reason:
            records.append(ignore_record(root, rel, ignore_reason))
            continue
        try:
            records.append(make_record(root, rel, max_bytes, max_doc_bytes))
        except OSError as exc:
            records.append(
                {
                    "path": rel,
                    "bytes": None,
                    "language": language_for(rel),
                    "role_guess": "unreadable",
                    "ignored": True,
                    "ignore_reason": f"read_error:{exc.__class__.__name__}",
                    "lines": None,
                    "sha256": None,
                    "token_estimate": None,
                }
            )

    indexed = [r for r in records if not r["ignored"]]
    ignored = [r for r in records if r["ignored"]]
    stats = {
        "total_files": len(records),
        "indexed_files": len(indexed),
        "ignored_files": len(ignored),
        "total_bytes": sum((r.get("bytes") or 0) for r in records),
        "indexed_lines": sum((r["lines"][1] if r.get("lines") else 0) for r in indexed),
        "languages": dict(sorted(Counter(r["language"] for r in indexed).items())),
        "roles": dict(sorted(Counter(r["role_guess"] for r in indexed).items())),
    }
    return {
        "version": 2,
        "kind": "ai-docs-native-source-index",
        "generated_at": now_iso(),
        "root": str(root),
        "source": source,
        "profile": profile,
        "max_bytes": max_bytes,
        "max_doc_bytes": max_doc_bytes,
        "ignore_patterns": ignore_patterns,
        "stats": stats,
        "files": {r["path"]: r for r in indexed},
        "ignored": ignored,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", nargs="?", default=".")
    parser.add_argument("--out-dir", help="Output directory. Defaults to ai-docs/.work/<timestamp>/source-index")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--max-doc-bytes", type=int, default=120_000)
    parser.add_argument("--profile", choices=["code-first", "history-aware", "ops-heavy"], default="code-first")
    parser.add_argument("--include-history", action="store_true", help="Include context/history directories excluded by the selected profile")
    parser.add_argument("--include-existing-ai-docs", action="store_true", help="Include existing ai-docs markdown as source material")
    parser.add_argument("--include-lockfiles", action="store_true", help="Include package/dependency lockfiles")
    parser.add_argument("--pack-xml", action="store_true", help="Also write pack.xml for LLM packet export")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    if not root.exists():
        print(f"Project root does not exist: {root}", file=sys.stderr)
        return 2
    if args.out_dir:
        out_dir = Path(args.out_dir).resolve()
    else:
        run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S-v2")
        out_dir = root / "ai-docs" / ".work" / run_id / "source-index"
    out_dir.mkdir(parents=True, exist_ok=True)

    index = build_index(
        root,
        args.max_bytes,
        args.max_doc_bytes,
        args.profile,
        args.include_history,
        args.include_existing_ai_docs,
        args.include_lockfiles,
    )
    records = list(index["files"].values()) + index["ignored"]

    (out_dir / "index-final.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with (out_dir / "files.ndjson").open("w", encoding="utf-8") as fh:
        for record in sorted(records, key=lambda item: item["path"]):
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    (out_dir / "stats.json").write_text(
        json.dumps(index["stats"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_yaml_inventory(out_dir / "source-inventory.yaml", index)
    if args.pack_xml:
        write_pack_xml(out_dir / "pack.xml", root, records)

    print(json.dumps({"out_dir": str(out_dir), "stats": index["stats"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
