# ATA · Atatrace

本地 Agent 轨迹阅读器。把 Pi、Droid、Claude Code、Codex 的会话翻译成统一账本，在浏览器里按轮次回看：消息、工具调用、每轮 usage、会话标题。

- 纯 Python 标准库后端 + 零构建前端；Markdown 与代码高亮用 vendored 库（`web/vendor/`，无运行期下载）
- 全部数据留在本机，不设服务端
- 内核不打开任何厂商目录；每个 agent 的适配器只在你显式传入路径时读取

## 快速开始

```bash
cd repos/ata
make serve                      # 等同于 ./scripts/serve-dev.sh，检测已装 agent 并 tail
# 打开 http://127.0.0.1:8787
```

其它常用命令：`make test`（全量测试）、`make seed`（灌入演示会话语料）、`make help`（命令列表）。

`serve-dev.sh` 自动挂载本机存在的会话目录（Claude Code：`~/.claude/projects`；Codex：`~/.codex/sessions`；Droid：`~/.factory/sessions`），账本固定存在 `~/.ata/dev.sqlite`，只读取最近 7 天修改的会话文件（`--tail-max-age-days` 可调，`0` 表示全部历史）。

也可以手动指定：

```bash
python3 -m ata serve --port 8787 --ledger ~/.ata/dev.sqlite \
  --claude-path ~/.claude/projects --codex-path ~/.codex/sessions \
  --droid-path ~/.factory/sessions --tail-max-age-days 7
```

Pi 不需要路径参数：它的 extension 经 `POST /api/pi-hooks` 实时推送。

## 支持的 agent

| Agent | 数据通道 | 会话标题 | SYSTEM 快照 | 每轮 usage |
| --- | --- | --- | --- | --- |
| Pi | 官方 extension（live hook，需安装见下） | 首条用户消息 | 有（`before_agent_start`） | reported |
| Cue | Pi 官方 extension（live hook，显式安装见下） | 首条用户消息 | 有（`before_agent_start`） | reported |
| Claude Code | 第一方 transcript（文件 tail） | `ai-title` 行 | 无（transcript 不落盘系统提示） | reported（缺失或全 0 → Missing） |
| Codex | 第一方 rollout（文件 tail） | `originator`（首条 prompt） | 有（`base_instructions`） | reported（`token_count.last_token_usage`） |
| Droid | 第一方 sessions（文件 tail） | `session_start.title` | 无 | 恒 Missing（JSONL 无 token 字段） |

## 安装 Pi extension（可选）

```bash
ln -s "$PWD/extensions/pi-atatrace" ~/.pi/agent/extensions/pi-atatrace
```

Pi 启动时自动加载，把 hook 事件推到 `ATA_URL`（默认 `http://127.0.0.1:8787`）。

## 安装 Cue Pi Trace extension（可选）

Cue 是 Screenpipe 品牌升级后的名称。该命令只写入 Cue 的隔离 Pi 配置目录，不修改 Cue 仓库或其原生功能：

```bash
make attach-cue
```

安装器将 ATA extension 复制到 `~/.screenpipe/pi-config/extensions/ata-cue-trace/`。Cue 的下一次 Pi 会话会自动加载它，并以 Cue 的粉色产品身份写入 ATA；事件仍保留 `host=cue`、`runtime=pi` 作为会话元数据。

若 Cue 使用了非默认的 Pi 配置目录，可显式指定：

```bash
CUE_PI_AGENT_DIR=/path/to/pi-config make attach-cue
```

## 手动测试

各 agent 的测试步骤与「怎么算正常」见 [`docs/features/manual-test-guide.md`](docs/features/manual-test-guide.md)。

## 结构

```text
ata/            Python 服务：schema / ledger / projection / http / plugins
plugins/        pi / droid / claude / codex 方言翻译器 + 公共 jsonl 增量读取
extensions/     pi-atatrace（Pi 官方 extension）
web/            零构建前端（复制自 sketches/002-beautiful-workbench，只换数据入口；
                vendor/ 存放 marked 与 highlight.js，来源与许可证见 vendor/README.md）
testdata/       合成 fixture（占位文案，无真实会话）
tests/          unittest（27 个）
docs/           spec / plan / 交付总结 / 测试指南
```

## 开发

```bash
python3 -m unittest discover -s tests -v
```

生产代码改动前必读 [`AGENTS.md`](AGENTS.md)（含 `/ponytail full` 纪律）；`sketches/` 冻结只读。

## 团队分发

目标：成员本机 5 分钟内跑起来，不动各自 agent 的配置。形态就是本仓库 + 一条命令：

1. 分发：把本仓库交给成员（git remote / 打包均可，无需服务端）
2. 成员：`cd repos/ata && ./scripts/serve-dev.sh`，浏览器打开
3. Claude Code / Codex / Droid 成员直接可用（读自己目录，零配置）；Pi 成员按上文装 extension

隐私边界：会话正文只在本机账本 `~/.ata/dev.sqlite`，不外发、不上传。每个成员看到的是自己机器上的轨迹。
