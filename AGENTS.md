# ATA （Agent Trace Analysis） 实现项目约束

领域词汇（会话/轮次/run/标注/任务项等）以仓库根 [`CONTEXT.md`](CONTEXT.md) 为准；命名与文档用语与其冲突时先对照再动笔。

## 1. 编码工作流

在 `repos/ata/` 内创建、修改、重构或删除生产代码前，优先使用以下 skill：

```text
/ponytail full <your coding prompt>
```

## 1.1 常驻服务维护

本机的 ATA trace 服务以 launchd 常驻（label `com.ata.atatrace`，plist 在 `~/Library/LaunchAgents/com.ata.atatrace.plist`），随登录自启，崩溃自动拉起（KeepAlive，已验证）。本机实际部署配置：端口 **17877**，账本 **`~/.ata/ata.sqlite`**（两者已固化在 plist 的 `ATA_PORT` / `ATA_LEDGER` 环境变量中，重新 install 时需继续显式传入这两个变量）。日志 `~/.ata/atatrace.log` / `~/.ata/atatrace.err.log`。Web UI：http://127.0.0.1:17877 。Pi extension 已通过符号链接安装在 `~/.pi/agent/extensions/pi-atatrace`，推送端点由 `~/.zshrc` 中的 `ATA_URL=http://127.0.0.1:17877` 提供（extension 默认指向 8787，换端口后必须显式设置）。

**改完任何生产代码（`ata/`、`web/`、`extensions/`）后**：

1. `make test` 全量测试通过
2. `./scripts/install-service.sh restart` 重建常驻服务（旧进程先杀、立即以新代码拉起）
3. `curl -s http://127.0.0.1:17877/api/health` 确认恢复

其他操作：`./scripts/install-service.sh status` 查看状态；`uninstall` 停止并移除常驻；临时用 `make serve` 前台起服务时，先 `uninstall` 避免端口冲突。改 plist 本身（端口/窗口/日志路径）后同样 `restart` 生效。

## 2. 第三方能力复用优先

- 实现一个组件前，先核对已有依赖、官方扩展和稳定社区包；**“自己写更顺手”不是重复实现的理由**。
- 选择顺序固定为：**原包直接依赖 → 宿主 adapter → 固定上游版本的最小兼容 fork → 自研**。跳到后一档时，必须在 ADR 中留下前一档不可行的源码或运行证据。
- 兼容 fork 保留上游目录、测试、许可证和提交血缘，只改与 Cue 合同冲突的接缝；每个 patch 都要有合同来源、测试、失效条件和可重放的上游同步记录。禁止复制上游源码后改名成为无血缘的本地实现。
- 复用不能破坏第 2 节的事实边界，也不能引入第二事实源、第二 writer、浮动依赖、运行期下载安装或无法回退的远端行为。
- 完全自研同类能力前，spec review 必须确认直接依赖、adapter 与最小 fork 都已被实证排除；否则停止实现并回到复用方案。

## 3. 不得引入的捷径

- 本目录本身是独立 Git 仓库；不得在本仓内部再建立嵌套 Git 仓库，也不得在外层知识库根目录新增 Node 工作区。
- 测试替身只放在测试或 fixture 目录，并通过生产 port 注入；生产入口不得出现演示模式或第二套 runtime。
- 密钥、真实 Base URL、会话正文和用户采集内容不得进入代码、fixture、日志或文档。
- 同一 schema、port、registry、发布清单或事实源同时只能有一个 writer。

## 4. 前端编码规范（webapp/ React 栈）

- **注释只写「读代码得不到的信息」**：为什么这样做、踩过什么坑、外部约束来源。禁止写阶段性/临时性注释（如「脚手架占位」「Phase X 起填充」「TODO 重构」）——计划与进度记录放任务系统或 docs/plans，不进代码；代码合入时它描述的状态已成历史，只剩噪音。
- 视觉体系单一事实源：React 版复用 `web/style.css` 的既有样式（构建期引入），不为同一视觉规则建立第二份 CSS。
- 组件库（beautiful.dev 等）只用于标准控件（按钮/弹层/表单/下拉）的局部增强，不作为设计系统底座；引入新 UI 依赖前按第 2 节复用阶梯走 ADR。
