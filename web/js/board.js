// ata web · 标注板视图：标注/归组的浏览与增删改查。
// 数据全部来自 GET /api/annotations（latest-wins 折叠墓碑后的有效条目）；
// 写入统一走 POST /api/events 追加事件（scored/assigned）或墓碑（cleared/unassigned），
// 账本 append-only，没有物理删除。

    let boardState = { loaded: false, scores: [], assignments: [], runs: [], badOnly: false };
    // 从标注板点进会话时置位：会话页顶栏出现「返回标注板」，回首页/换会话即清除
    let boardReturn = false;

    async function openBoard() {
      setView("board");
      if (!boardState.loaded) await reloadBoard();
    }
    function setView(view) {
      app.dataset.view = view;
      document.getElementById("boardView").hidden = view !== "board";
      document.querySelectorAll("#viewSwitch button").forEach(btn =>
        btn.setAttribute("aria-pressed", String(btn.dataset.view === view)));
      if (view !== "board") {
        // 回会话流：恢复首页/会话态的显隐规则（data-home 逻辑照旧）
        document.getElementById("annoForm").hidden = true;
        document.getElementById("assignForm").hidden = true;
      }
    }

    async function reloadBoard() {
      try {
        const [anno, runs] = await Promise.all([
          fetchJSON("/api/annotations"), fetchJSON("/api/runs")]);
        boardState.scores = anno.scores || [];
        boardState.assignments = anno.assignments || [];
        boardState.runs = runs || [];
        boardState.loaded = true;
      } catch (err) {
        toast("标注板加载失败：" + err.message, "err");
        return;
      }
      paintBoard();
    }

    const boardTerm = () => document.getElementById("q").value.trim().toLowerCase();
    const boardMatch = (title, note, extra) => {
      const term = boardTerm();
      if (!term) return true;
      return [title, note, extra].filter(Boolean).join(" ").toLowerCase().includes(term);
    };

    function paintBoard() {
      const bad = boardState.badOnly;
      const scores = boardState.scores.filter(s =>
        (!bad || s.value === "bad") &&
        boardMatch(s.title, s.note, s.session_id));
      const assigns = boardState.assignments.filter(a =>
        (!bad || a.value === "bad") &&
        boardMatch(a.title, a.task_id, a.run_id));

      document.getElementById("annoCountText").textContent =
        `${boardState.scores.length} 条标注`;
      document.getElementById("assignCountBadge").hidden = !boardState.assignments.length;
      document.getElementById("assignCountText").innerHTML =
        `<b>${new Set(boardState.assignments.map(a => a.run_id)).size}</b> runs · ` +
        `<b>${new Set(boardState.assignments.map(a => a.session_id)).size}</b> 会话已归组`;
      document.getElementById("annoSecCnt").textContent =
        `${scores.length} 条 · 按时间倒序`;
      document.getElementById("assignSecCnt").textContent =
        `${new Set(assigns.map(a => a.run_id)).size} runs · 按任务聚合`;

      // ── 标注列表 ──
      document.getElementById("annoList").innerHTML = scores.length ? scores.map(s => {
        const sid = esc(s.session_id);
        return `
        <div class="arow" data-sid="${sid}">
          <span class="adot" data-v="${esc(s.value)}"></span>
          <span class="vchip" data-v="${esc(s.value)}">${esc(s.value)}</span>
          <span class="who">
            <button class="t" type="button" data-open="${sid}">${esc(s.title || s.session_id)}</button>
            <span class="sub">${esc(AGENT_LABELS[s.agent] || s.agent || "?")} · ${Number(s.event_count ?? 0)} evts${Number(s.error_count ?? 0) ? ` · ${Number(s.error_count)} failed` : ""} · ${shortTime(Number(s.ts))}</span>
          </span>
          <span class="note">${s.note ? esc(s.note) : "<i>（无备注）</i>"}</span>
          <span class="ts">${fullTime(Number(s.ts))}</span>
          <span class="acts">
            <button class="icon-btn" data-edit="${sid}" title="编辑标注"><svg class="ico"><use href="#i-edit"/></svg></button>
            <button class="icon-btn danger" data-clear="${sid}" title="删除标注（追加 cleared 墓碑，历史可追溯）"><svg class="ico"><use href="#i-trash"/></svg></button>
          </span>
        </div>`;
      }).join("") : `<div class="board-empty">暂无标注${bad ? "（bad 过滤中）" : ""} —— 打开一条会话，在顶栏「标注」里打分</div>`;

      // ── 归组列表：run → task → 会话 ──
      const byRun = new Map();
      for (const a of assigns) {
        if (!byRun.has(a.run_id)) byRun.set(a.run_id, []);
        byRun.get(a.run_id).push(a);
      }
      const runMeta = new Map(boardState.runs.map(r => [r.run_id, r]));
      document.getElementById("runList").innerHTML = byRun.size ? [...byRun.entries()].map(([rid, list]) => {
        const meta = runMeta.get(rid) || {};
        const byTask = new Map();
        for (const a of list) {
          if (!byTask.has(a.task_id)) byTask.set(a.task_id, []);
          byTask.get(a.task_id).push(a);
        }
        const tasks = [...byTask.entries()].map(([tid, sess]) => `
          <div class="task">
            <span class="task-id">${esc(tid)}</span>
            <div class="task-sessions">
              ${sess.map(a => `
              <div class="tsess">
                <button class="t" type="button" data-open="${esc(a.session_id)}">${esc(a.title || a.session_id)}</button>
                <span class="adot" ${sValueOf(a.session_id)}></span>
                <span class="meta">${esc(AGENT_LABELS[a.agent] || a.agent || "?")} · ${Number(a.event_count ?? 0)} evts · ${shortTime(Number(a.ts))}</span>
                <button class="icon-btn danger" data-unassign="${esc(a.session_id)}|${esc(rid)}" title="移出归组（追加 unassigned 墓碑）"><svg class="ico"><use href="#i-x"/></svg></button>
              </div>`).join("")}
              <button class="add-sess" type="button" data-addto="${esc(tid)}|${esc(rid)}">+ 挂会话</button>
            </div>
          </div>`).join("");
        return `
        <div class="run">
          <div class="run-head">
            <b>${esc(rid)}</b>
            <span class="fp">${esc(meta.description || "")}${meta.created_ts ? ` · ${fullTime(Number(meta.created_ts))} 建` : ""}</span>
            <span class="grow"></span>
            <span class="cnt">${byTask.size} 任务 · ${list.length} 会话</span>
            <span class="acts">
              <button class="icon-btn danger" data-drun="${esc(rid)}" title="移出该 run 全部归组（逐条墓碑）"><svg class="ico"><use href="#i-trash"/></svg></button>
            </span>
          </div>
          <div class="run-body">${tasks}</div>
        </div>`;
      }).join("") : `<div class="board-empty">暂无归组 —— 在会话页「归组」或点右上「新建归组」</div>`;

      bindBoardActions();
    }
    // 会话当前标注值（归组行上的小点）；没标注返回空心
    function sValueOf(sid) {
      const s = boardState.scores.find(x => x.session_id === sid);
      return s ? `data-v="${esc(s.value)}"` : "";
    }

    function bindBoardActions() {
      document.querySelectorAll("#annoList [data-open], #runList [data-open]").forEach(el =>
        el.addEventListener("click", () => { boardReturn = true; setView("sessions"); openSession(el.dataset.open); }));
      document.querySelectorAll("#annoList [data-clear]").forEach(btn =>
        btn.addEventListener("click", async () => {
          await postBoardEvent({
            type: "session.score.cleared", session_id: btn.dataset.clear, payload: {},
            ok: "已删除标注", fail: "删除失败"
          });
        }));
      document.querySelectorAll("#annoList [data-edit]").forEach(btn =>
        btn.addEventListener("click", () => openAnnoForm(btn.dataset.edit)));
      document.querySelectorAll("#runList [data-unassign]").forEach(btn => {
        const [sid, rid] = btn.dataset.unassign.split("|");
        btn.addEventListener("click", async () => {
          await postBoardEvent({
            type: "session.unassigned", session_id: sid, payload: { run_id: rid },
            ok: "已移出归组", fail: "移出失败"
          });
        });
      });
      document.querySelectorAll("#runList [data-drun]").forEach(btn =>
        btn.addEventListener("click", async () => {
          const rid = btn.dataset.drun;
          const list = boardState.assignments.filter(a => a.run_id === rid);
          for (const a of list) {
            await postBoardEvent({
              type: "session.unassigned", session_id: a.session_id,
              payload: { run_id: rid }, ok: null, fail: "移出失败"
            });
          }
          if (list.length) toast(`已移出 ${list.length} 条归组`);
        }));
      // 「+ 挂会话」：预选 run/task 打开归组表单
      document.querySelectorAll("#runList [data-addto]").forEach(btn => {
        const [tid, rid] = btn.dataset.addto.split("|");
        btn.addEventListener("click", () => openAssignForm(tid, rid));
      });
    }

    // 写入统一通道：组一条 v1 事件 POST /api/events，成功后重拉聚合。
    async function postBoardEvent({ type, session_id, payload, ok, fail }) {
      const s = boardState.scores.find(x => x.session_id === session_id)
        || boardState.assignments.find(x => x.session_id === session_id);
      const agent = s?.agent || sessions.find(x => x.id === session_id)?.agent;
      if (!agent) { toast(fail + "：未知会话", "err"); return; }
      const body = {
        v: 1, id: crypto.randomUUID().replace(/-/g, ""),
        agent_id: agent, session_id,
        ts: Date.now(), type, turn: null, payload
      };
      try {
        const res = await fetch(API + "/api/events", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body)
        });
        if (!res.ok) throw new Error((await res.json()).error || res.status);
        if (ok) toast(ok);
        await reloadBoard();
      } catch (err) {
        toast(fail + "：" + err.message, "err");
      }
    }

    // ── 标注表单（新增/编辑共用）──
    let annoFormValue = "good";
    let annoFormTarget = null; // 编辑态的 session_id
    function fillSessionSelect(sel, preferred) {
      const box = document.getElementById(sel);
      box.innerHTML = sessions.map(s =>
        `<option value="${esc(s.id)}">${esc((s.title || s.id).slice(0, 40))}（${esc(AGENT_LABELS[s.agent] || s.agent)} · ${Number(s.eventCount ?? 0)} evts）</option>`).join("");
      if (preferred) box.value = preferred;
    }
    function openAnnoForm(sid) {
      annoFormTarget = sid || null;
      document.getElementById("annoFormTitle").textContent = sid ? "编辑标注" : "新增标注";
      fillSessionSelect("annoSession", sid);
      const existing = sid && boardState.scores.find(x => x.session_id === sid);
      setAnnoValue(existing?.value || "good");
      document.getElementById("annoNote").value = existing?.note || "";
      document.getElementById("annoForm").hidden = false;
      document.getElementById("annoSession").disabled = !!sid;
    }
    function setAnnoValue(v) {
      annoFormValue = v;
      document.querySelectorAll("#annoForm [data-fv]").forEach(btn =>
        btn.setAttribute("aria-pressed", String(btn.dataset.fv === v)));
    }
    document.querySelectorAll("#annoForm [data-fv]").forEach(btn =>
      btn.addEventListener("click", () => setAnnoValue(btn.dataset.fv)));
    document.getElementById("addAnnoBtn").addEventListener("click", (e) => {
      e.stopPropagation();
      if (!sessions.length) { toast("暂无会话可标注", "err"); return; }
      const wasHidden = document.getElementById("annoForm").hidden;
      document.getElementById("assignForm").hidden = true;
      if (wasHidden) openAnnoForm(null); else document.getElementById("annoForm").hidden = true;
    });
    document.getElementById("annoCancel").addEventListener("click", () => {
      document.getElementById("annoForm").hidden = true;
    });
    document.getElementById("annoForm").addEventListener("click", e => e.stopPropagation());
    document.getElementById("annoSave").addEventListener("click", async () => {
      const sid = document.getElementById("annoSession").value;
      if (!sid) { toast("先选会话", "err"); return; }
      const note = document.getElementById("annoNote").value.trim();
      await postBoardEvent({
        type: "session.scored", session_id: sid,
        payload: note ? { value: annoFormValue, note } : { value: annoFormValue },
        ok: `已标注：${annoFormValue}`, fail: "标注写入失败"
      });
      document.getElementById("annoForm").hidden = true;
      // 会话页顶栏徽章/卡片点同步
      if (current.id === sid) { await refreshTail(true); paintScore(); }
    });

    // ── 归组表单 ──
    function openAssignForm(preTask, preRun) {
      if (!sessions.length) { toast("暂无会话可归组", "err"); return; }
      document.getElementById("annoForm").hidden = true;
      fillSessionSelect("assignSession", current.id || null);
      const runSel = document.getElementById("assignRun2");
      runSel.innerHTML = (boardState.runs.length ? boardState.runs : [])
        .map(r => `<option value="${esc(r.run_id)}">${esc(r.run_id)} · ${esc(r.description || "")}</option>`).join("");
      if (!boardState.runs.length) {
        runSel.innerHTML = `<option value="">（无 run，去 CLI: ata run new）</option>`;
      }
      document.getElementById("assignTask2").value = preTask || "";
      if (preRun) runSel.value = preRun;
      document.getElementById("assignForm").hidden = false;
    }
    document.getElementById("addAssignBtn").addEventListener("click", (e) => {
      e.stopPropagation();
      const wasHidden = document.getElementById("assignForm").hidden;
      document.getElementById("annoForm").hidden = true;
      if (wasHidden) openAssignForm(); else document.getElementById("assignForm").hidden = true;
    });
    document.getElementById("assignCancel").addEventListener("click", () => {
      document.getElementById("assignForm").hidden = true;
    });
    document.getElementById("assignForm").addEventListener("click", e => e.stopPropagation());
    document.getElementById("assignSave").addEventListener("click", async () => {
      const sid = document.getElementById("assignSession").value;
      const rid = document.getElementById("assignRun2").value;
      const tid = document.getElementById("assignTask2").value.trim();
      if (!sid || !rid || !tid) { toast("会话、run、任务 id 都要填", "err"); return; }
      await postBoardEvent({
        type: "session.assigned", session_id: sid,
        payload: { run_id: rid, task_id: tid },
        ok: `已归组：${tid} → ${rid}`, fail: "归组写入失败"
      });
      document.getElementById("assignForm").hidden = true;
    });

    // ── 过滤 / 搜索 / 视图切换绑定 ──
    document.getElementById("badFilter").addEventListener("click", (e) => {
      boardState.badOnly = !boardState.badOnly;
      e.currentTarget.setAttribute("aria-pressed", String(boardState.badOnly));
      paintBoard();
    });
    document.getElementById("q").addEventListener("input", () => {
      if (app.dataset.view === "board") paintBoard();
    });
    document.querySelectorAll("#viewSwitch button").forEach(btn =>
      btn.addEventListener("click", () => {
        if (btn.dataset.view === "board") openBoard();
        else { setView("sessions"); showHome(); }
      }));
    // 点击外部收起两个表单
    document.addEventListener("click", (e) => {
      for (const [formId, btnId] of [["annoForm", "addAnnoBtn"], ["assignForm", "addAssignBtn"]]) {
        const form = document.getElementById(formId), btn = document.getElementById(btnId);
        if (form && !form.hidden && !form.contains(e.target) && !btn.contains(e.target)) {
          form.hidden = true;
        }
      }
    });
