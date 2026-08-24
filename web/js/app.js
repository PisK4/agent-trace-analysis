// ata web · 应用编排：boot、paint 总入口、选择/翻页/轮询、控件与 resize 绑定

    async function boot() {
      const list = await fetchJSON("/api/sessions");
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
      // 打开会话时顺带把侧栏卡片的标注点/计数刷成最新（openSession 已合并 scores）
      paintSessions();
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
      const next = await loadSession(id);
      if (!next) return;
      const idx = sessions.findIndex(session => session.id === next.id);
      // 详情接口不返回 first_ts 等列表字段，合并保留，避免卡片时间变成 —
      if (idx >= 0) sessions[idx] = { ...sessions[idx], ...next }; else sessions.push(next);
      current = next;
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
      const prevHeight = scroller.scrollHeight;
      const prevTop = scroller.scrollTop;
      const page = await loadSession(current.id, `?before=${current.cursor}&limit=36`);
      const have = new Set(current.rows.map(r => r.id));
      const prepend = page.rows.filter(r => !have.has(r.id)).map(r => ({ ...r, _keptOlder: true }));
      current.rows = [...prepend, ...current.rows].map((row, i) => ({ ...row, index: i }));
      current.older = page.older;
      current.cursor = page.cursor;
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

    // 单会话尾部增量刷新：轮询与手动刷新按钮共用。force 供按钮绕过 follow 开关；
    // 只更新数据不动视口，跳尾是 follow 开关自己的职责。
    // 手动刷新先盖一层骨架行（只动 tbody 渲染层）：选中/滚动/数据都在，回填后原样恢复。
    let refreshSkeleton = false;
    async function refreshTail(force) {
      if (!current.id || loadingOlder) return;
      if (!force && !follow) return;
      if (force && !refreshSkeleton) {
        refreshSkeleton = true;
        paintSkeleton();
      }
      const page = await loadSession(current.id);
      const tailIds = new Set(page.rows.map(r => r.id));
      const kept = current.rows.filter(r => r._keptOlder && !tailIds.has(r.id));
      current.rows = [...kept, ...page.rows].map((row, i) => ({ ...row, index: i, _keptOlder: row._keptOlder && !tailIds.has(row.id) }));
      current.older = page.older;
      if (!current.cursor) current.cursor = page.cursor;
      refreshSkeleton = false;
      paint();
      if (toolStats.open) refreshToolStats();
      if (usageState.open) refreshUsage();
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

    setInterval(async () => {
      if (!follow || !current.id || loadingOlder) return;
      await refreshTail(false);
      if (follow) scroller.scrollTop = scroller.scrollHeight;
    }, 1000);

    // 新会话出现时刷新左侧列表（只新增，不打断当前画布）。
    setInterval(async () => {
      if (document.hidden) return;
      const list = await fetchJSON("/api/sessions");
      const have = new Set(sessions.map(s => s.id));
      const fresh = list.filter(s => !have.has(s.id));
      if (!fresh.length) return;
      // 服务端按最近活动倒序返回，新会话在列表前面：unshift 保持顶部。
      for (const item of fresh.reverse()) sessions.unshift({
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
      });
      paintTabs();
      paintSessions();
    }, 5000);

    boot();
