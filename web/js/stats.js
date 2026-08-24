// ata web · 会话级统计面板：工具调用统计（条带+钻取+跳转）与逐轮 usage 趋势

    const TSTRIP_MAX = 40;          // 超过则压缩为比例条
    const TDRILL_BATCH = 5;         // 二级列表初始渲染与每次追加条数
    let toolStats = { open: false, data: null, expanded: "", shown: {} };
    let sessionUsageData = null;

    function resetSessionPanels() {
      toolStats = { open: false, data: null, expanded: "", shown: {} };
      sessionUsageData = null;
      document.getElementById("tstatBar").hidden = true;
      document.getElementById("tstatPanel").hidden = true;
      const up = document.getElementById("usagePanel");
      up.hidden = true;
      document.getElementById("usageBtn").setAttribute("aria-pressed", "false");
    }

    function paintToolStatsBar() {
      document.getElementById("tstatBar").hidden = !current.id;
      const s = toolStats.data && toolStats.data.summary;
      const el = document.getElementById("tstatSummary");
      if (!s) { el.textContent = ""; return; }
      el.innerHTML = `${s.tools} tools · ${s.calls} calls` +
        (s.failed ? ` · <b class="bad">${s.failed} failed</b>` : "");
    }

    async function toggleToolStats() {
      toolStats.open = !toolStats.open;
      document.getElementById("tstatPanel").hidden = !toolStats.open;
      document.getElementById("tstatToggle").setAttribute("aria-expanded", String(toolStats.open));
      if (toolStats.open) await refreshToolStats();
    }

    async function refreshToolStats() {
      if (!current.id || !toolStats.open) return;
      try {
        toolStats.data = await fetchJSON("/api/sessions/" + encodeURIComponent(current.id) + "/tool-stats");
      } catch { toolStats.data = null; }
      renderToolStats();
      paintToolStatsBar();
    }

    const sqClass = (status) => status === "completed" ? "ok" : status === "failed" ? "fail" : status === "pending" ? "wait" : "other";

    function stripHTML(calls) {
      if (calls.length <= TSTRIP_MAX) {
        return `<span class="sq-strip">` + calls.map(c =>
          `<i class="sq ${sqClass(c.status)}"></i>`).join("") + `</span>`;
      }
      // ponytail: 比例条只分四段纯色，不做逐格压缩；需要更细再改。
      const n = calls.length;
      const seg = (st) => {
        const k = calls.filter(c => sqClass(c.status) === st).length;
        return k ? `<i class="sqseg ${st}" style="--w:${(k / n * 100).toFixed(2)}%"></i>` : "";
      };
      return `<span class="ratio-strip">` +
        seg("ok") + seg("fail") + seg("wait") + seg("other") + `</span>`;
    }

    function renderToolStats() {
      const box = document.getElementById("tstatBody");
      const data = toolStats.data;
      if (!data || !data.tools.length) {
        box.innerHTML = `<p class="miss">No tool calls in this session.</p>`;
        return;
      }
      box.innerHTML = data.tools.map(tool => {
        const open = toolStats.expanded === tool.name;
        const shown = toolStats.shown[tool.name] || TDRILL_BATCH;
        const drill = !open ? "" :
          tool.calls.slice(0, shown).map(c => `
            <button class="tcall" type="button" data-seq="${c.seq}">
              <i class="dot ${sqClass(c.status)}"></i>
              <span class="tt">${clock(c.ts)}</span>
              <span class="td">${c.duration_ms != null ? durLabel(c.duration_ms) : "—"}</span>
              <span class="tx">${esc(compactPreview(c.text)) || '<span class="dim">(no input preview)</span>'}</span>
            </button>`).join("") +
          (tool.calls.length > shown
            ? `<button class="ghost tmore" type="button" data-tool="${esc(tool.name)}">show more (${tool.calls.length - shown} left)</button>`
            : "");
        return `<div class="trow-wrap">
          <button class="trow" type="button" data-tool="${esc(tool.name)}" aria-expanded="${open}">
            <span class="tname">${esc(tool.name)}</span>
            <span class="tstrip">${stripHTML(tool.calls)}</span>
            <span class="tnum">${tool.total}${tool.failed ? ` · <b class="bad">${tool.failed} failed</b>` : ""}</span>
          </button>
          <div class="tdrill">${drill}</div>
        </div>`;
      }).join("");
    }

    async function jumpToSeq(seq) {
      seq = Number(seq);
      let row = current.rows.find(r => r._seq === seq);
      if (!row) {
        // 目标在已加载窗口之外：拉包含它的那一页并并入当前视图。
        const page = await loadSession(current.id, `?before=${seq + 1}&limit=36`);
        const have = new Set(current.rows.map(r => r.id));
        const prepend = page.rows.filter(r => !have.has(r.id));
        if (!prepend.length) return;
        current.rows = [...prepend, ...current.rows].map((r, i) => ({ ...r, index: i }));
        if (page.cursor && (!current.cursor || page.cursor < current.cursor)) current.cursor = page.cursor;
        current.older = true;
        row = current.rows.find(r => r._seq === seq);
      }
      if (!row) return;
      selectRecord(row.id);
      // 点进来的动机几乎总是看细节：有 payload tab 就直接落到 payload。
      if (tabsOf(selected).includes("payload")) rememberTab("payload");
      paint();
    }

    async function toggleUsagePanel() {
      const panel = document.getElementById("usagePanel");
      const on = panel.hidden;
      panel.hidden = !on;
      document.getElementById("usageBtn").setAttribute("aria-pressed", String(on));
      if (on) await refreshSessionUsage();
    }

    async function refreshSessionUsage() {
      if (!current.id) { sessionUsageData = null; renderUsagePanel(); return; }
      try {
        sessionUsageData = await fetchJSON("/api/sessions/" + encodeURIComponent(current.id) + "/usage");
      } catch { sessionUsageData = null; }
      renderUsagePanel();
    }

    function renderUsagePanel() {
      const el = document.getElementById("usagePanel");
      if (el.hidden) return;
      const u = sessionUsageData;
      const turns = (u && u.turns) || [];
      if (!turns.length) {
        el.innerHTML = `<div class="meta-line"><span class="dim">No usage recorded.</span></div>`;
        return;
      }
      const max = Math.max(1, ...turns.map(t => Math.max(t.input || 0, t.output || 0)));
      const bars = turns.map(t => `
        <div class="urow">
          <span class="ut">T${t.turn}</span>
          <span class="ubars">
            <i class="ubar in" style="--w:${(((t.input || 0) / max) * 100).toFixed(1)}%" title="input ${fmtNum(t.input)}"></i>
            <i class="ubar out" style="--w:${(((t.output || 0) / max) * 100).toFixed(1)}%" title="output ${fmtNum(t.output)}"></i>
          </span>
          <span class="unum">↑${fmtNum(t.input) ?? "—"} ↓${fmtNum(t.output) ?? "—"}</span>
        </div>`).join("");
      const total = (u && u.total) || {};
      const miss = u.missing_turns;
      // 元信息条：agent 与轮次数来自会话权威字段；token 合计来自 /usage 全量投影，
      // 不用前端已加载窗口数数（那是分页窗口，会漏）。
      el.innerHTML = `
        <div class="meta-line">
          <span>${esc(AGENT_LABELS[current.agent] || current.agent)}</span>
          <span>${current.turns != null ? `${current.turns} turns` : `${turns.length} turns w/ usage`}</span>
          <span>tokens ↑${fmtNum(total.input) ?? "—"} / ↓${fmtNum(total.output) ?? "—"}</span>
          ${miss ? `<b class="bad" title="这些轮次没有可归因的 usage 计量">${miss} turns missing usage</b>` : ""}
          <span class="dim">cache 在本地中转语料常为空（已知盲区）</span>
        </div>${bars}`;
    }
