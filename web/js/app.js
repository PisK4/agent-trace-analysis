// ata web · 应用编排：boot、paint 总入口、选择/翻页/轮询、控件与 resize 绑定

    async function boot() {
      const list = await fetchJSON("/api/sessions");
      sidebarFingerprint = sidebarPrint(list);
      sessions = list.map(item => ({
        id: item.id,
        agent: item.agent,
        title: item.title,
        crumb: `${item.agent} · <b>${item.title}</b>`,
        rows: [],
        older: false,
        cursor: 0,
        turns: item.turns,
        firstTs: item.first_ts,
        eventCount: item.event_count,
        errorCount: item.error_count,
        toolsIndex: {}
      }));
      paintTabs();
      paintSessions();
      showHome();
    }
    function paintScore() {
      // 标注/归组收成 Badge：这里只更新徽章可见性与状态文字，弹出面板由 bindPopover 管理。
      const annoBtn = document.getElementById("scoreBadgeBtn");
      const assignBtn = document.getElementById("assignBadgeBtn");
      const annoPop = document.getElementById("scoreBox");
      const assignPop = document.getElementById("assignBox");
      if (!current.id) {
        annoBtn.hidden = true; assignBtn.hidden = true;
        annoPop.hidden = true; assignPop.hidden = true;
        return;
      }
      annoBtn.hidden = false; assignBtn.hidden = false;
      ensureRunsLoaded();
      // 侧栏卡片的标注点由 pollSessions 的指纹门控统一刷新（scores 变化会改指纹），
      // 这里不再每次 paintScore 都重建侧栏——那会让 hover/滚动每秒死一次。
      const txt = document.getElementById("annoBadgeText");
      const dot = document.getElementById("scoreDot");
      const list = current.scores || [];
      const latest = list[list.length - 1];
      if (latest) {
        dot.dataset.v = latest.value;
        txt.textContent = latest.value + (latest.note ? ` · ${latest.note}` : "");
        annoBtn.title = `${list.length} 条标注${latest.note ? ` · 最近：${latest.note}` : ""}`;
      } else {
        delete dot.dataset.v;
        txt.textContent = "未标注";
        annoBtn.title = "尚未标注";
      }
    }

    function paint() {
      suppressOlder = true;
      paintOverview();
      paintTable();
      paintScore();
      paintToolStatsBar();
      paintInspector();
      requestAnimationFrame(() => {
        lastScrollTop = scroller.scrollTop;
        suppressOlder = false;
      });
    }

    function selectRecord(id, opts = {}) {
      const row = byId(id);
      if (!row) return;
      const focus = focusSet();
      if (opts.fromTable && focus && !focus.has(id)) range = null;
      selected = { type: "record", id };
      if (opts.clearRange) range = null;
      restoreTab(selected);
      paint();
      const tr = tbody.querySelector(`tr[data-id="${id}"]`);
      if (tr) tr.scrollIntoView({ block: "nearest" });
    }
    function selectRequest(id) {
      selected = { type: "request", id };
      restoreTab(selected);
      paint();
    }
    function focusRecord(id) {
      const tr = tbody.querySelector(`tr[data-id="${id}"]`);
      if (tr) tr.scrollIntoView({ block: "nearest" });
    }

    function toggleTurn(turn) {
      if (collapsedTurns.has(turn)) collapsedTurns.delete(turn);
      else collapsedTurns.add(turn);
      paint();
    }
    function toggleAssistant(id) {
      if (collapsedAssistants.has(id)) collapsedAssistants.delete(id);
      else collapsedAssistants.add(id);
      paint();
    }

    async function openSession(id) {
      // epoch 守卫：openSession 可能被并发触发（快速连点两个会话），只有「最后一次
      // 点击」的结果才允许落地。用请求序号判定，过期响应直接丢弃。
      const epoch = ++sessionEpoch;
      let next;
      try {
        next = await loadSession(id);
      } catch (err) {
        toast("会话加载失败：" + err.message, "err");
        return;
      }
      if (epoch !== sessionEpoch || !next) return;
      const idx = sessions.findIndex(session => session.id === next.id);
      // 详情接口不返回 first_ts 等列表字段，合并保留，避免卡片时间变成 —
      if (idx >= 0) sessions[idx] = { ...sessions[idx], ...next }; else sessions.push(next);
      current = next;
      sessionRev = next.rev || 0;
      selected = next.rows.length ? { type: "record", id: next.rows[next.rows.length - 1].id } : null;
      range = null;
      draft = null;
      viewport = null;
      tab = "summary";
      tabHistory = ["summary"];
      collapsedTurns = new Set();
      collapsedAssistants = new Set();
      searchQuery = "";
      tableFilter = "";
      resetSessionPanels();
      syncFilterChips();
      document.getElementById("q").value = "";
      document.getElementById("crumb").innerHTML = next.crumb;
      const sidBox = document.getElementById("sidBox");
      sidBox.textContent = next.id;
      sidBox.hidden = false;
      document.getElementById("copySidBtn").hidden = false;
      document.getElementById("renameBtn").hidden = false;
      // 从标注板点进来的会话：顶栏给一个返回入口
      document.getElementById("boardBackBtn").hidden = !boardReturn;
      app.dataset.home = "";
      paintSessions();
      paint();
      refreshToolStats();
      refreshUsage();
      requestAnimationFrame(() => { scroller.scrollTop = scroller.scrollHeight; });
    }

    async function loadOlder() {
      if (loadingOlder || !current.older) return;
      loadingOlder = true;
      paint();
      const sid = current.id;
      const prevHeight = scroller.scrollHeight;
      const prevTop = scroller.scrollTop;
      let page;
      try {
        page = await loadSession(sid, `?before=${current.cursor}&limit=36`);
      } catch { loadingOlder = false; paint(); return; }
      if (sid !== current.id) { loadingOlder = false; return; } // epoch 守卫：已换会话
      const have = new Set(current.rows.map(r => r.id));
      const prepend = page.rows.filter(r => !have.has(r.id)).map(r => ({ ...r, _keptOlder: true }));
      current.rows = [...prepend, ...current.rows].map((row, i) => ({ ...row, index: i }));
      current.older = page.older;
      current.cursor = page.cursor;
      sessionRev = page.rev || sessionRev;
      loadingOlder = false;
      paint();
      scroller.scrollTop = prevTop + (scroller.scrollHeight - prevHeight);
    }
    earlierBtn.addEventListener("click", () => loadOlder());
    document.getElementById("q").addEventListener("input", (event) => {
      searchQuery = event.currentTarget.value;
      paint();
    });
    document.getElementById("homeBtn").addEventListener("click", showHome);
    // 侧栏折叠开关：收起时主区占满整行。
    document.getElementById("navToggle").addEventListener("click", () => {
      const hidden = document.body.classList.toggle("nav-hidden");
      document.getElementById("navToggle").setAttribute("aria-pressed", String(hidden));
    });
    // 统一弹层管理（标注 / 归组 / 视图菜单）：点击徽章切换展开，点击外部收起。
    function bindPopover(btnId, panelId) {
      const btn = document.getElementById(btnId), panel = document.getElementById(panelId);
      if (!btn || !panel) return;
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const open = panel.hidden;
        panel.hidden = !open;
        btn.setAttribute("aria-expanded", String(open));
      });
    }
    document.addEventListener("click", (e) => {
      [["scoreBadgeBtn", "scoreBox"], ["assignBadgeBtn", "assignBox"], ["viewMenuBtn", "viewMenu"]]
        .forEach(([btnId, panelId]) => {
          const btn = document.getElementById(btnId), panel = document.getElementById(panelId);
          if (!btn || !panel || panel.hidden) return;
          if (!panel.contains(e.target) && !btn.contains(e.target)) {
            panel.hidden = true;
            btn.setAttribute("aria-expanded", "false");
          }
        });
    });
    bindPopover("scoreBadgeBtn", "scoreBox");
    bindPopover("assignBadgeBtn", "assignBox");
    bindPopover("viewMenuBtn", "viewMenu");
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
        // 提交成功即收起弹层，Badge 状态由 paintScore 更新。
        document.getElementById("scoreBox").hidden = true;
        document.getElementById("scoreBadgeBtn").setAttribute("aria-expanded", "false");
        paintScore();
        toast(`已标注：${payload.value}`);
      } catch (err) {
        toast("标注写入失败：" + err.message, "err");
      }
    });
    // 清除选中：点表格空白处即可，右栏常驻不消失（收起整栏走右缘 detailsHandle）。
    document.getElementById("assignBtn").addEventListener("click", async () => {
      if (!current.id) return;
      const runId = document.getElementById("assignRun").value;
      const taskId = document.getElementById("assignTask").value.trim();
      if (!runId || !taskId) { toast("先选 run 并填任务 id（ata tasks list 可查）", "err"); return; }
      const body = {
        v: 1, id: crypto.randomUUID().replace(/-/g, ""),
        agent_id: current.agent, session_id: current.id,
        ts: Date.now(), type: "session.assigned", turn: null,
        payload: { run_id: runId, task_id: taskId }
      };
      try {
        const res = await fetch(API + "/api/events", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body)
        });
        if (!res.ok) throw new Error((await res.json()).error || res.status);
        toast(`已归组：${taskId} → ${runId}`);
      } catch (err) {
        toast("归组写入失败：" + err.message, "err");
      }
    });
    const setFollowUi = (on) => {
      const el = document.getElementById("live");
      el.setAttribute("aria-pressed", on);
      el.querySelector(".txt").textContent = on ? "跟随尾部" : "已暂停跟随";
    };
    document.getElementById("live").addEventListener("click", () => {
      follow = !follow;
      setFollowUi(follow);
      if (follow) scroller.scrollTop = scroller.scrollHeight;
    });
    document.getElementById("copySidBtn").addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      try {
        await navigator.clipboard.writeText(current.id);
        toast("已复制 session id");
      } catch {
        toast("复制失败", "err");
      }
    });
    document.getElementById("turnsBtn").addEventListener("click", () => {
      const turns = collapsibleTurns();
      const all = turns.length > 0 && turns.every(turn => collapsedTurns.has(turn));
      collapsedTurns = all ? new Set() : new Set(turns);
      paint();
    });
    document.getElementById("callsBtn").addEventListener("click", () => {
      const ids = collapsibleAssistants();
      const all = ids.length > 0 && ids.every(id => collapsedAssistants.has(id));
      collapsedAssistants = all ? new Set() : new Set(ids);
      paint();
    });
    const syncFilterChips = () => {
      document.getElementById("failChip").setAttribute("aria-pressed", String(tableFilter === "failed"));
      document.getElementById("toolChip").setAttribute("aria-pressed", String(tableFilter === "tools"));
    };
    document.getElementById("failChip").addEventListener("click", () => {
      tableFilter = tableFilter === "failed" ? "" : "failed";
      syncFilterChips();
      paint();
    });
    document.getElementById("toolChip").addEventListener("click", () => {
      tableFilter = tableFilter === "tools" ? "" : "tools";
      syncFilterChips();
      paint();
    });
    document.getElementById("statBadge").addEventListener("click", () => toggleToolStats());
    document.getElementById("statClose").addEventListener("click", () => toggleToolStats());
    document.getElementById("statsPanel").addEventListener("click", async (event) => {
      const more = event.target.closest(".more");
      if (more) {
        toolStats.shown[more.dataset.tool] = (toolStats.shown[more.dataset.tool] || TDRILL_BATCH) + TDRILL_BATCH;
        renderToolStats();
        return;
      }
      const head = event.target.closest(".drow");
      if (head) {
        toolStats.expanded = toolStats.expanded === head.dataset.tool ? "" : head.dataset.tool;
        renderToolStats();
        return;
      }
      const call = event.target.closest(".crow");
      if (call) await jumpToSeq(call.dataset.seq);
    });
    let lastScrollTop = 0;
    let suppressOlder = false;
    scroller.addEventListener("scroll", () => {
      const top = scroller.scrollTop;
      if (top < scroller.scrollHeight - scroller.clientHeight - 24) {
        follow = false;
        setFollowUi(false);
      }
      if (!suppressOlder && top <= LOAD_NEAR_TOP && lastScrollTop > LOAD_NEAR_TOP) loadOlder();
      lastScrollTop = top;
      paintTable();
    });
    scroller.addEventListener("click", (event) => {
      if (event.target === scroller || event.target.tagName === "TABLE") {
        selected = null;
        paint();
      }
    });
    // 会话上下文抽屉：摘要条切换展开/折叠。
    document.getElementById("ctxBar").addEventListener("click", () => { ctxOpen = !ctxOpen; paint(); });
    // 右缘把手：折叠/展开详情栏，状态跨会话记忆。
    document.getElementById("detailsHandle").addEventListener("click", () => {
      detailsCollapsed = !detailsCollapsed;
      try { localStorage.setItem("ata.detailsCollapsed", String(detailsCollapsed)); } catch {}
      paint();
    });
    document.getElementById("themeBtn").addEventListener("click", () => {
      const dark = document.documentElement.classList.toggle("dark");
      // 图标已 sprite 化：切 use href 而不是文本字形
      document.querySelector("#themeBtn use").setAttribute("href", dark ? "#i-sun" : "#i-moon");
    });

    // 返回标注板：只在从标注板进入的会话页出现
    document.getElementById("boardBackBtn").addEventListener("click", () => {
      boardReturn = false;
      openBoard();
    });

    // 会话改名：POST /api/sessions/{id}/title，服务端组 renamed 事件入账本。
    document.getElementById("renameBtn").addEventListener("click", () => {
      if (!current.id) return;
      const next = window.prompt("重命名会话", current.title || "");
      if (next == null) return;
      const title = next.trim();
      if (!title || title === current.title) return;
      fetch(`${API}/api/sessions/${encodeURIComponent(current.id)}/title`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title })
      }).then(async res => {
        if (!res.ok) throw new Error((await res.json()).error || res.status);
        toast("已重命名");
        current.title = title;
        current.crumb = `${current.agent} · <b>${esc(title)}</b>`;
        document.getElementById("crumb").innerHTML = current.crumb;
        const own = sessions.find(s => s.id === current.id);
        if (own) { own.title = title; paintSessions(); }
      }).catch(err => toast("重命名失败：" + err.message, "err"));
    });

    const clampDetailsWidth = (width, splitWidth) =>
      Math.min(Math.max(width, DETAILS_MIN), Math.min(DETAILS_MAX, splitWidth - TABLE_MIN));
    let resizeDrag = null;
    resize.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      const splitWidth = details.parentElement.getBoundingClientRect().width;
      resizeDrag = { pointerId: event.pointerId, startX: event.clientX, startWidth: details.getBoundingClientRect().width, splitWidth };
      resize.setPointerCapture(event.pointerId);
      event.preventDefault();
    });
    resize.addEventListener("pointermove", (event) => {
      if (!resizeDrag || resizeDrag.pointerId !== event.pointerId) return;
      detailsWidth = clampDetailsWidth(resizeDrag.startWidth + resizeDrag.startX - event.clientX, resizeDrag.splitWidth);
      details.style.width = `${detailsWidth}px`;
    });
    resize.addEventListener("pointerup", (event) => {
      if (resizeDrag?.pointerId !== event.pointerId) return;
      resizeDrag = null;
      try { localStorage.setItem("ata.detailsWidth", String(detailsWidth)); } catch {}
    });
    resize.addEventListener("dblclick", () => {
      detailsWidth = null; details.style.width = "";
      try { localStorage.removeItem("ata.detailsWidth"); } catch {}
    });
    resize.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      const splitWidth = details.parentElement.getBoundingClientRect().width;
      const currentWidth = details.getBoundingClientRect().width;
      const next = clampDetailsWidth(currentWidth + (event.key === "ArrowLeft" ? DETAILS_STEP : -DETAILS_STEP), splitWidth);
      detailsWidth = next;
      details.style.width = `${next}px`;
      try { localStorage.setItem("ata.detailsWidth", String(next)); } catch {}
      event.preventDefault();
    });

    // ── 数据落地与分区重绘 ──
    // applySessionPage 把一页投影结果 upsert 进 current（投影层是「同 id 新版本」
    // 语义：流式增长的 assistant 文本、pending→completed 的工具行都以新 _seq 重现），
    // 未变的行保留原对象身份，据此判断哪些分区真正需要重绘。
    function applySessionPage(page) {
      const report = { rowsChanged: false };
      // 行合并：id 相同且关键字段全等 → 保留旧对象（对象身份即变更标记）；
      // 同 id 内容变或新 id → 换新对象并标 dirty。
      const oldById = new Map(current.rows.map(r => [r.id, r]));
      const merged = [];
      for (const row of page.rows) {
        const prev = oldById.get(row.id);
        if (prev && sameRow(prev, row)) { merged.push(prev); continue; }
        merged.push(row);
        report.rowsChanged = true;
        if (selected && selected.type === "record" && selected.id === row.id) report.selectedRowChanged = true;
      }
      // keptOlder 行：tail 页窗口外的历史行继续保留（loadOlder 攒下的）
      const tailIds = new Set(page.rows.map(r => r.id));
      for (const row of current.rows) {
        if (row._keptOlder && !tailIds.has(row.id)) { row.index = -1; merged.unshift(row); }
      }
      merged.sort((a, b) => a._seq - b._seq);
      merged.forEach((row, i) => { row.index = i; });
      current.rows = merged;
      // meta 合并：title/cursor/scores 等变了才标 dirty（驱动 paintScore 这类轻量重绘）
      for (const k of ["title", "crumb", "older", "cursor", "turns", "scores", "toolsIndex"]) {
        if (!sameValue(current[k], page[k])) report.metaChanged = true;
        current[k] = page[k];
      }
      sessionRev = page.rev || sessionRev;
      return report;
    }
    // 行级相等比较：整行结构比对（投影后处理如 turn remap / model 回填会改老行而不改
    // _first），只剔除随页窗口变的 index。两侧都出自服务端同一序列化器，键序一致。
    const sameRow = (a, b) => {
      const { index: _a, ...ra } = a;
      const { index: _b, ...rb } = b;
      return JSON.stringify(ra) === JSON.stringify(rb);
    };
    const sameValue = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

    // 单会话尾部增量刷新：轮询与手动刷新按钮共用。force 供按钮绕过 rev 门控与
    // follow 开关（重置基线）；只更新数据不动视口，跳尾是 follow 开关自己的职责。
    async function refreshTail(force = false) {
      const sid = current.id;
      if (!sid || loadingOlder) return;
      if (!force && !follow) return;
      if (force) paintSkeleton();
      let page;
      try {
        page = force ? await loadSession(sid) : await loadSessionIfChanged(sid, sessionRev);
      } catch { pollErrorStreak += 1; return; } // 失败退避由轮询链处理，这里不堆积重试
      if (sid !== current.id) return; // epoch 守卫：await 期间已换会话
      if (!page) return; // unchanged：零请求投影、零重绘
      const report = applySessionPage(page);
      if (report.rowsChanged || force) paint();
      else if (report.metaChanged) paintScore();
      if (report.rowsChanged) {
        if (toolStats.open) refreshToolStats(sid);
        if (usageState.open) refreshUsage(sid);
      }
    }
    // 骨架行只替换 tbody 内容，行数取虚拟窗口近似；不碰 current/selected/scroller.scrollTop。
    function paintSkeleton() {
      const n = Math.max(6, Math.min(14, Math.ceil(scroller.clientHeight / CONTENT_ROW_HEIGHT)));
      const skels = Array.from({ length: n }, () =>
        `<tr class="skel-row"><td class="idx"><div class="skel" style="width:52px"></div></td>` +
        `<td class="evt"><div class="skel" style="width:64px"></div></td>` +
        `<td><div class="skel" style="width:${60 + Math.random() * 30}%"></div></td></tr>`).join("");
      tbody.innerHTML = skels;
    }
    document.getElementById("refreshBtn").addEventListener("click", async () => {
      await refreshTail(true);
      toast("已刷新到最新事件");
    });

    // ── 自调度轮询链（替代 setInterval）──
    // setTimeout 链天然防重叠：上一拍没回来下一拍不会发；失败退避；后台标签暂停。
    const POLL_INTERVAL_MS = 1000;
    const POLL_BACKOFF_MS = 5000;
    let pollErrorStreak = 0;
    function scheduleNextPoll(ms = pollErrorStreak ? POLL_BACKOFF_MS : POLL_INTERVAL_MS) {
      setTimeout(pollTick, ms);
    }
    async function pollTick() {
      if (document.hidden || !follow || !current.id || loadingOlder || pollInFlight) {
        scheduleNextPoll();
        return;
      }
      pollInFlight = true;
      try {
        await refreshTail(false);
        pollErrorStreak = 0;
      } catch {
        pollErrorStreak += 1;
      } finally {
        pollInFlight = false;
      }
      // 数据真变了才需要跳尾；unchanged 拍直接回原位无害
      if (follow) scroller.scrollTop = scroller.scrollHeight;
      scheduleNextPoll();
    }

    // 页面回到前台立刻补一拍，不等退避计时器走完
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && current.id) pollTick();
    });

    // ── 会话列表轮询（5s）──
    // 指纹门控：列表没变就一个字节都不画，侧栏 hover/滚动不再被周期性打断。
    const SIDEBAR_POLL_MS = 5000;
    function sidebarPrint(list) {
      return list.map(s => `${s.id}|${s.title}|${s.turns}|${s.first_ts}|${s.event_count}|${s.error_count}`).join("\n");
    }
    function adoptSidebarItem(item) {
      return {
        id: item.id,
        agent: item.agent,
        title: item.title,
        crumb: `${item.agent} · <b>${item.title}</b>`,
        rows: [],
        older: false,
        cursor: 0,
        turns: item.turns,
        firstTs: item.first_ts,
        eventCount: item.event_count,
        errorCount: item.error_count,
        toolsIndex: {}
      };
    }
    async function pollSessions() {
      try {
        if (!document.hidden) {
          const sid = current.id;
          const list = await fetchJSON("/api/sessions");
          if (sid !== current.id) return scheduleSidebar(); // epoch 守卫
          const print = sidebarPrint(list);
          if (print !== sidebarFingerprint) {
            sidebarFingerprint = print;
            const have = new Map(sessions.map(s => [s.id, s]));
            // 既有卡片只同步列表级字段（标题/计数会被改名、标注、新事件更新），
            // 不动它已加载的 rows 等会话页数据
            const next = list.map(item => have.get(item.id)
              ? Object.assign(have.get(item.id), {
                  title: item.title,
                  turns: item.turns,
                  firstTs: item.first_ts,
                  eventCount: item.event_count,
                  errorCount: item.error_count
                })
              : adoptSidebarItem(item));
            sessions.splice(0, sessions.length, ...next);
            paintTabs();
            paintSessions();
            if (current.id) paintScore();
          }
        }
      } catch { /* 服务不可达：下轮再试 */ }
      scheduleSidebar();
    }
    function scheduleSidebar() { setTimeout(pollSessions, SIDEBAR_POLL_MS); }
    pollSessions();
    scheduleNextPoll();

    boot();
