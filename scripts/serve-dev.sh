#!/bin/bash
# ATA dev server for local manual testing and team dogfooding.
# Detects installed agent runtimes and tails their first-party session
# dirs. Everything stays on this machine; nothing is sent anywhere.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${ATA_PORT:-8787}"
LEDGER="${ATA_LEDGER:-$HOME/.ata/dev.sqlite}"
AGE="${ATA_TAIL_MAX_AGE_DAYS:-7}"

ARGS=()
if [ -d "$HOME/.claude/projects" ]; then ARGS+=(--claude-path "$HOME/.claude/projects"); fi
if [ -d "$HOME/.codex/sessions" ]; then ARGS+=(--codex-path "$HOME/.codex/sessions"); fi
if [ -d "$HOME/.factory/sessions" ]; then ARGS+=(--droid-path "$HOME/.factory/sessions"); fi

mkdir -p "$HOME/.ata"
python3 -m ata serve --port "$PORT" --ledger "$LEDGER" \
  --tail-max-age-days "$AGE" "${ARGS[@]}" "$@"
