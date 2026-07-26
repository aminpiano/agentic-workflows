# Antigravity One-Shot Usage

## Verified Local Command

Use the wrapper:

```bash
python3 $AR_SKILL/scripts/run_agy_once.py \
  --prompt-file <prompt.txt> \
  --out <result.txt> \
  --timeout 900
```

The wrapper runs:

```bash
agy --sandbox --print-timeout <seconds>s --print "<prompt contents>"
```

It writes stdout to `--out`, stderr to `<out>.stderr.log`, and exits non-zero if:

- `agy` exits non-zero
- stdout starts with `Error:`
- the subprocess times out

## Local Facts

- Binary found at `/home/s-office/.local/bin/agy`.
- `agy --help` supports `--print`, `--print-timeout`, `--sandbox`, `--add-dir`, `--continue`, `--conversation`, `plugin`, `update`, and `install`.
- Local Antigravity settings are under `~/.gemini/antigravity-cli/`.
- Current local setting observed during setup: `Gemini 3.5 Flash (High)`.

## When To Use Agy

Use Antigravity for bottom-of-schedule one-shot tasks:

- broad web search
- official/product/source discovery
- site profiling
- weakly structured web pages

Avoid using it for:

- tasks that need tight repository edits
- high-concurrency execution unless the user explicitly asks
- final fact acceptance without a verifier phase

## Prompt Rules

Prompts sent to `agy` must tell the worker:

- write outputs into exact assigned files
- write `done/<task_id>.yaml`
- return only brief completion metadata
- use `UNKNOWN` for unsupported facts
- never invent URLs, DOI, PMID, NCT, dates, or authors

For long tasks, split the schedule rather than sending huge prompts.
