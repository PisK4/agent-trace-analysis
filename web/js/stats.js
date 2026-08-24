// ata web · 会话级统计面板：工具调用统计（徽章+排序表+时间序钻取+跳转）与逐轮 usage 趋势

    const TDRILL_BATCH = 5;         // 钻取列表初始渲染与每次追加条数
    let toolStats = { open: false, data: null, expanded: "", shown: {} };
    let sessionUsageData = null;

    function resetSessionPanels() {
      toolStats = { open: false, data: null, expanded: "", shown: {} };
      sessionUsageData = null;
      paintToolStatsBar();
      document.getElementById("statsPanel").hidden = true;
      document.getElementById("statBadge").setAttribute("aria-expanded", "false");
      const up = document.getElementById("usagePanel");
      up.hidden = true;
      document.getElementById("usageBtn").setAttribute("aria-pressed", "false");
    }

    // 常驻徽章：统计模块唯一入口，failed 非零时红字永远在场。
    function paintToolStatsBar() {
      document.getElementById("statBadge").hidden = !current.id;
      const s = toolStats.data && toolStats.data.summary;
      const el = document.getElementById("badgeText");
      if (!s) { el.innerHTML = ""; return; }
      el.innerHTML = `<b>${s.calls} calls</b>` +
        (s.failed ? `<span class="fbadge">· ${s.failed} failed</span>` : "");
    }

    async function toggleToolStats() {
      const panel = document.getElementById("statsPanel");
      toolStats.open = panel.hidden;
      panel.hidden = !toolStats.open;
      document.getElementById("statBadge").setAttribute("aria-expanded", String(toolStats.open));
      if (toolStats.open) await refreshToolStats();
    }

    async function refreshToolStats() {
      // 徽章数字要常驻，打开会话就拉一次；面板未开时秒级轮询不重复拉。
      if (!current.id) return;
      try {
        toolStats.data = await fetchJSON("/api/sessions/" + encodeURIComponent(current.id) + "/tool-stats");
      } catch { toolStats.data = null; }
      renderToolStats();
      paintToolStatsBar();
    }

    const sqClass = (status) => status === "completed" ? "ok"
      : status === "failed" ? "fail" : status === "pending" ? "wait" : "other";

    function renderToolStats() {
      const data = toolStats.data;
      const sum = data && data.summary;
      document.getElementById("statSum").textContent =
        sum ? `${sum.calls} calls · ${sum.failed} failed · ${sum.tools} tools` : "";
      const urate = document.getElementById("urate");
      if (!sum) { urate.hidden = true; }
      else if (sum.mounted) {
        urate.hidden = false;
        urate.title = "分母来自 SYSTEM 行的工具目录";
        urate.innerHTML = `<span class="u-seg">挂载 <b>${sum.mounted}</b></span>` +
          `<span class="u-seg">已用 <b>${sum.tools}</b></span>` +
          `<span class="u-seg rate">使用率 <b>${sum.usage_rate}%</b></span>`;
      } else {
        // 目录缺失的宿主（Claude / Droid 等）：使用率 n/a，不硬算。
        urate.hidden = false;
        urate.title = "本会话没有工具目录记录，无法计算使用率";
        urate.innerHTML = `<span class="u-seg">已用 <b>${sum.tools}</b></span>` +
          `<span class="u-seg rate">使用率 <b>n/a</b></span>`;
      }
      const box = document.getElementById("distRows");
      if (!data || !data.tools.length) {
        box.innerHTML = `<p class="miss" style="padding:10px 14px">No tool calls in this session.</p>`;
        return;
      }
      // 排序：失败数降序 → 调用数降序；红色数字自己完成分区。
      const sorted = [...data.tools].sort((a, b) => (b.failed - a.failed) || (b.total - a.total));
      box.innerHTML = sorted.map(tool => {
        const open = toolStats.expanded === tool.name;
        const shown = toolStats.shown[tool.name] || TDRILL_BATCH;
        const drill = !open ? "" :
          // calls 按 started_at 升序（后端口径），钻取即时间顺序。
          tool.calls.slice(0, shown).map(c => `
            <button class="crow" type="button" data-seq="${c.seq}">
              <i class="dot ${sqClass(c.status)}"></i>
              <span class="ct">${clock(c.ts)}</span>
              <span class="cd">${c.duration_ms != null ? durLabel(c.duration_ms) : "—"}</span>
              <span class="cx">${esc(compactPreview(c.text)) || '<span class="dim">(no input preview)</span>'}</span>
            </button>`).join("") +
          (tool.calls.length > shown
            ? `<button class="more" type="button" data-tool="${esc(tool.name)}">show more (${tool.calls.length - shown} left)</button>`
            : "");
        return `<div class="drow-wrap">
          <button class="drow" type="button" data-tool="${esc(tool.name)}" aria-expanded="${open}">
            <span class="dname" title="${esc(tool.name)}">${esc(tool.name)}</span>
            <span class="dnum">${tool.total}</span>
            <span class="dnum ${tool.failed ? "bad" : "mute"}">${tool.failed || ""}</span>
          </button>
          <div class="drill" ${open ? "" : "hidden"}>${drill}</div>
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
