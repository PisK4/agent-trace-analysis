#!/bin/bash
# Install ATA's Pi extension into Cue's isolated global Pi extension directory.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AGENT_DIR="${CUE_PI_AGENT_DIR:-$HOME/.screenpipe/pi-config}"
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
