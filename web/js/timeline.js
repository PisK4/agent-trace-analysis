// ata web · Timeline 总览绘制：span、选区、turn 分隔线、earlier 入口

    function paintOverview() {
      const m = model();
      document.querySelectorAll("#modeSeg [data-mode]").forEach((btn) =>
        btn.setAttribute("aria-pressed", (actualTime ? "time" : "sequence") === btn.dataset.mode));
      if (!m) return;
      const { domainStart, domainDuration, fullDuration } = domainState(m);
      const left = `${-((domainStart - m.start) / domainDuration) * 100}%`;
      const width = `${(fullDuration / domainDuration) * 100}%`;
      turnLinesEl.style.setProperty("--domain-left", left);
      turnLinesEl.style.setProperty("--domain-width", width);
      lanesEl.style.setProperty("--domain-left", left);
      lanesEl.style.setProperty("--domain-width", width);
      const sel = draft || range;
      const matches = searchTerms().length ? new Set(current.rows.filter(rowMatches).map(row => row.id)) : null;
      const equal = timelineMode() === "time";
      turnLinesEl.innerHTML = m.bounds.map(b =>
        `<span class="turn-line" style="--left:${((b.time - m.start) / fullDuration) * 100}%"></span>`
      ).join("");
      lanesEl.innerHTML = m.spans.map(span => {
        const spanLeft = ((span.start - m.start) / fullDuration) * 100;
        const spanWidth = ((span.end - span.start) / fullDuration) * 100;
        const inRange = !sel || (span.start <= sel.end && span.end >= sel.start);
        const search = !matches || matches.has(span.id);
        const ttft = span.ttftMs && span.durationMs ? `${(span.ttftMs / span.durationMs) * 100}%` : "";
        const currentSel = selected && selected.type === "record" && span.id === selected.id;
        return `<span class="span ${span.kind}"
          data-id="${span.id}" data-current="${currentSel}" data-in-range="${inRange}"
          data-search="${search}" data-error="${span.error === true}" data-equal="${equal}"
          ${ttft ? `data-ttft="true"` : ""}
          style="--lane:${span.lane};--left:${spanLeft}%;--width:${spanWidth}%;--gap:min(${Math.max(spanWidth, 0.01) * 0.08}%,1px);${ttft ? `--ttft:${ttft};` : ""}"></span>`;
      }).join("");
      if (sel) {
        const s = clamp(Math.min(sel.start, sel.end), m.start, m.end);
        const e = clamp(Math.max(sel.start, sel.end), m.start, m.end);
        const selLeft = ((s - domainStart) / domainDuration) * 100;
        const selWidth = ((e - s) / domainDuration) * 100;
        selFill.hidden = false; selEdge.hidden = false;
        selFill.dataset.draft = draft ? "true" : "false";
        selEdge.dataset.draft = draft ? "true" : "false";
        [selFill, selEdge].forEach(el => {
          el.style.setProperty("--sel-left", `${selLeft}%`);
          el.style.setProperty("--sel-width", `${Math.max(selWidth, 0.15)}%`);
        });
      } else {
        selFill.hidden = true; selEdge.hidden = true;
      }
      const atStart = !viewport || domainStart === m.start;
      earlierBtn.hidden = !(current.older && atStart);
      earlierBtn.disabled = loadingOlder;
    }
