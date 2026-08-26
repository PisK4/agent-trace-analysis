# 本地常驻与部署 / Local Service and Deployment

launchd 常驻服务、端口与账本约定、dev 起服务脚本、extension / 代理通道的开启方式。

| 词 | 定义 |
| --- | --- |
| 常驻服务 | launchd `com.ata.atatrace` plist；随登录自启；崩溃自动拉起（KeepAlive） |
| webroot | `web/dist`（Vite 构建产物）；`ata serve --web` 默认 |
| 账本 | SQLite 文件；dev 默认 `~/.ata/dev.sqlite`，生产 `~/.ata/ata.sqlite` |
| 代理通道 | `--proxy-port` 开启的可选 LLM 流量侧采 |

## 常驻服务

| 项 | 值 |
| --- | --- |
| Label | `com.ata.atatrace` |
| Plist | `~/Library/LaunchAgents/com.ata.atatrace.plist` |
| 日志 stdout | `~/.ata/atatrace.log` |
| 日志 stderr | `~/.ata/atatrace.err.log` |
| 入口脚本 | `<repo>/scripts/serve-dev.sh` |
| RunAtLoad | true（随登录自启） |
| KeepAlive | true（崩溃自动拉起） |

环境变量（plist 内固化）：

| 变量 | 含义 | 默认 |
| --- | --- | --- |
| `ATA_PORT` | 服务端口 | 8787 |
| `ATA_LEDGER` | 账本路径 | `~/.ata/ata.sqlite` |
| `ATA_TAIL_MAX_AGE_DAYS` | 文件 tail 时间窗 | 7（0 = 全部历史） |
| `ATA_PROXY_PORT` | 代理通道端口 | 未设则不开 |

## 部署流程

| 任务 | 命令 |
| --- | --- |
| 改完生产代码后重建常驻 | `./scripts/install-service.sh restart` |
| 确认服务可用 | `curl -s http://127.0.0.1:$ATA_PORT/api/health` |
| 查看状态 | `./scripts/install-service.sh status` |
| 停止常驻 | `./scripts/install-service.sh uninstall` |
| 临时前台起服务（避免端口冲突先 uninstall） | `make serve` |
| 改 plist 后生效 | `restart` |

`install-service.sh` 在生成 plist 时把 `ATA_PORT` / `ATA_LEDGER` 等环境变量固化进 plist，避免 restart 后丢失。重新 install 时需继续显式传入。

## dev 起服务（`make serve` / `./scripts/serve-dev.sh`）

| 检测 | 行为 |
| --- | --- |
| 存在 `~/.claude/projects` | 加 `--claude-path` |
| 存在 `~/.codex/sessions` | 加 `--codex-path` |
| 存在 `~/.factory/sessions` | 加 `--droid-path` |
| `ATA_PROXY_PORT` 已设 | 加 `--proxy-port` 与可选 `--proxy-upstream` |
| Pi / Cue | 不需要路径参数，走 `POST /api/pi-hooks` |

`make serve` 等价于 `scripts/serve-dev.sh`。其它 `make` 目标：`make test`（全量测试）、`make seed`（灌入演示语料）、`make help`（命令列表）。

## 启用代理通道

```bash
# 启动
python3 -m ata serve --proxy-port 8319
# agent 的 API base 改指 http://127.0.0.1:8319
# 上游默认 api.anthropic.com（用 --proxy-upstream 改）
# --proxy-agent 改 agent_id（默认 claude）
```

代理只发账本里别处拿不到的事实（system.upserted + turn.ended）；详见 [`proxy-capture-channel.md`](proxy-capture-channel.md)。

## Pi / Cue extension 安装

```bash
# 软链方式（已支持）
mkdir -p ~/.pi/agent/extensions
ln -s <repo>/extensions/pi-atatrace ~/.pi/agent/extensions/pi-atatrace
# extension 默认指向 8787；换端口必须在 ~/.zshrc 设 ATA_URL
# Pi / Cue 必须新开进程才能加载后装的 extension（旧进程不重读）
```

`ATA_URL` 决定 extension 推流到哪个服务地址。`17877` 是常驻服务的本机实际端口（`ATA_PORT=17877`），需要让 extension 知道。

## 数据边界

| 边界 | 行为 |
| --- | --- |
| 端口被占 | `make serve` 前台起服务会失败；先 `uninstall` 常驻 |
| plist 改完不生效 | 必须 `restart` |
| 账本路径改完丢失 | 重新 `install` 时必须显式传 `ATA_LEDGER` |
| Pi extension 不推流 | 旧 Pi 进程没加载后装的 extension；新开一个 |
| 代理通道没拿到 SYSTEM | 检查请求头是否带宿主会话 id（如 `x-claude-code-session-id`） |

## 引用边界

| 边界 | 不外推成 |
| --- | --- |
| launchd plist 流程 | 任何 systemd / Windows 服务方案；本服务只在 macOS 本机 |
| `serve-dev.sh` 自动检测路径 | 任意运行期配置；它只是 dev 入口 |
| `ATA_URL` 控制 extension 推送 | 任何服务发现机制 |

## 代码出处

| 概念 | 文件 |
| --- | --- |
| 常驻 plist 生成 | `scripts/install-service.sh` `write_plist` |
| dev 起服务 | `scripts/serve-dev.sh` |
| 端口/账本/代理 CLI 参数 | `ata/__main__.py` |
| webroot 默认 | `ata/__main__.py` `--web` 默认 `web/dist` |
| 静态托管 | `ata/http.py` `make_server(ledger, webroot, ...)` |
| 代理通道 | [`proxy-capture-channel.md`](proxy-capture-channel.md) |
| 读取端点 | [`read-api-and-cli.md`](read-api-and-cli.md) |
