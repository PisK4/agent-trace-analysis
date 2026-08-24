// ata web · Ledger 表格：虚拟滚动渲染、行/请求绑定、折叠汇总行

    function virtualRows(records) {
      const force = current.older === true;
      if (records.length <= VIRTUAL_THRESHOLD && !force) {
        return { virtual: false, rows: records, top: 0, bottom: 0, total: records.length * CONTENT_ROW_HEIGHT };
      }
      const items = records.map(row => ({
        row,
        height: row.virtual === "summary" ? COLLAPSED_SUMMARY_HEIGHT : CONTENT_ROW_HEIGHT
      }));
      const olderH = current.older ? CONTENT_ROW_HEIGHT : 0;
      let offset = olderH;
      const offsets = items.map(item => {
        const start = offset;
        offset += item.height;
        return { ...item, start, end: offset };
      });
      const viewH = scroller.clientHeight || 600;
      const top = scroller.scrollTop;
      let first = offsets.findIndex(item => item.end >= top);
      if (first < 0) first = 0;
      let last = offsets.findIndex(item => item.start > top + viewH);
      if (last < 0) last = offsets.length;
      first = Math.max(0, first - OVERSCAN);
      last = Math.min(offsets.length, last + OVERSCAN);
      const shown = offsets.slice(first, last);
      const topSpacer = Math.max(0, (shown[0]?.start || olderH) - olderH);
      const lastEnd = shown.length ? shown[shown.length - 1].end : olderH;
      return {
        virtual: true,
        rows: shown.map(item => item.row),
        top: topSpacer,
        bottom: Math.max(0, offset - lastEnd),
        total: offset
      };
    }

    function paintTable() {
      const records = displayRecords();
      const focus = focusSet();
      const pack = virtualRows(records);
      const parts = [];
      if (current.older) {
        parts.push(`<tr class="older" data-kind="older"><td class="idx"></td><td colspan="2"><button class="ghost" id="loadOlder" ${loadingOlder ? "disabled" : ""}>${loadingOlder ? "Loading…" : "Load earlier history"}</button></td></tr>`);
      }
      if (pack.virtual && pack.top) parts.push(`<tr class="spacer"><td colspan="3" style="--h:${pack.top}px;height:${pack.top}px"></td></tr>`);
      for (const row of pack.rows) {
        if (row.kind === "summary") {
          parts.push(`<tr class="summary" data-kind="summary" data-expand-turn="${row.expandTurn || ""}" data-expand-assistant="${row.expandAssistant || ""}">
            <td class="idx"></td><td class="evt"></td><td>${esc(row.text)}</td></tr>`);
          continue;
        }
        const out = focus && !focus.has(row.id);
        const selectedRow = selected.type === "record" && selected.id === row.id;
        const idx = String(row.index + 1).padStart(2, "0");
        const reqActive = selected.type === "request" && selected.id === row.id;
        const req = row.requestNo
          ? `<button class="req-dot" data-req="${row.id}" data-error="${row.status === "failed" || row.status === "cancelled"}" data-active="${reqActive}" title="Request #${row.requestNo}"><span>Request #${row.requestNo}</span></button>`
          : "";
        const turn = row.start && row.turn && row.kind !== "context"
          ? `<span class="turn-chip">${row.turn < 0 ? "T…" : `T${row.turn}`}</span>`
          : "";
        const content = rowContent(row);
        // assistant 行尾挂 usage 迷你条（sub2API 式）：只有真实上报（reported/estimated）
        // 才渲染；missing 行全是破折号，是噪音。明细悬停经全局 #tip 展开。
        const hasUsage = row.usage && (row.usage.status === "reported" || row.usage.status === "estimated");
        const usageHtml = row.kind === "assistant" && hasUsage ? usageStrip(row.usage, true) : "";
        // turn 色条按起始行 kind 推导（user→green / assistant→紫 / tool→orange），
        // 不再手写 turn 类，避免漏配退回灰条
        const turnClass = row.start ? ` turnc-${row.kind}` : "";
        parts.push(`<tr data-id="${row.id}" data-selected="${selectedRow}" data-focus="${out ? "out" : "in"}" data-error="${row.status === "failed" || row.status === "cancelled"}" data-pending="${row.status === "pending"}" ${row.start ? 'data-turn-start="true"' : ""} class="${row.kind === "subtool" ? "subtool" : ""}${turnClass}">
          <td class="idx">${idx}${turn}</td>
          <td class="evt">${req}<span class="kind ${row.kind}">${esc(row.tag)}</span></td>
          <td class="content ${row.kind === "tool" || row.kind === "subtool" ? "mono" : ""}">${esc(content)}${usageHtml}</td>
        </tr>`);
      }
      if (pack.virtual && pack.bottom) parts.push(`<tr class="spacer"><td colspan="3" style="--h:${pack.bottom}px;height:${pack.bottom}px"></td></tr>`);
      tbody.innerHTML = parts.join("");
      tbody.querySelectorAll("tr[data-id]").forEach(tr => {
        tr.addEventListener("click", () => selectRecord(tr.dataset.id, { fromTable: true }));
        tr.addEventListener("dblclick", (event) => {
          const row = byId(tr.dataset.id);
          if (!row) return;
          event.preventDefault();
          if (row.kind === "assistant" && collapsibleAssistants().includes(row.id)) toggleAssistant(row.id);
          else if (row.start && collapsibleTurns().includes(row.turn)) toggleTurn(row.turn);
        });
      });
      tbody.querySelectorAll("tr.summary").forEach(tr => {
        tr.addEventListener("click", () => {
          if (tr.dataset.expandTurn) { collapsedTurns.delete(Number(tr.dataset.expandTurn)); paint(); }
          if (tr.dataset.expandAssistant) { collapsedAssistants.delete(tr.dataset.expandAssistant); paint(); }
        });
      });
      tbody.querySelectorAll("[data-req]").forEach(btn => {
        btn.addEventListener("click", (event) => {
          event.stopPropagation();
          selectRequest(btn.dataset.req);
        });
      });
      const loadBtn = document.getElementById("loadOlder");
      if (loadBtn) loadBtn.addEventListener("click", () => loadOlder());
      paintFoldButtons();
    }

    // 行内 usage 迷你条的悬停明细：走全局 #tip（fixed 定位），不被 .table-wrap 的 overflow 裁剪。
    // 事件委托挂在 tbody 上，重绘不丢；离开迷你条即收起，不影响 timeline 自己的 tip 用法。
    tbody.addEventListener("mousemove", (event) => {
      const strip = event.target.closest?.(".row-usage");
      if (!strip) {
        if (tip.dataset.usage === "true") { tip.dataset.on = "false"; tip.dataset.usage = "false"; }
        return;
      }
      const row = byId(strip.closest("tr")?.dataset.id);
      if (!row || !row.usage) return;
      tip.innerHTML = usageCells(row.usage);
      tip.dataset.usage = "true";
      tip.dataset.on = "true";
      tip.style.left = Math.min(window.innerWidth - 300, event.clientX + 14) + "px";
      tip.style.top = Math.min(window.innerHeight - 230, event.clientY + 16) + "px";
    });
    tbody.addEventListener("mouseleave", () => {
      if (tip.dataset.usage === "true") { tip.dataset.on = "false"; tip.dataset.usage = "false"; }
    });

    function paintFoldButtons() {
      const turns = collapsibleTurns();
      const calls = collapsibleAssistants();
      const allTurns = turns.length > 0 && turns.every(turn => collapsedTurns.has(turn));
      const allCalls = calls.length > 0 && calls.every(id => collapsedAssistants.has(id));
      const turnsBtn = document.getElementById("turnsBtn");
      const callsBtn = document.getElementById("callsBtn");
      turnsBtn.setAttribute("aria-pressed", allTurns);
      callsBtn.setAttribute("aria-pressed", allCalls);
      turnsBtn.title = allTurns ? "Expand turns" : "Collapse turns";
      callsBtn.title = allCalls ? "Expand calls" : "Collapse calls";
      // 图标 sprite 化后折叠/展开切 use href
      const setFold = (btn, expanded) =>
        btn.querySelector("use").setAttribute("href", expanded ? "#i-unfold" : "#i-fold");
      setFold(turnsBtn, allTurns);
      setFold(callsBtn, allCalls);
    }
