#!/bin/bash
# ATA 常驻服务管理（launchd）：install / restart / uninstall / status
# - 服务名 com.ata.atatrace，随登录自启，崩溃自动拉起（KeepAlive）
# - 日志：~/.ata/atatrace.log（stdout）、~/.ata/atatrace.err.log（stderr）
# - 端口/会话窗口由 env 控制：ATA_PORT（默认 8787）、ATA_TAIL_MAX_AGE_DAYS（默认 7）
set -euo pipefail

LABEL="com.ata.atatrace"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
UI_DOMAIN="gui/$(id -u)"

usage() {
  echo "用法: $0 {install|restart|uninstall|status}"
  echo "  install    生成 plist 并注册常驻服务（已注册则先重启）"
  echo "  restart    重启常驻服务（代码更新后用它重建）"
  echo "  uninstall  停止并移除常驻服务"
  echo "  status     查看服务状态与日志位置"
}

write_plist() {
  mkdir -p "$HOME/.ata"
  # 把调用方显式传入的 ATA_PORT / ATA_LEDGER 固化进 plist，避免 restart 后丢失
  local extra_env=""
  [ -n "${ATA_PORT:-}" ] && extra_env+="    <key>ATA_PORT</key><string>$ATA_PORT</string>"$'\n'
  [ -n "${ATA_LEDGER:-}" ] && extra_env+="    <key>ATA_LEDGER</key><string>$ATA_LEDGER</string>"$'\n'
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$REPO/scripts/serve-dev.sh</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/.ata/atatrace.log</string>
  <key>StandardErrorPath</key><string>$HOME/.ata/atatrace.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin</string>
$extra_env  </dict>
</dict>
</plist>
EOF
  chmod 644 "$PLIST"
  echo "已写入 $PLIST"
}

install() {
  write_plist
  if launchctl print "$UI_DOMAIN/$LABEL" >/dev/null 2>&1; then
    echo "服务已注册，执行重启以应用当前代码"
    restart
    return
  fi
  launchctl bootstrap "$UI_DOMAIN" "$PLIST"
  echo "服务已注册并启动"
  status
}

restart() {
  if launchctl print "$UI_DOMAIN/$LABEL" >/dev/null 2>&1; then
    launchctl kickstart -k "$UI_DOMAIN/$LABEL"
    echo "服务已重启"
  else
    echo "服务未注册，先安装"
    install
  fi
}

uninstall() {
  if launchctl print "$UI_DOMAIN/$LABEL" >/dev/null 2>&1; then
    launchctl bootout "$UI_DOMAIN/$LABEL"
  fi
  rm -f "$PLIST"
  echo "服务已停止并移除"
}

status() {
  if launchctl print "$UI_DOMAIN/$LABEL" >/dev/null 2>&1; then
    echo "服务状态: 已注册运行中"
    launchctl print "$UI_DOMAIN/$LABEL" | grep -E "state|pid" | head -3
  else
    echo "服务状态: 未注册"
  fi
  echo "日志: ~/.ata/atatrace.log / ~/.ata/atatrace.err.log"
  echo "账本: \${ATA_LEDGER:-~/.ata/dev.sqlite}"
}

case "${1:-}" in
  install) install ;;
  restart) restart ;;
  uninstall) uninstall ;;
  status) status ;;
  *) usage; exit 1 ;;
esac
