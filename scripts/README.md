# scripts/

本目录的脚本都是面向"成员本机 5 分钟跑起来 ATA"的运维工具，不在服务主流程里。

| 脚本 | 用途 |
| --- | --- |
| `serve-dev.sh` | 启动 ATA 本地 dev server（17877 主端口 + 17878 代理采集通道），自动 tail 已装 agent 的会话目录 |
| `install-service.sh` | 把 ATA 注册成 macOS launchd 常驻服务（`com.ata.atatrace`），随登录自启，崩溃自动拉起 |
| `attach-cue-pi.sh` | 把 Pi extension 安装到 Cue 的隔离 Pi 配置目录（`~/.cue/pi-config/...`） |
| `attach-omp-pi.sh` | 把 Pi extension 以 omp 身份变体安装到 omp 的 agent 扩展目录（`~/.omp/agent/extensions/...`） |
| `install-droid-hooks.sh` | 把 ATA 的 droid hook 命令挂到 droid CLI 的 7 类事件上（见下文） |
| `_merge_droid_hooks.py` | 上面脚本调用的纯 Python JSON 合并器，方便跨平台和单测 |

---

## install-droid-hooks.sh

把 `POST /api/hooks/droid` 这条 HTTP 端点挂进 droid CLI 的 7 个事件通道
（`PreToolUse` / `PostToolUse` / `Notification` / `UserPromptSubmit` /
`Stop` / `SubagentStop` / `SessionStart`），droid 触发 hook 时就会把
事件 payload 推到 ata，ata 端会写到 `~/.ata/droid_hooks.jsonl` 供后续
回放。

### 装

```bash
bash scripts/install-droid-hooks.sh
# 或
./scripts/install-droid-hooks.sh
```

默认目标配置：

1. `$FACTORY_HOME_OVERRIDE/hooks.json`（如设置了 env）
2. `$HOME/.factory/hooks.json`（默认）
3. 以上都没有会先 `mkdir -p` 然后写入

默认 ata 端点：

1. `$ATA_URL/api/hooks/droid`（如设置了 env，例如 `ATA_URL=http://127.0.0.1:17877`）
2. `http://127.0.0.1:17877/api/hooks/droid`（默认）
3. CLI 参数 `--ata-url` 可覆盖

### 卸载

```bash
bash scripts/install-droid-hooks.sh --uninstall
```

只移除 ata 自己追加的 command 块，保留用户原有的 hook / matcher / 顶层字段。

### 状态

```bash
bash scripts/install-droid-hooks.sh --status
```

报告 7 类 event 是否都已挂载 ata hook；`$?` 0 = 全部覆盖，1 = 有缺失。

### 自定义 ata 地址

```bash
ATA_URL=http://my-host:17877 bash scripts/install-droid-hooks.sh
# 或
bash scripts/install-droid-hooks.sh --ata-url http://my-host:17877
```

### 自定义 droid 配置目录

```bash
FACTORY_HOME_OVERRIDE=/path/to/factory bash scripts/install-droid-hooks.sh
```

### 重装（换 ata URL 后想清理旧规则）

```bash
bash scripts/install-droid-hooks.sh --force
```

先 `--uninstall` 再 install，会清掉之前用其他 `ATA_URL` 装进去的规则。

### 干跑

```bash
bash scripts/install-droid-hooks.sh --dry-run
```

只打印会做什么，不写文件、不备份。

## 幂等

- 多次跑脚本是安全的：每条 event 都已经有 ata command 的话直接跳过，不重复追加
- 现有用户的 hook / matcher / `hooksDisabled` / `showHookOutput` 等顶层字段都不会被动
- 现有 `hooks.json` 在写之前会备份到 `hooks.json.bak.YYYYMMDDHHMMSS`

## 依赖

- `curl`（必需）
- `python3`（必需；用于 JSON 合并，不依赖 `jq` / `yq`）
- droid CLI（目标机器已装即可）
- ATA 服务（可选 — 脚本会探活 `/api/health` 并 warn-only，不阻断安装）

## 端到端验证

1. `make serve` 启 ata（17877 端口）
2. `bash scripts/install-droid-hooks.sh` 装 hook
3. 在 droid 里随便跑一个工具，触发 `PreToolUse` / `PostToolUse`
4. `tail -F ~/.ata/droid_hooks.jsonl` 看到事件落盘
5. `bash scripts/install-droid-hooks.sh --status` 显示 7 类都 ok
