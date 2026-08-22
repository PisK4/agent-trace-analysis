#!/bin/bash
# Install ATA's Pi extension into Cue's isolated global Pi extension directory.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Cue 数据目录：上游 screenpipe 的 default_screenpipe_data_dir() 默认 ~/.cue（SCREENPIPE_DATA_DIR 可覆盖），
# Pi 隔离配置目录为 ~/.cue/pi-config；CUE_PI_AGENT_DIR 仍可显式指定非默认位置。
AGENT_DIR="${CUE_PI_AGENT_DIR:-$HOME/.cue/pi-config}"
TARGET="$AGENT_DIR/extensions/ata-cue-trace"
ATA_ENDPOINT="${ATA_URL:-http://127.0.0.1:8787}"

mkdir -p "$TARGET"
install -m 0644 "$ROOT/extensions/pi-atatrace/index.ts" "$TARGET/index.ts"
cat > "$TARGET/config.ts" <<EOF
export const ATA_CONFIG = {
  endpoint: "${ATA_ENDPOINT}",
  agentId: "cue",
  host: "cue",
  runtime: "pi",
} as const;
EOF

printf 'Installed ATA Cue Pi tracing at %s\n' "$TARGET"
printf 'Cue will load it when its next Pi session starts.\n'
