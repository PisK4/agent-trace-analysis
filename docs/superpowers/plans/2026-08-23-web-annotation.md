# Web UI 标注控件实施计划（T9 收尾）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 兑现 T9 Resolution 第 2 点的 Web UI 部分：会话回看视图加「好 / 不好 / 部分 + 备注」标注控件，写入走已有的 `POST /api/events`（`session.scored`），读取复用现有投影，不加新端点。

**Architecture:** 两处改动。`ata/project.py` 的 `project_session` 补一个 `session.scored` 分支，在返回体里透出 `scores` 数组；`web/index.html` 在顶栏加一组标注按钮和备注输入框，提交后本地追加并重绘。事件仍是追加门一条写路径，schema 不动。

**Tech Stack:** Python 标准库 + unittest；前端是单文件原生 JS（innerHTML 渲染、无构建步骤），零新依赖。

**Spec:** 接口形状沿用 `docs/specs/agent-read-interface.md`；决议背景见 `docs/wayfinder/tickets/T9-human-annotation.md`（本计划是其 Progress notes 里「留待第二份计划」的那一份）。

## 现状摸底结论（2026-08-23）

- 前端是 `web/index.html` 单文件应用：全局状态变量 + `paint()` 全量重绘，inspector 由 `paintInspector()` 按 tab 渲染进 `#dBody`。
- `project_session`（`ata/project.py`）目前没有 `session.scored` 分支，标注事件被静默丢弃；前端因此拿不到任何标注数据。
- `POST /api/events` 已存在且过 schema 校验，CLI `rate` 已在生产使用，前端直接复用即可。
- 工作区有两处未提交改动：`web/index.html`（CSS 全屏化微调）和 T10 票文件。**开工前先与用户确认这两处怎么处理**；若随本计划一起提交，commit message 需提及，不得混入无关内容还不声明。

## Global Constraints

- 纯 Python 标准库，禁止引入任何第三方依赖（含测试）。
- 事件 `v` 保持 `1`；schema 不改；所有写入仍走服务进程的事件追加门，前端只发 HTTP，不碰 SQLite。
- 密钥、真实会话正文不得进入代码、fixture、日志、文档。
- 生产代码改动后必须：`make test` 全量通过 → `./scripts/install-service.sh restart` → `curl -s http://127.0.0.1:17877/api/health` 返回 `{"ok": true}`。
- 测试命令统一：`make test`（即 `python3 -m unittest discover -s tests -v`）。
- 前端无测试设施，Task 2 以人工冒烟清单验收，不为此引入 JS 测试框架。

---

### Task 1: 投影层透出 scores

**Files:**
- Modify: `ata/project.py`（`project_session` 内加一个分支 + 返回体加一键）
- Test: `tests/test_score_projection.py`（新建）

**Interfaces:**
- Produces: `/api/sessions/{sid}` 返回体新增 `"scores"` 键：按发生顺序排列的 `{"value", "note", "ts"}` 数组，`note` 可为 None。重复标注全部保留（追加门语义：每次标注都是发生过的事实），前端取末条为当前值。
- 明确不做：把标注渲染成表格行、编辑/撤销标注、数值型评分。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_score_projection.py
import unittest
from ata.project import project_session


def rec(seq, typ, payload, turn=None):
    return {"seq": seq, "event": {"v": 1, "id": f"e{seq}", "agent_id": "cue",
            "session_id": "s", "ts": seq * 1000, "type": typ, "turn": turn,
            "payload": payload}}


class TestScoreProjection(unittest.TestCase):
    def test_scores_in_order_with_notes(self):
        recs = [
            rec(1, "session.opened", {"title": "t"}),
            rec(2, "session.scored", {"value": "bad", "note": "方向跑偏"}),
            rec(3, "message.upserted", {"message_id": "m1", "role": "user",
                                        "text": "hi", "status": "completed"}, turn=1),
            rec(4, "session.scored", {"value": "good"}),
        ]
        page = project_session("s", "cue", recs)
        self.assertEqual(page["scores"], [
            {"value": "bad", "note": "方向跑偏", "ts": 2000},
            {"value": "good", "note": None, "ts": 4000},
        ])
        # 标注不混进内容行
        self.assertTrue(all(row["kind"] != "score" for row in page["rows"]))

    def test_no_scores_is_empty_list(self):
        page = project_session("s", "cue", [rec(1, "session.opened", {"title": "t"})])
        self.assertEqual(page["scores"], [])

    def test_tail_window_keeps_all_scores(self):
        recs = [
            rec(1, "session.opened", {"title": "t"}),
            rec(2, "session.scored", {"value": "partial", "note": "一半可用"}),
            rec(3, "session.scored", {"value": "bad"}),
        ]
        page = project_session("s", "cue", recs, tail=1)
        self.assertEqual(len(page["scores"]), 2)


