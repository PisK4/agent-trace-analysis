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
        toolsIndex: {}
      }));
      paintTabs();
      paintSessions();
      showHome();
    }
    function paintScore() {
      const box = document.getElementById("scoreBox");
      const assignBox = document.getElementById("assignBox");
      if (!current.id) { box.hidden = true; assignBox.hidden = true; return; }
      box.hidden = false;
      assignBox.hidden = false;
      ensureRunsLoaded();
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

    function paint() {
      suppressOlder = true;
      paintOverview();
      paintTable();
      paintScore();
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
      document.getElementById("q").value = "";
      document.getElementById("crumb").innerHTML = next.crumb;
      const sidBox = document.getElementById("sidBox");
      sidBox.textContent = next.id;
      sidBox.hidden = false;
      document.getElementById("copySidBtn").hidden = false;
      app.dataset.home = "";
      paintSessions();
      paint();
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
    document.getElementById("close").addEventListener("click", () => { app.dataset.inspect = ""; selected = null; });
    document.getElementById("assignBtn").addEventListener("click", async () => {
      if (!current.id) return;
      const runId = document.getElementById("assignRun").value;
      const taskId = document.getElementById("assignTask").value.trim();
      if (!runId || !taskId) { window.alert("先选 run 并填任务 id（ata tasks list 可查）"); return; }
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
        window.alert(`已归组：${taskId} → ${runId}`);
      } catch (err) {
        window.alert("归组写入失败：" + err.message);
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
    document.getElementById("durBtn").addEventListener("click", (e) => {
      actualDuration = !actualDuration;
      e.currentTarget.setAttribute("aria-pressed", actualDuration);
      e.currentTarget.title = actualDuration ? "Use equal-width operations" : "Use actual duration";
      range = null;
      viewport = null;
      paint();
    });
    document.querySelectorAll("#modeSeg [data-mode]").forEach((btn) => btn.addEventListener("click", () => {
      if ((actualTime ? "time" : "sequence") === btn.dataset.mode) return;
      actualTime = btn.dataset.mode === "time";
      range = null;
      viewport = null;
      paint();
    }));
    document.getElementById("copySidBtn").addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      try {
        await navigator.clipboard.writeText(current.id);
        btn.textContent = "✓";
      } catch {
        btn.textContent = "✕";
      }
      setTimeout(() => { btn.textContent = "⧉"; }, 900);
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
        app.dataset.inspect = "";
      }
    });
    document.getElementById("themeBtn").addEventListener("click", () => {
      const dark = document.documentElement.classList.toggle("dark");
      document.getElementById("themeBtn").textContent = dark ? "☀" : "☾";
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
    });
    resize.addEventListener("dblclick", () => { detailsWidth = null; details.style.width = ""; });
    resize.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      const splitWidth = details.parentElement.getBoundingClientRect().width;
      const currentWidth = details.getBoundingClientRect().width;
      const next = clampDetailsWidth(currentWidth + (event.key === "ArrowLeft" ? DETAILS_STEP : -DETAILS_STEP), splitWidth);
      detailsWidth = next;
      details.style.width = `${next}px`;
      event.preventDefault();
    });

    setInterval(async () => {
      if (!follow || !current.id || loadingOlder) return;
      const page = await loadSession(current.id);
      const tailIds = new Set(page.rows.map(r => r.id));
      const kept = current.rows.filter(r => r._keptOlder && !tailIds.has(r.id));
      current.rows = [...kept, ...page.rows].map((row, i) => ({ ...row, index: i, _keptOlder: row._keptOlder && !tailIds.has(row.id) }));
      current.older = page.older;
      if (!current.cursor) current.cursor = page.cursor;
      paint();
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
        toolsIndex: {}
      });
      paintTabs();
      paintSessions();
    }, 5000);

    boot();
