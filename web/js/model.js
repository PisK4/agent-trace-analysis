// ata web · 数据模型：行折叠投影 displayRecords、时间轴几何 model/domainState、焦点集、虚拟滚动窗口

    let tableFilter = ""; // "" | "failed" | "tools"，Ledger 区过滤 chips

    function filteredRows() {
      if (tableFilter === "failed") return current.rows.filter(row => row.status === "failed");
      if (tableFilter === "tools") return current.rows.filter(row => row.kind === "tool" || row.kind === "subtool");
      return current.rows;
    }

    function displayRecords() {
      const base = filteredRows();
      const terms = searchTerms();
      if (terms.length) return base.filter(rowMatches).map(row => ({ ...row, virtual: "content" }));
      const turnSet = collapsedTurns;
      const out = [];
      const byTurn = new Map();
      for (const row of base) {
        if (row.turn == null) continue;
        const list = byTurn.get(row.turn) || [];
        list.push(row);
        byTurn.set(row.turn, list);
      }
      for (const row of base) {
        if (row.turn == null || !turnSet.has(row.turn) || row.kind === "system") {
          out.push({ ...row, virtual: "content" });
          continue;
        }
        const content = (byTurn.get(row.turn) || []).filter(item => item.kind !== "system");
        if (content.length <= 1 || row.id !== content[0].id) continue;
        out.push({ ...row, virtual: "content" });
        const rest = content.slice(1);
        const steps = new Set(rest.map(item => item.group).filter(group => group && group.startsWith("Step "))).size;
        const tools = rest.filter(item => item.kind === "tool" || item.kind === "subtool").length;
        out.push({
          id: `${row.id}__turn`,
          index: row.index,
          turn: row.turn,
          kind: "summary",
          tag: "SUMMARY",
          virtual: "summary",
          summaryKind: "turn",
          text: `${steps} ${steps === 1 ? "step" : "steps"} · ${tools} tool ${tools === 1 ? "call" : "calls"}`,
          expandTurn: row.turn
        });
      }
      const folded = [];
      for (let i = 0; i < out.length; i++) {
        const row = out[i];
        folded.push(row);
        if (row.kind !== "assistant" || !collapsedAssistants.has(row.id)) continue;
        const calls = [];
        for (let j = i + 1; j < out.length; j++) {
          if (out[j].kind !== "tool" && out[j].kind !== "subtool") break;
          calls.push(out[j]);
        }
        if (!calls.length) continue;
        const names = [...new Set(calls.map(item => item.name).filter(Boolean))];
        folded.push({
          id: `${row.id}__calls`,
          index: row.index,
          turn: row.turn,
          kind: "summary",
          tag: "SUMMARY",
          virtual: "summary",
          summaryKind: "assistant",
          text: `${calls.length} tool ${calls.length === 1 ? "call" : "calls"}${names.length ? ` · ${names.join(", ")}` : ""}`,
          expandAssistant: row.id
        });
        i += calls.length;
      }
      return folded;
    }

    function model() {
      const rows = current.rows.filter(row => row.kind !== "summary");
      const mode = timelineMode();
      if (mode === "sequence") {
        const spans = rows.map((row, i) => ({
          id: row.id, kind: row.kind, lane: laneOf(row.kind), start: i, end: i + 1,
          startedAt: row.startedAt, durationMs: row.durationMs, ttftMs: row.ttftMs,
          error: row.status === "failed"
        }));
        const bounds = [];
        rows.forEach((row, i) => { if (row.start && row.turn) bounds.push({ turn: row.turn, time: i }); });
        return { start: 0, end: Math.max(1, spans.length), spans, bounds };
      }
      const raw = rows.flatMap(row => {
        if (!Number.isFinite(row.startedAt)) return [];
        const durationMs = Math.max(0, row.durationMs || 0);
        return [{
          id: row.id, kind: row.kind, lane: laneOf(row.kind),
          start: row.startedAt, end: row.startedAt + durationMs,
          startedAt: row.startedAt, durationMs, ttftMs: row.ttftMs,
          error: row.status === "failed", turn: row.turn, turnStart: row.start
        }];
      });
      if (!raw.length) return null;
      const compressIdle = mode === "duration";
      const useWidth = mode === "actual" || mode === "duration";
      const removed = new Map();
      let idle = 0;
      let covered = null;
      for (const span of [...raw].sort((a, b) => a.start - b.start || a.end - b.end)) {
        if (compressIdle && covered != null && span.start > covered) idle += span.start - covered;
        removed.set(span.id, idle);
        covered = covered == null ? span.end : Math.max(covered, span.end);
      }
      const spans = raw.map(span => {
        const offset = removed.get(span.id) || 0;
        return {
          ...span,
          start: span.start - offset,
          end: (useWidth ? span.end : span.start) - offset
        };
      });
      const bounds = [];
      const seen = new Set();
      for (const span of spans) {
        if (!span.turnStart || !span.turn || seen.has(span.turn)) continue;
        seen.add(span.turn);
        const first = Math.min(...spans.filter(item => item.turn === span.turn).map(item => item.start));
        bounds.push({ turn: span.turn, time: first });
      }
      return {
        start: Math.min(...spans.map(s => s.start)),
        end: Math.max(...spans.map(s => s.end)),
        spans, bounds
      };
    }

    function domainState(m) {
      const fullDuration = Math.max(1, m.end - m.start);
      if (!viewport) return { domainStart: m.start, domainDuration: fullDuration, fullDuration };
      const viewportDuration = Math.min(fullDuration, Math.max(1, viewport.end - viewport.start));
      const domainStart = clamp(viewport.start, m.start, m.end - viewportDuration);
      return { domainStart, domainDuration: viewportDuration, fullDuration };
    }

    function focusSet() {
      const m = model();
      const sel = draft || range;
      if (!m || !sel) return null;
      return new Set(m.spans.filter(s => s.start <= sel.end && s.end >= sel.start).map(s => s.id));
    }