if __name__ == "__main__":
    unittest.main()
```

第三个用例钉住一个行为：`tail` 只裁剪内容行，标注是会话级事实，不随窗口裁剪。

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest tests.test_score_projection -v`
Expected: FAIL（KeyError: 'scores'）

- [ ] **Step 3: 最小实现**

`ata/project.py` `project_session`：

初始化区（`turn_usage = {}` 一带）加 `scores = [];`。

分支放在 `if ev["type"] == "session.opened":` 之后：

```python
        if ev["type"] == "session.scored":
            scores.append({"value": p.get("value"), "note": p.get("note"), "ts": ev["ts"]})
            continue
```

返回体字典加一项：

```python
        "scores": scores,
```

注意分支必须用 `continue` 且排在 message/tool 等分支之前，避免落入其他 elif；`p` 已在循环头解包。

- [ ] **Step 4: 跑测试确认通过**

Run: `make test`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add ata/project.py tests/test_score_projection.py
git commit -m "feat(project): expose session.scored annotations in session projection"
```

---

### Task 2: 前端标注控件

**Files:**
- Modify: `web/index.html`（顶栏 HTML 一块、CSS 一小节、JS 三处）

**Interfaces:**
- Consumes: `/api/sessions/{sid}` 的 `scores`（Task 1）；`POST /api/events`。
- Produces: 打开会话后顶栏出现标注区：当前标注徽章 + 备注输入框 + Good/Bad/Partial 三键。点按钮即写入并即时更新徽章；徽章 hover 显示最近备注。

- [ ] **Step 1: HTML**

`.top` 头部里 `<span class="mode-chip" id="modeChip">sequence</span>` 之后插入：

```html
<div class="score" id="scoreBox" hidden>
  <span class="score-badge" id="scoreBadge" hidden></span>
  <input class="score-note" id="scoreNote" type="text" placeholder="备注（可选）" maxlength="200" />
  <button class="ghost" type="button" data-score="good">Good</button>
  <button class="ghost" type="button" data-score="bad">Bad</button>
  <button class="ghost" type="button" data-score="partial">Partial</button>
</div>
```

- [ ] **Step 2: CSS**

样式表追加一节（复用现有变量，明暗主题自动生效）：

```css
.score { display: flex; align-items: center; gap: 6px; }
.score[hidden] { display: none; }
.score-note {
  width: 150px; padding: 3px 8px; border-radius: 6px;
  background: var(--field); box-shadow: var(--shadow-inset-field);
  border: 0; outline: none;
}
.score-badge {
  padding: 2px 8px; border-radius: 999px;
  font-size: 11px; font-weight: 600;
  max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.score-badge[data-value="good"] { background: var(--green-tint); color: var(--green); }
.score-badge[data-value="bad"] { background: var(--red-tint); color: var(--red); }
.score-badge[data-value="partial"] { background: var(--orange-tint); color: var(--orange); }
```

- [ ] **Step 3: JS**

① `loadSession` 返回对象加一行（随 1 秒轮询刷新，别处打的标注也会自动出现）：

```js
        scores: page.scores || [],
```

② 新增渲染函数，并在 `paint()` 里调用（`paintInspector();` 之前）：

```js
    function paintScore() {
      const box = document.getElementById("scoreBox");
      if (!current.id) { box.hidden = true; return; }
      box.hidden = false;
      const badge = document.getElementById("scoreBadge");
      const list = current.scores || [];
      const latest = list[list.length - 1];
      badge.hidden = !latest;
      if (latest) {
        badge.dataset.value = latest.value;
        badge.textContent = latest.value + (latest.note ? ` · ${latest.note}` : "");
        badge.title = `${list.length} 条标注${latest.note ? ` · 最近：${latest.note}` : ""}`;
      }
    }
```

文案走 `textContent` / `title`，天然转义，备注不需要再 esc。

③ 提交处理，绑一次（放在 `followBtn` 监听器附近的一次性绑定区，不要放进 `paintTable` 的行级绑定里）：

```js
    document.getElementById("scoreBox").addEventListener("click", async (event) => {
      const btn = event.target.closest("[data-score]");
      if (!btn || !current.id) return;
      const note = document.getElementById("scoreNote").value.trim();
      const payload = note ? { value: btn.dataset.score, note } : { value: btn.dataset.score };
      const body = {
        v: 1, id: crypto.randomUUID().replace(/-/g, ""),
        agent_id: current.agent, session_id: current.id,
        ts: Date.now(), type: "session.scored", turn: null, payload
      };
      try {
        const res = await fetch(API + "/api/events", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body)
        });
        if (!res.ok) throw new Error((await res.json()).error || res.status);
        current.scores = [...(current.scores || []),
          { value: payload.value, note: note || null, ts: body.ts }];
        document.getElementById("scoreNote").value = "";
        paintScore();
      } catch (err) {
        window.alert("标注写入失败：" + err.message);
      }
    });
