#!/usr/bin/env bash
# 安装 ATA 的 droid hook 命令到 droid 工厂配置（hooks.json）。
#
# 用法:
#   bash scripts/install-droid-hooks.sh                     # 默认: 装到 $HOME/.factory/hooks.json
#   ATA_URL=http://my-host:17877 bash scripts/install-droid-hooks.sh
#   FACTORY_HOME_OVERRIDE=/path/to/factory bash scripts/install-droid-hooks.sh
#   bash scripts/install-droid-hooks.sh --ata-url http://my-host:17877
#   bash scripts/install-droid-hooks.sh --uninstall
#   bash scripts/install-droid-hooks.sh --status
#   bash scripts/install-droid-hooks.sh --dry-run
#   bash scripts/install-droid-hooks.sh --force            # 重装（先卸载再装）
#
# 行为:
#   * 幂等: 多次跑不会重复追加 ata command
#   * 保留用户已有的 hook 规则、matcher、顶层字段（hooksDisabled 等）
#   * 备份现有 hooks.json 到 hooks.json.bak.YYYYMMDDHHMMSS
#   * ata 端点 alive 检查是 warn-only, 不阻断安装
#
# 端点: 默认 http://127.0.0.1:17877/api/hooks/droid, 可由 ATA_URL 或 --ata-url 覆盖
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MERGE_PY="$SCRIPT_DIR/_merge_droid_hooks.py"

# ---- 解析参数 ----
ATA_URL_OVERRIDE=""
DRY_RUN=0
DO_UNINSTALL=0
DO_STATUS=0
DO_FORCE=0
usage() {
  cat <<EOF
用法: $0 [--uninstall] [--status] [--dry-run] [--force] [--ata-url URL]

  --uninstall     从 hooks.json 移除 ata command 块, 保留其他 hook
  --status        报告 7 类 event 是否都已挂载 ata hook
  --dry-run       只打印将做什么, 不改文件
  --force         先 --uninstall 再 install, 用于 ATA_URL 变更后重装
  --ata-url URL   覆盖 ATA_URL (默认: \${ATA_URL:-http://127.0.0.1:17877})

环境变量:
  ATA_URL                  ata 端点 (默认 http://127.0.0.1:17877), 拼接 /api/hooks/droid
  FACTORY_HOME_OVERRIDE    droid 工厂配置根目录 (默认 \$HOME/.factory)
  HOME                     用户家目录 (用于 FACTORY_HOME_OVERRIDE 缺省时)
EOF
}
while [ $# -gt 0 ]; do
  case "$1" in
    --uninstall) DO_UNINSTALL=1 ;;
    --status) DO_STATUS=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --force) DO_FORCE=1 ;;
    --ata-url) ATA_URL_OVERRIDE="${2:-}"; shift ;;
    --ata-url=*) ATA_URL_OVERRIDE="${1#*=}" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown argument: $1" >&2; usage; exit 1 ;;
  esac
  shift
done

# ---- 依赖检查 ----
if ! command -v curl >/dev/null 2>&1; then
  echo "error: curl is required but not found in PATH" >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 is required but not found in PATH" >&2
  exit 1
fi
if [ ! -f "$MERGE_PY" ]; then
  echo "error: $MERGE_PY not found (script expects to live in scripts/)" >&2
  exit 1
fi

# ---- 决定目标 hooks.json 位置 ----
if [ -n "${FACTORY_HOME_OVERRIDE:-}" ]; then
  FACTORY_HOME="$FACTORY_HOME_OVERRIDE"
elif [ -n "${HOME:-}" ] && [ -d "${HOME}/.factory" ]; then
  FACTORY_HOME="$HOME/.factory"
elif [ -n "${HOME:-}" ]; then
  FACTORY_HOME="$HOME/.factory"
else
  echo "error: cannot determine factory home. Set FACTORY_HOME_OVERRIDE or HOME." >&2
  exit 1
fi
HOOKS_JSON="$FACTORY_HOME/hooks.json"

# ---- 决定 ata 端点 URL ----
if [ -n "$ATA_URL_OVERRIDE" ]; then
  ATA_BASE="$ATA_URL_OVERRIDE"
elif [ -n "${ATA_URL:-}" ]; then
  ATA_BASE="$ATA_URL"
else
  ATA_BASE="http://127.0.0.1:17877"
fi
# 去掉尾部斜杠, 再拼路径
ATA_BASE="${ATA_BASE%/}"
ATA_ENDPOINT="$ATA_BASE/api/hooks/droid"

