#!/bin/bash
# ATA dev server for local manual testing and team dogfooding.
# Detects installed agent runtimes and tails their first-party session
# dirs. Everything stays on this machine; nothing is sent anywhere.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${ATA_PORT:-17877}"
LEDGER="${ATA_LEDGER:-$HOME/.ata/dev.sqlite}"
AGE="${ATA_TAIL_MAX_AGE_DAYS:-7}"
# 代理采集通道：默认开 17878（agent 的 API base 指过来就补采）；设 ATA_PROXY_PORT=0 关闭
PROXY_PORT="${ATA_PROXY_PORT:-17878}"
PROXY_ARGS=(--proxy-port "$PROXY_PORT")
[ -n "${ATA_PROXY_UPSTREAM:-}" ] && PROXY_ARGS+=(--proxy-upstream "$ATA_PROXY_UPSTREAM")

ARGS=()
if [ -d "$HOME/.claude/projects" ]; then ARGS+=(--claude-path "$HOME/.claude/projects"); fi
if [ -d "$HOME/.codex/sessions" ]; then ARGS+=(--codex-path "$HOME/.codex/sessions"); fi
if [ -d "$HOME/.factory/sessions" ]; then ARGS+=(--droid-path "$HOME/.factory/sessions"); fi

mkdir -p "$HOME/.ata"
# React 版（webapp build 产物）是唯一前端。
WEB="web/dist"
python3 -m ata serve --port "$PORT" --ledger "$LEDGER" --web "$WEB" \
  --tail-max-age-days "$AGE" "${ARGS[@]}" "${PROXY_ARGS[@]}" "$@"
