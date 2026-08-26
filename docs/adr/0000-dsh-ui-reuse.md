# ADR：ATA 展示层对标 dsh Trajectory 的复用决策

- **日期**：2026-08-16
- **范围**：`repos/ata` 前端展示层与数据面
- **参照对象**：DeepSeek Harness（dsh）Trajectory，检出锚点 `repos-external/deepseek-harness` @ `47f943859b`（package `0.1.0-rc.5`，MIT）
- **结论**：不搬 dsh 前端代码，落「对齐重写」档；两个渲染库（marked、highlight.js）走「原包直接依赖」档以文件形式 vendored。

## 背景

ATA 阅读器的目标是把四个 agent 的会话语料统一成一张轨迹账本。用户希望展示完成度对齐 dsh 的 Trajectory（信息密度、Markdown 渲染、检查器细节），同时不重复造轮子。dsh 是 MIT 开源，工程上先按本项目 AGENTS.md 第 2 节的复用阶梯逐档核验，再决定怎么落地。

## 复用阶梯逐档核验

### 第一档：原包直接依赖 —— 不可行

dsh 的 Trajectory 不提供可供独立安装的前端资产：

- `apps/web` 不是独立应用，启动必须由 `dsh web` 注入 `window.__DSH_BOOT__` 与静态资源宿主（`apps/web/vite.config.ts` 的 boot manifest，`packages/host/frontend-static`），脱离 dsh 宿主直接 serve 会拒绝运行。
- 前端数据不是静态 JSON：历史走 RPC `POST /api/session.history`，增量走 WebSocket `/api/events.mux`，服务端把磁盘 JSONL(zstd) 分页后下发（`packages/host/apiproxy/src/api-proxy.ts`），没有可单独消费的产物。

ATA 的数据通道（本地 SQLite 账本 + `GET /api/sessions/{id}`）与之形态不同，直连 dsh 后端等于引入第二运行时，违反「同一 schema、port 同时只能有一个 writer」与本地优先约束。

### 第二档：宿主 adapter —— 不可行

Trajectory 组件强绑定 dsh 的会话对象层：`conversation.view` 插件 slot、`SessionEvent` 事件模型、`conversation-assembler` + 五种 Definition（message / request-header / assistant / tool / compaction）在浏览器里投影。把 ATA 的统一事件适配成这套模型，等于搬 dsh 的半个 client runtime 进来（`dsh-agent`、`dsh-tools`、`dsh-compaction`、`dsh-client-runtime` 都是类型依赖），且 ATA 的四种语料信息量小于 dsh 事件模型，适配层造出来的数据面仍然是空态。

### 第三档：最小兼容 fork —— 不可行

- dsh 前端是 React 18 + Vite + Cordis 插件树 + CSS Modules（`--dsw-*` token）生态；本项目硬约束「不得在外层知识库根目录新增 Node 工作区」「零构建」，fork 进来等于把构建链和运行时一起搬。
- 唯一相对可拆的 `packages/client/ui-primitives`（MarkdownText / JsonTree / Tooltip）是 React + TS 源码，无 UMD 产物，仍然过不了零构建这一关。

### 第四档：对齐重写 —— 采纳

- 把 dsh Trajectory 的展示细节逐项当作规格（explorer 调研锚定 `47f943859b`），对照 ATA 现有实现做差距补齐，不搬运组件源码。
- 两个渲染库按第一档以文件形式 vendored：marked 18.0.9（MIT）与 highlight.js 11.12.0（BSD-3），收进 `web/vendor/`，随仓库分发、无运行期下载（来源与许可证见 `web/vendor/README.md`）。
- 数据面以语料真实可得为界：usage 明细（total_tokens/cost）、工具目录索引、thinking 分离属可得；TTFT/decoding/subtool 属 dsh 事件模型独有、四种语料无源，保持空态并在差距清单中留档。

## 证据锚点

- dsh 检出提交：`47f943859bef60e4160492346772ded9b24f765a`
- `apps/web/vite.config.ts`（boot manifest 要求）、`packages/client/ui-trajectory/src/client/index.ts`（slot 注册）、`trajectory-contract.ts`（前端消费的投影类型）、`packages/host/apiproxy/src/api-proxy.ts`（history/mux 数据面）
- 本仓库对象档案：`Agent研究/deepseek-harness/README.md`（引用边界与证据标签）

## 失效条件与升级路径

- 若未来 ATA 放弃零构建约束并接受 React 工程，可重新评估把 `ui-trajectory` 的 `TrajectoryTable`/`MarkdownText` 作为上游直接依赖或最小 fork（保留上游目录、测试、许可证与提交血缘）。
- 若 dsh 后续发布独立可用的前端资产（拆除 `__DSH_BOOT__`），回到第一档重新核验。
