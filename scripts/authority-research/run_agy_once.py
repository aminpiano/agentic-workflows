#!/usr/bin/env python3
"""Run Antigravity CLI once from a prompt file and write stdout to a file."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run agy --print with a prompt file.")
    parser.add_argument("--prompt-file", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--stderr", type=Path, default=None)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--add-dir", action="append", default=[])
    parser.add_argument("--no-sandbox", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    prompt_path = args.prompt_file.expanduser().resolve()
    out_path = args.out.expanduser().resolve()
    stderr_path = args.stderr.expanduser().resolve() if args.stderr else out_path.with_suffix(out_path.suffix + ".stderr.log")

    prompt = prompt_path.read_text(encoding="utf-8")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["agy"]
    for path in args.add_dir:
        cmd.extend(["--add-dir", str(Path(path).expanduser().resolve())])
    if not args.no_sandbox:
        cmd.append("--sandbox")
    cmd.extend(["--print-timeout", f"{args.timeout}s", "--print", prompt])

    started = time.time()
    result = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=args.timeout + 30,
    )
    elapsed = round(time.time() - started, 3)
    stderr_path.write_text(result.stderr or "", encoding="utf-8")

    status = "ok"
    error = None
    stdout = result.stdout or ""
    if result.returncode != 0:
        status = "failed"
        error = f"agy exited with code {result.returncode}"
    elif stdout.lstrip().startswith("Error:"):
        status = "failed"
        error = stdout.strip().splitlines()[0]

    if status == "ok":
        out_path.write_text(stdout.strip() + "\n", encoding="utf-8")
    else:
        out_path.write_text(stdout, encoding="utf-8")

    summary = {
        "status": status,
        "returncode": result.returncode,
        "elapsed_seconds": elapsed,
        "prompt_file": str(prompt_path),
        "out": str(out_path),
        "stderr": str(stderr_path),
        "error": error,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