# ---- 构造 shell command 字符串 (放进 JSON 的 hooks[*].command) ----
# 关键: --data-binary @- 让 stdin 喂给 droid 给的 hook payload (via env / file)
# 异步 & 加 max-time 1 防 droid 端 AgentAbortError
# 用单引号包, 内部不再有 shell 变量, 避免被 droid 解释时出错
ATA_CMD="(curl -sS -X POST $ATA_ENDPOINT --data-binary @- --max-time 1 -H 'Content-Type: application/json' &)"

# ---- 打印汇总 ----
echo "目标 hooks.json: $HOOKS_JSON"
echo "ata 端点:        $ATA_ENDPOINT"
echo "command:         $ATA_CMD"

# ---- 探活 ata 端点 (warn-only) ----
HEALTH_URL="$ATA_BASE/api/health"
if command -v curl >/dev/null 2>&1; then
  if curl -sS --max-time 2 -o /dev/null -w '%{http_code}' "$HEALTH_URL" 2>/dev/null | grep -qE '^(200|204)$'; then
    echo "ata 端点 alive: yes"
  else
    echo "warning: ata 端点 $HEALTH_URL 无响应 (--max-time 2)。脚本仍会继续, 你可以先装再起服务。" >&2
  fi
fi

# ---- 备份现有 hooks.json (如果存在) ----
backup_existing() {
  if [ -f "$HOOKS_JSON" ]; then
    local stamp
    stamp="$(date +%Y%m%d%H%M%S)"
    local backup="$HOOKS_JSON.bak.$stamp"
    if [ "$DRY_RUN" = 1 ]; then
      echo "[dry-run] would back up $HOOKS_JSON -> $backup"
    else
      cp -p "$HOOKS_JSON" "$backup"
      echo "已备份: $backup"
    fi
  fi
}

# ---- --status: 检查但不修改 ----
if [ "$DO_STATUS" = 1 ]; then
  if [ ! -f "$HOOKS_JSON" ]; then
    echo "status: $HOOKS_JSON 不存在, 未安装"
    exit 1
  fi
  echo "当前 ata hook 覆盖情况:"
  python3 "$MERGE_PY" --status "$HOOKS_JSON"
  rc=$?
  if [ $rc -eq 0 ]; then
    echo "status: 7 类 event 全部已挂载 ata hook"
  else
    echo "status: 部分 event 未挂载 ata hook"
  fi
  exit $rc
fi

# ---- --uninstall: 移除 ata command ----
if [ "$DO_UNINSTALL" = 1 ]; then
  backup_existing
  if [ "$DRY_RUN" = 1 ]; then
    echo "[dry-run] would run: python3 $MERGE_PY --uninstall <command> $HOOKS_JSON"
  else
    python3 "$MERGE_PY" --uninstall "$ATA_CMD" "$HOOKS_JSON"
  fi
  exit 0
fi

# ---- install (默认) ----
# 兼容 --force: 先卸载再装
if [ "$DO_FORCE" = 1 ]; then
  echo "--force: 先卸载再装"
  if [ "$DRY_RUN" = 1 ]; then
    echo "[dry-run] would run: python3 $MERGE_PY --uninstall <command> $HOOKS_JSON"
  else
    python3 "$MERGE_PY" --uninstall "$ATA_CMD" "$HOOKS_JSON"
  fi
fi

backup_existing

# 确保父目录存在 (FACTORY_HOME 可能不存在)
if [ ! -d "$FACTORY_HOME" ]; then
  if [ "$DRY_RUN" = 1 ]; then
    echo "[dry-run] would mkdir -p $FACTORY_HOME"
  else
    mkdir -p "$FACTORY_HOME"
    echo "已创建目录: $FACTORY_HOME"
  fi
fi

if [ "$DRY_RUN" = 1 ]; then
  echo "[dry-run] would run: python3 $MERGE_PY <command> $HOOKS_JSON"
  echo "[dry-run] 命令已构造完成。去掉 --dry-run 实际执行。"
  exit 0
fi

python3 "$MERGE_PY" "$ATA_CMD" "$HOOKS_JSON"

echo ""
echo "安装完成。验证方法:"
echo "  bash $0 --status"
echo "首次触发后, 端点 ${ATA_ENDPOINT} 会在 ~/.ata/droid_hooks.jsonl 落 audit log。"

exit 0
