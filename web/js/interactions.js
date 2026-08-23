// ata web · Timeline 指针交互：拖拽选区、右键平移、滚轮缩放、边缘平移、悬停提示

    function fractionAt(event) {
      const rect = track.getBoundingClientRect();
      return clamp((event.clientX - rect.left) / Math.max(1, rect.width), 0, 1);
    }
    function spanIdAt(event) {
      const node = event.target.closest?.("[data-id]");
      return node ? node.dataset.id : null;
    }

    let drag = null;
    let pan = null;

    track.addEventListener("pointerdown", (event) => {
      const m = model();
      if (!m) return;
      const { domainStart, domainDuration } = domainState(m);
      if (event.button === 2) {
        pan = {
          pointerId: event.pointerId,
          anchorClientX: event.clientX,
          anchorStart: domainStart,
          moved: false,
          pannable: viewport != null
        };
        track.dataset.panning = viewport ? "true" : "false";
        track.setPointerCapture(event.pointerId);
        return;
      }
      if (event.button !== 0) return;
      const t = domainStart + fractionAt(event) * domainDuration;
      drag = { pointerId: event.pointerId, x: event.clientX, t, id: spanIdAt(event) };
      draft = { start: t, end: t };
      track.setPointerCapture(event.pointerId);
      paintOverview();
    });
    track.addEventListener("pointermove", (event) => {
      const m = model();
      if (!m) return;
      const frac = fractionAt(event);
      const id = spanIdAt(event);
      if (pan && pan.pointerId === event.pointerId) {
        if (Math.abs(event.clientX - pan.anchorClientX) >= MINIMUM_DRAG_PX) pan.moved = true;
        if (!pan.pannable) return;
        const { domainDuration, fullDuration } = domainState(m);
        const delta = (event.clientX - pan.anchorClientX) / Math.max(1, track.getBoundingClientRect().width);
        const nextStart = clamp(pan.anchorStart - delta * domainDuration, m.start, m.end - domainDuration);
        viewport = { start: nextStart, end: nextStart + domainDuration };
        if (domainDuration >= fullDuration * 0.999) viewport = null;
        paintOverview();
        return;
      }
      if (!drag) {
        hoverLine.hidden = id !== null;
        hoverLine.style.setProperty("--hover-left", `${frac * 100}%`);
        lanesEl.querySelectorAll(".span").forEach(el => { el.dataset.hovered = el.dataset.id === id; });
        window.clearTimeout(tipTimer);
        if (id == null) { tip.dataset.on = "false"; return; }
        tipTimer = window.setTimeout(() => {
          const row = byId(id);
          const node = lanesEl.querySelector(`.span[data-id="${id}"]`);
          if (!row || !node) return;
          const box = node.getBoundingClientRect();
          const lines = [kindLabel(row.kind)];
          if (Number.isFinite(row.startedAt) && row.durationMs) {
            lines.push(`${clock(row.startedAt)} → ${clock(row.startedAt + row.durationMs)}`);
          } else if (Number.isFinite(row.startedAt)) {
            lines.push(`Started ${clock(row.startedAt)}`);
          }
          const bits = [];
          if (row.durationMs) bits.push(`Total ${commaMs(row.durationMs)}`);
          if (row.ttftMs != null && row.decodingMs != null) bits.push(`TTFT ${commaMs(row.ttftMs)} · Decoding ${commaMs(row.decodingMs)}`);
          if (bits.length) lines.push(bits.join(" · "));
          tip.textContent = lines.join("\n");
          tip.style.left = `${Math.min(window.innerWidth - 220, Math.max(12, box.left + box.width / 2 - 80))}px`;
          tip.style.top = `${box.bottom + 8}px`;
          tip.dataset.on = "true";
        }, TIMELINE_TOOLTIP_DELAY_MS);
        return;
      }
      const rect = track.getBoundingClientRect();
      let { domainStart, domainDuration } = domainState(m);
      if (viewport) {
        const localX = event.clientX - rect.left;
        const edgeWidth = Math.min(MAXIMUM_EDGE_PAN_PX, Math.max(1, rect.width * EDGE_PAN_ZONE_FRACTION));
        const direction = localX < edgeWidth ? -1 : localX > rect.width - edgeWidth ? 1 : 0;
        if (direction !== 0) {
          const edgeDistance = direction < 0 ? edgeWidth - localX : localX - (rect.width - edgeWidth);
          const strength = clamp(edgeDistance / edgeWidth, 0, 1);
          const nextStart = clamp(
            domainStart + direction * domainDuration * EDGE_PAN_STEP_FRACTION * Math.max(0.2, strength),
            m.start,
            m.end - domainDuration
          );
          viewport = { start: nextStart, end: nextStart + domainDuration };
          domainStart = nextStart;
        }
      }
      const next = domainStart + frac * domainDuration;
      draft = orderedRange(drag.t, next);
      paintOverview();
    });
    track.addEventListener("pointerup", (event) => {
      if (pan && pan.pointerId === event.pointerId) {
        const moved = pan.moved || Math.abs(event.clientX - pan.anchorClientX) >= MINIMUM_DRAG_PX;
        pan = null;
        track.dataset.panning = "false";
        if (!moved) { range = null; draft = null; paint(); }
        return;
      }
      if (!drag || drag.pointerId !== event.pointerId) return;
      const m = model();
      const { domainStart, domainDuration } = domainState(m);
      const moved = Math.abs(event.clientX - drag.x) >= MINIMUM_DRAG_PX;
      const clickId = spanIdAt(event) || drag.id;
      if (!moved && clickId) {
        range = null;
        draft = null;
        selectRecord(clickId, { clearRange: true });
      } else {
        const selectedRange = draft || orderedRange(drag.t, domainStart + fractionAt(event) * domainDuration);
        const minW = Math.min(domainDuration, (m.end - m.start) / Math.max(m.spans.length, 1));
        range = selectedRange.end - selectedRange.start < minW
          ? centeredRange(moved ? (selectedRange.start + selectedRange.end) / 2 : selectedRange.start, minW, m.start, m.end)
          : selectedRange;
        draft = null;
        if (!moved) {
          const t = selectedRange.start;
          const nearest = m.spans.reduce((best, span) => {
            const dist = t < span.start ? span.start - t : t > span.end ? t - span.end : 0;
            const bestDist = t < best.start ? best.start - t : t > best.end ? t - best.end : 0;
            return dist < bestDist ? span : best;
          });
          selected = { type: "record", id: nearest.id };
          restoreTab(selected);
        }
        paint();
        if (!moved) focusRecord(selected.id);
      }
      drag = null;
      tip.dataset.on = "false";
    });
    track.addEventListener("pointerleave", () => {
      if (!drag && !pan) { hoverLine.hidden = true; tip.dataset.on = "false"; }
    });
    track.addEventListener("dblclick", (event) => { event.preventDefault(); range = null; draft = null; paint(); });
    track.addEventListener("contextmenu", (event) => { event.preventDefault(); });
    track.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && range) { range = null; paint(); }
    });
    track.addEventListener("wheel", (event) => {
      event.preventDefault();
      const m = model();
      if (!m) return;
      const { domainStart, domainDuration, fullDuration } = domainState(m);
      const rect = track.getBoundingClientRect();
      const anchorFraction = clamp((event.clientX - rect.left) / Math.max(1, rect.width), 0, 1);
      const minZoom = Math.min(timelineMode() === "sequence" ? MINIMUM_ZOOM_OPERATIONS : 20, fullDuration);
      const nextDuration = Math.min(fullDuration, Math.max(minZoom, domainDuration * Math.exp(event.deltaY * 0.0015)));
      if (nextDuration >= fullDuration * 0.999) { viewport = null; paintOverview(); return; }
      const anchorTime = domainStart + anchorFraction * domainDuration;
      const nextStart = clamp(anchorTime - anchorFraction * nextDuration, m.start, m.end - nextDuration);
      viewport = { start: nextStart, end: nextStart + nextDuration };
      paintOverview();
    }, { passive: false });
