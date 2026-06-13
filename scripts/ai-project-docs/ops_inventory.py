#!/usr/bin/env python3
"""Collect read-only production/ops hints for AI-docs v2."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
from pathlib import Path


MAX_TEXT_BYTES = 262_144
SECRET_VALUE_RE = re.compile(
    r"(?i)(password|passwd|pwd|secret|token|api[_-]?key|stream[_-]?key|private[_-]?key|cookie|session)\s*[:=]\s*([^\s\"']+)"
)
ENV_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")
PORT_RE = re.compile(r"(?m)(?:^|\s|['\"])(\d{2,5})\s*:\s*(\d{2,5})(?:/tcp|/udp)?")
URL_HOST_RE = re.compile(r"\b(?:https?://)?([a-zA-Z0-9][a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(?::\d{2,5})?\b")
FILELIKE_DOMAIN_SUFFIXES = (
    ".conf",
    ".crt",
    ".db",
    ".exe",
    ".bat",
    ".git",
    ".js",
    ".json",
    ".key",
    ".log",
    ".md",
    ".pem",
    ".py",
    ".service",
    ".sh",
    ".so",
    ".target",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
)
DOMAIN_TLD_BLOCKLIST = {
    "bat",
    "conf",
    "crt",
    "db",
    "exe",
    "exports",
    "git",
    "head",
    "html",
    "js",
    "json",
    "key",
    "log",
    "md",
    "origin",
    "pem",
    "platform",
    "py",
    "service",
    "sh",
    "so",
    "target",
    "ts",
    "tsx",
    "txt",
    "yaml",
    "yml",
}
PLACEHOLDER_HOSTS = {"your-server.com", "example.com", "example.org", "example.net"}

OPS_PATTERNS = (
    "docker-compose",
    "compose.",
    "dockerfile",
    ".service",
    ".timer",
    "systemd",
    "nginx",
    "traefik",
    "caddyfile",
    "caddy.",
    "procfile",
    "supervisord",
    "ecosystem.config",
    "pm2",
    "deploy",
    "infra",
    ".github/workflows",
    ".env",
)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def line_count(data: bytes) -> int:
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def git_files(root: Path) -> list[str] | None:
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
    skip = {".git", "node_modules", ".venv", "venv", ".work", "dist", "build", ".next"}
    result: list[str] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip]
        for name in files:
            path = Path(current) / name
            try:
                result.append(path.relative_to(root).as_posix())
            except ValueError:
                continue
    return sorted(result)


def is_markdown(path: str) -> bool:
    return Path(path.lower()).suffix in {".md", ".mdx"}


def is_ops_candidate(path: str, include_ops_docs: bool = False) -> bool:
    lower = path.lower()
    if is_markdown(path) and not include_ops_docs:
        return False
    return any(pattern in lower for pattern in OPS_PATTERNS)


def safe_read(path: Path) -> bytes:
    data = path.read_bytes()
    return data[:MAX_TEXT_BYTES]


def redact(text: str) -> str:
    return SECRET_VALUE_RE.sub(lambda match: f"{match.group(1)}=<redacted>", text)


def classify_file(path: str) -> str:
    lower = path.lower()
    name = Path(lower).name
    if is_markdown(path):
        return "ops-doc"
    if "docker-compose" in lower or "compose." in lower:
        return "docker-compose"
    if name == "dockerfile" or name.endswith(".dockerfile"):
        return "dockerfile"
    if lower.endswith(".service") or lower.endswith(".timer") or "systemd" in lower:
        return "systemd"
    if "traefik" in lower:
        return "traefik"
    if "nginx" in lower:
        return "nginx"
    if "caddy" in lower:
        return "caddy"
    if ".github/workflows" in lower:
        return "ci-workflow"
    if name.startswith(".env") or ".env" in name:
        return "env-file"
    if "deploy" in lower or "infra" in lower:
        return "deploy-infra"
    return "ops"


def first_anchor(text: str, fallback: str) -> tuple[str, int | None]:
    for idx, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:160], idx
    return fallback, None


def extract_env_keys(text: str) -> list[str]:
    keys = []
    for line in text.splitlines():
        match = ENV_LINE_RE.match(line)
        if match:
            keys.append(match.group(1))
    return sorted(set(keys))


def extract_ports(text: str) -> list[str]:
    ports = []
    for left, right in PORT_RE.findall(text):
        left_int = int(left)
        right_int = int(right)
        if left_int > 65535 or right_int > 65535:
            continue
        # Avoid treating clock-like prose such as 12:00 as a port mapping.
        if right_int == 0 and left_int <= 24:
            continue
        ports.append(f"{left}:{right}")
    return sorted(set(ports))


def extract_domains(text: str) -> list[str]:
    domains = []
    for host in URL_HOST_RE.findall(text):
        lowered = host.lower()
        if ".." in lowered:
            continue
        if lowered in PLACEHOLDER_HOSTS or lowered.endswith((".local", ".example")):
            continue
        tld = lowered.rsplit(".", 1)[-1]
        if tld in DOMAIN_TLD_BLOCKLIST:
            continue
        if lowered.endswith(FILELIKE_DOMAIN_SUFFIXES):
            continue
        if lowered.count(".") == 1 and lowered.rsplit(".", 1)[1] in {"js", "ts", "py", "md", "log", "json", "yaml", "yml"}:
            continue
        domains.append(lowered)
    return sorted(set(domains))


def should_extract_network_hints(kind: str) -> bool:
    return kind in {
        "docker-compose",
        "nginx",
        "traefik",
        "caddy",
        "ci-workflow",
        "env-file",
        "deploy-infra",
        "ops",
    }


def inspect_ops_file(root: Path, rel_path: str) -> dict:
    path = root / rel_path
    data = safe_read(path)
    text = redact(data.decode("utf-8", "replace"))
    kind = classify_file(rel_path)
    env_keys = extract_env_keys(text) if kind == "env-file" else []
    if kind == "env-file" and env_keys:
        first_key = env_keys[0]
        anchor = f"{first_key}="
        anchor_line = next(
            (idx for idx, line in enumerate(text.splitlines(), start=1) if line.lstrip().startswith(anchor)),
            None,
        )
    else:
        anchor, anchor_line = first_anchor(text, rel_path)
    network_hints = should_extract_network_hints(kind)
    return {
        "path": rel_path,
        "kind": kind,
        "bytes": path.stat().st_size,
        "lines": [1, max(1, line_count(data))],
        "sha256": sha256(data),
        "anchor": anchor,
        "anchor_line": anchor_line,
        "env_keys": env_keys,
        "ports": extract_ports(text) if network_hints else [],
        "domains": extract_domains(text) if network_hints else [],
    }


def run_readonly_command(name: str, command: list[str], timeout: int = 5) -> dict:
    if shutil.which(command[0]) is None:
        return {"name": name, "command": command, "available": False, "status": "missing"}
    try:
        proc = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"name": name, "command": command, "available": True, "status": "timeout"}
    output = redact((proc.stdout or "")[:20_000])
    error = redact((proc.stderr or "")[:4_000])
    return {
        "name": name,
        "command": command,
        "available": True,
        "status": "ok" if proc.returncode == 0 else "nonzero",
        "returncode": proc.returncode,
        "stdout": output,
        "stderr": error,
    }


def collect_host_readonly() -> dict:
    commands = [
        ("systemd_running_services", ["systemctl", "list-units", "--type=service", "--state=running", "--no-pager", "--no-legend"]),
        ("systemd_timers", ["systemctl", "list-timers", "--all", "--no-pager", "--no-legend"]),
        ("docker_ps", ["docker", "ps", "--format", "{{json .}}"]),
        ("docker_compose_ls", ["docker", "compose", "ls", "--format", "json"]),
        ("listening_ports", ["ss", "-ltnup"]),
        ("tailscale_status", ["tailscale", "status", "--json"]),
    ]
    return {
        "hostname": socket.gethostname(),
        "collected_at": now_iso(),
        "commands": [run_readonly_command(name, command) for name, command in commands],
    }


def make_packet(inventory: dict, packet_out: Path, done_out: Path | None) -> None:
    findings = []
    for item in inventory["repo_ops_files"]:
        claim_bits = [f"{item['kind']} file `{item['path']}` is an operations evidence source."]
        if item["ports"]:
            claim_bits.append(f"Port mappings mentioned: {', '.join(item['ports'])}.")
        if item["domains"]:
            claim_bits.append(f"Domains mentioned: {', '.join(item['domains'][:8])}.")
        if item["env_keys"]:
            claim_bits.append(f"Environment keys mentioned: {', '.join(item['env_keys'][:12])}.")
        findings.append(
            {
                "slot_id": "runtime_ops",
                "claim": " ".join(claim_bits),
                "evidence": [
                    {
                        "path": item["path"],
                        "anchor": item["anchor"],
                        "anchor_line": item["anchor_line"],
                        "file_sha256": item["sha256"],
                        "policy": "strict",
                    }
                ],
                "confidence": "high",
            }
        )
    host = inventory.get("host_readonly")
    if host:
        available = [cmd["name"] for cmd in host.get("commands", []) if cmd.get("available")]
        findings.append(
            {
                "slot_id": "runtime_ops",
                "claim": f"Host read-only inventory was collected on `{host.get('hostname')}`. Available probes: {', '.join(available) or 'none'}.",
                "evidence": [
                    {
                        "path": "ai-docs/.work/<run-id>/ops-inventory/ops-inventory.json",
                        "anchor": "\"host_readonly\"",
                        "anchor_line": None,
                        "file_sha256": sha256(json.dumps(inventory, sort_keys=True).encode("utf-8")),
                        "policy": "tracked",
                    }
                ],
                "confidence": "medium",
            }
        )
    packet = {
        "task_id": "ops-inventory-001",
        "status": "done",
        "findings": findings,
        "open_questions": [] if findings else ["No operations evidence found in repository files."],
    }
    packet_out.parent.mkdir(parents=True, exist_ok=True)
    packet_out.write_text(json.dumps(packet, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if done_out:
        done_out.parent.mkdir(parents=True, exist_ok=True)
        done_out.write_text(
            json.dumps(
                {"task_id": "ops-inventory-001", "status": "done", "packet": str(packet_out)},
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )


def write_yaml(path: Path, inventory: dict) -> None:
    lines = [
        "version: 2",
        f"kind: {json.dumps(inventory['kind'])}",
        f"generated_at: {json.dumps(inventory['generated_at'])}",
        f"project_root: {json.dumps(inventory['project_root'])}",
        "repo_ops_files:",
    ]
    for item in inventory["repo_ops_files"]:
        lines.append(f"  - path: {json.dumps(item['path'])}")
        lines.append(f"    kind: {json.dumps(item['kind'])}")
        lines.append(f"    ports: {json.dumps(item['ports'])}")
        lines.append(f"    domains: {json.dumps(item['domains'])}")
        lines.append(f"    env_keys: {json.dumps(item['env_keys'])}")
    lines.append(f"host_readonly_collected: {str(bool(inventory.get('host_readonly'))).lower()}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", nargs="?", default=".")
    parser.add_argument("--out-dir", help="Defaults to ai-docs/.work/<timestamp>/ops-inventory")
    parser.add_argument("--include-ops-docs", action="store_true", help="Also scan markdown docs whose paths look operations-related")
    parser.add_argument("--host-readonly", action="store_true", help="Run limited host read-only probes. No sudo, no writes.")
    parser.add_argument("--packet-out", help="Write a runtime_ops packet JSON to this path")
    parser.add_argument("--done-out", help="Write a done marker JSON to this path")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    if args.out_dir:
        out_dir = Path(args.out_dir).resolve()
    else:
        run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S-v2")
        out_dir = root / "ai-docs" / ".work" / run_id / "ops-inventory"
    out_dir.mkdir(parents=True, exist_ok=True)

    candidates = git_files(root) or walk_files(root)
    repo_ops = []
    for rel_path in sorted(dict.fromkeys(candidates)):
        if rel_path.startswith("ai-docs/.work/"):
            continue
        path = root / rel_path
        if path.is_file() and is_ops_candidate(rel_path, include_ops_docs=args.include_ops_docs):
            try:
                repo_ops.append(inspect_ops_file(root, rel_path))
            except OSError:
                continue

    inventory = {
        "version": 2,
        "kind": "ai-docs-v2-ops-inventory",
        "generated_at": now_iso(),
        "project_root": str(root),
        "mode": "host-readonly" if args.host_readonly else "repo-only",
        "repo_ops_files": repo_ops,
        "host_readonly": collect_host_readonly() if args.host_readonly else None,
        "safety": {
            "writes_performed": False,
            "sudo_used": False,
            "secret_values_recorded": False,
            "note": "Environment files are summarized by key names only. Host probes are opt-in and read-only.",
        },
    }
    (out_dir / "ops-inventory.json").write_text(
        json.dumps(inventory, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_yaml(out_dir / "ops-inventory.yaml", inventory)
    if args.packet_out:
        make_packet(inventory, Path(args.packet_out).resolve(), Path(args.done_out).resolve() if args.done_out else None)
    print(
        json.dumps(
            {
                "out_dir": str(out_dir),
                "repo_ops_files": len(repo_ops),
                "host_readonly": bool(args.host_readonly),
                "packet": args.packet_out,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