```

`agent_id` 取 `current.agent`（打开会话时已带），与 CLI rate 从账本查 agent 同源。失败时 alert 报服务端 error 字段，不静默。

- [ ] **Step 4: 人工冒烟清单**

Run: `./scripts/install-service.sh restart && sleep 2 && curl -s http://127.0.0.1:8787/api/health`
Expected: `{"ok": true}`

浏览器开 http://127.0.0.1:17877 ，逐项核对：

1. 未选会话时不显示标注区；打开任一会话后出现。
2. 点 Good（可先填一句备注）：徽章立即变绿显示值与备注；`curl -s "http://127.0.0.1:17877/api/sessions/<sid>/events?limit=5"` 能看到 `session.scored`。
3. 刷新页面：徽章仍在（数据来自投影而非本地状态）。
4. 连打两次不同值：徽章取最新，title 显示「2 条标注」。
5. 暗色主题下三色徽章可读；空备注直接点按钮不报错。
6. 对同一 sid 跑 `ATA_URL=http://127.0.0.1:17877 python3 -m ata read usage <sid>` 不受影响（回归确认投影没被改坏）。

- [ ] **Step 5: Commit**

```bash
git add web/index.html
git commit -m "feat(web): session annotation controls posting session.scored events"
```

---

### Task 3: 收尾 —— 回归、真机验证、票目回写

**Files:** 仅文档回写；无代码改动。

- [ ] **Step 1: 全量回归**

Run: `make test`
Expected: 全部 PASS

- [ ] **Step 2: 生产服务重启与健康检查**

Run: `./scripts/install-service.sh restart && sleep 2 && curl -s http://127.0.0.1:17877/api/health`
Expected: `{"ok": true}`

- [ ] **Step 3: 端到端闭环**

对同一个真实会话分别用 Web UI 和 CLI 各打一条标注，然后核对两边都可见：

```bash
ATA_URL=http://127.0.0.1:17877 python3 -m ata rate <sid> --value partial --note cli-side
sqlite3 -readonly ~/.ata/ata.sqlite \
  "SELECT payload_json FROM events WHERE type='session.scored' ORDER BY seq DESC LIMIT 3"
```

Expected: Web 徽章显示 `partial · cli-side`（轮询自动带上 CLI 写的那条）；账本里两条来源不同的标注共存。

- [ ] **Step 4: 回写 T9 票**

在 `docs/wayfinder/tickets/T9-human-annotation.md` Progress notes 追加一段：Web UI 控件落地日期、实现方式（投影透出 scores + 顶栏控件直发 /api/events）、端到端闭环结果。Resolution 第 2 点至此完整兑现，票保持 closed 不需要 reopen。

- [ ] **Step 5: Commit**

```bash
git add docs/wayfinder/
git commit -m "docs(wayfinder): close out T9 web annotation entry"
```

---

## Self-Review 记录

1. **范围对齐**：只补 T9 明确欠的两块——投影读路径与 Web 写入入口。新端点、标注编辑/撤销、逐消息评分、数值型评分都不做，与「主观标注是锚」的最小闭环一致。
2. **写路径唯一性**：前端与 CLI 走同一条 `POST /api/events` 追加门，无第二 writer。
3. **类型一致性**：投影 `scores` 元素 `{value, note, ts}` 与前端 `paintScore`/提交后的本地追加形状一致；`note` 缺省统一为 None/null。
4. **已知风险**：工作区那处 `web/index.html` 的 CSS 微调会和 Task 2 改动落在同一文件，提交前需按「现状摸底结论」最后一项与用户确认归属，避免混提交。
