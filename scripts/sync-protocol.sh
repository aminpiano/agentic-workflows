#!/usr/bin/env bash
#
# Sync a protocol's implementation from its upstream skill repo into this
# repository's snapshot.
#
# This repository is a *snapshot*, not the source of truth. Each protocol is
# developed and battle-tested as an installed skill; this repo publishes a
# readable copy of that work. Edits therefore flow one way only:
#
#     upstream skill  ---->  this repository
#
# Never hand-edit the synced files here. Fix them upstream and re-run this
# script, or the next sync will silently overwrite the fix.
#
# What is synced:
#   scripts/*.py        -> scripts/<protocol>/
#   references/*.md     -> protocols/<protocol>/references/
#
# What is NOT synced (deliberately):
#   SKILL.md            The upstream file is an executable spec with runtime
#                       frontmatter. protocols/<protocol>/README.md is a
#                       human-facing introduction written for this repo.
#                       They serve different readers — keep both, by hand.
#   templates/          Repo-only starter files.
#   agents/, .gitignore Runtime-specific packaging.
#
# Usage:
#   scripts/sync-protocol.sh [protocol] [upstream-path] [--apply]
#
#   Runs as a dry run by default and prints what would change. Pass --apply
#   to actually copy.
#
set -euo pipefail

PROTOCOL="${1:-authority-research}"
UPSTREAM="${2:-$HOME/.codex/skills/$PROTOCOL}"
APPLY=""
for arg in "$@"; do [ "$arg" = "--apply" ] && APPLY=1; done

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPTS_DST="$REPO/scripts/$PROTOCOL"
REFS_DST="$REPO/protocols/$PROTOCOL/references"

[ -d "$UPSTREAM" ] || { echo "upstream not found: $UPSTREAM" >&2; exit 1; }
[ -d "$SCRIPTS_DST" ] || { echo "destination not found: $SCRIPTS_DST" >&2; exit 1; }
[ -d "$REFS_DST" ] || { echo "destination not found: $REFS_DST" >&2; exit 1; }

echo "protocol : $PROTOCOL"
echo "upstream : $UPSTREAM"
echo "snapshot : $REPO"
echo "mode     : ${APPLY:+APPLY}${APPLY:-dry run (pass --apply to copy)}"
echo

changed=0
report() {
  local src="$1" dst="$2" label="$3"
  if [ ! -f "$dst" ]; then
    echo "  NEW      $label"
    changed=$((changed + 1))
  elif ! diff -q "$src" "$dst" >/dev/null 2>&1; then
    echo "  UPDATED  $label  ($(diff "$src" "$dst" | grep -c '^[<>]') lines)"
    changed=$((changed + 1))
  fi
  [ -n "$APPLY" ] && cp "$src" "$dst"
  return 0
}

for src in "$UPSTREAM"/scripts/*.py; do
  [ -e "$src" ] || continue
  report "$src" "$SCRIPTS_DST/$(basename "$src")" "scripts/$PROTOCOL/$(basename "$src")"
done

for src in "$UPSTREAM"/references/*.md; do
  [ -e "$src" ] || continue
  report "$src" "$REFS_DST/$(basename "$src")" "protocols/$PROTOCOL/references/$(basename "$src")"
done

# Files present only in the snapshot are reported but never deleted
# automatically — a missing upstream file may mean a rename, not a removal.
for dst in "$SCRIPTS_DST"/*.py; do
  [ -e "$dst" ] || continue
  [ -f "$UPSTREAM/scripts/$(basename "$dst")" ] || echo "  ORPHAN   scripts/$PROTOCOL/$(basename "$dst")  (no longer upstream — review by hand)"
done

echo
if [ "$changed" -eq 0 ]; then
  echo "snapshot is up to date"
elif [ -n "$APPLY" ]; then
  echo "$changed file(s) synced — review 'git diff' before committing"
else
  echo "$changed file(s) would change — re-run with --apply"
fi
