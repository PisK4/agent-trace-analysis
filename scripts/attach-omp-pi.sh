#!/bin/bash
# Install ATA's Pi extension into omp's isolated agent extension directory,
# rewired with the omp product identity (agent_id/host=omp, runtime=pi).
# omp is a desktop product sitting on the Pi runtime; the hook contract is
# identical to pi-atatrace, only ATA_CONFIG.* changes.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# omp 数据目录：默认 ~/.omp（与 OMP_DATA_DIR / 桌面端默认数据目录约定一致），
# 可由 OMP_PI_AGENT_DIR 显式覆盖（指向另一个 agent 扩展目录）。
AGENT_DIR="${OMP_PI_AGENT_DIR:-$HOME/.omp/agent}"
TARGET="$AGENT_DIR/extensions/ata-omp-trace"
ATA_ENDPOINT="${ATA_URL:-http://127.0.0.1:8787}"

mkdir -p "$TARGET"
install -m 0644 "$ROOT/extensions/pi-atatrace/index.ts" "$TARGET/index.ts"
cat > "$TARGET/config.ts" <<EOF
export const ATA_CONFIG = {
  endpoint: "${ATA_ENDPOINT}",
  agentId: "omp",
  host: "omp",
  runtime: "pi",
} as const;
EOF

printf 'Installed ATA omp tracing at %s\n' "$TARGET"
printf 'omp will load it when its next session starts.\n'
