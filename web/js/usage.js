// ata web · Usage 全周期面板：占用/缓存命中率双层曲线 + 体检发现 + 轮级跳转。
// 数据全部来自 GET /api/sessions/{id}/usage（后端纯派生视图，无新 writer）。

    let usageState = { open: false, data: null };

    function resetUsagePanel() {
      usageState = { open: false, data: null };
      document.getElementById("usagePanel").hidden = true;
      document.getElementById("usageBadge").setAttribute("aria-expanded", "false");
      paintUsageBadge();
    }

    // 常驻徽章：轮数 + token 总量摘要（in/out/cache R）；发现只在面板清单里呈现。
    function paintUsageBadge() {
      const badge = document.getElementById("usageBadge");
      badge.hidden = !current.id || !usageState.data;
      const el = document.getElementById("usageBadgeText");
      const d = usageState.data;
      if (!d) { el.innerHTML = ""; return; }
      const t = d.total || {};
      el.innerHTML = `<b>Usage · ${d.audit.reported_turns} turns</b>` +
        ` · ↓ ${fmtK(t.input || 0)} ↑ ${fmtK(t.output || 0)} ↓c ${fmtK(t.cache_read || 0)}`;
    }

    async function refreshUsage() {
      if (!current.id) return;
      try {
        usageState.data = await fetchJSON("/api/sessions/" + encodeURIComponent(current.id) + "/usage");
      } catch { usageState.data = null; }
      paintUsageBadge();
      if (usageState.open) renderUsagePanel();
    }

    async function toggleUsagePanel() {
      const panel = document.getElementById("usagePanel");
      usageState.open = panel.hidden;
      panel.hidden = !usageState.open;
      document.getElementById("usageBadge").setAttribute("aria-expanded", String(usageState.open));
      if (usageState.open) {
        await refreshUsage();
        renderUsagePanel();
      }
    }

    const URULE_LABEL = { missing: "缺 usage", placeholder: "占位值", duplicate: "重复嫌疑", cliff: "断崖嫌疑" };

    function renderUsagePanel() {
      const d = usageState.data;
      if (!d) return;
      const a = d.audit;
      const turns = d.turns || [];
      const maxTurn = Math.max(a.expected_turns, 1);
      const rep = turns.filter(t => t.status === "reported");
      const W = 840, L = 52, R = 14;
      // 上层占用（方言感知的 context 口径，后端算好），下层命中率，同一条轮次横轴。
      const occTop = 26, occBot = 150, hitTop = 186, hitBot = 246, H = 262;
      const maxIn = Math.max(1, ...rep.map(t => t.context || t.input || 0));
      const plotW = W - L - R;
      const x = turn => maxTurn > 1 ? L + plotW * (turn - 1) / (maxTurn - 1) : L + plotW / 2;
      const yIn = v => occBot - (occBot - occTop) * Math.min(v, maxIn) / maxIn;
      const yHit = r => hitBot - (hitBot - hitTop) * Math.min(r, 100) / 100;
      const byTurn = {};
      turns.forEach(t => { byTurn[t.turn] = t; });
      const susp = {};
      a.findings.forEach(f => { if (f.rule !== "missing") susp[f.turn] = f.rule; });

      // 占用曲线在 missing 轮断开，不补线——缺口本身就是信息。
      const segs = [];
      let cur = [];
      turns.forEach(t => {
        if (t.status !== "reported") { if (cur.length > 1) segs.push(cur.join(" ")); cur = []; return; }
        cur.push(`${x(t.turn).toFixed(1)},${yIn(t.context || t.input || 0).toFixed(1)}`);
      });
      if (cur.length > 1) segs.push(cur.join(" "));
      const occArea = rep.length > 1
        ? `<polygon points="${L},${occBot} ${rep.map(t => `${x(t.turn).toFixed(1)},${yIn(t.context || t.input || 0).toFixed(1)}`).join(" ")} ${L + plotW},${occBot}" class="uc-area"/>` : "";
      const occLine = segs.map(s => `<polyline points="${s}" class="uc-line"/>`).join("");

      const hitPts = rep.filter(t => (t.context || 0) > 0 && t.cache_read != null);
      const hitLine = hitPts.length > 1
        ? `<polyline points="${hitPts.map(t => `${x(t.turn).toFixed(1)},${yHit((t.cache_read || 0) / t.context * 100).toFixed(1)}`).join(" ")}" class="uc-hit"/>` : "";
      // 演示同款极值标注：命中率最低的一轮，点名让人看见。
      let minHitAnno = "";
      if (hitPts.length > 2) {
        const minT = hitPts.reduce((a, b) =>
          (a.cache_read / a.context) <= (b.cache_read / b.context) ? a : b);
        const rate = (minT.cache_read / minT.context * 100).toFixed(1);
        const ax = x(minT.turn), ay = yHit(minT.cache_read / minT.context * 100);
        const anchor = ax > W - 180 ? "end" : ax < L + 120 ? "start" : "middle";
        const dx = anchor === "end" ? -6 : anchor === "start" ? 6 : 0;
        minHitAnno = `<circle cx="${ax}" cy="${ay}" r="3" class="uc-hitmin"/>` +
          `<text x="${ax + dx}" y="${ay - 7}" text-anchor="${anchor}" class="uc-anno">命中率最低 T${minT.turn} · ${rate}%</text>`;
      }

      const grid = [0, .5, 1].map(f => {
        const v = maxIn * f, y = yIn(v);
        return `<line x1="${L}" y1="${y}" x2="${W - R}" y2="${y}" class="uc-grid"/>` +
          `<text x="${L - 6}" y="${y + 3}" text-anchor="end" class="uc-cap">${fmtK(v)}</text>`;
      }).join("");
      // compaction：竖线贯穿两层 + 落差标注（−N），与参考演示同构。
      const compAnno = (d.compactions || []).map(c => {
        if (c.turn == null) return "";
        const cx = x(c.turn);
        let s = `<line x1="${cx}" y1="${occTop}" x2="${cx}" y2="${hitBot}" class="uc-comp"/>`;
        const cur = byTurn[c.turn];
        const prev = [...rep].reverse().find(r => r.turn < c.turn);
        if (cur && prev && (prev.context || 0) > (cur.context || 0)) {
          const drop = prev.context - cur.context;
          s += `<text x="${cx + 6}" y="${(yIn(prev.context) + yIn(cur.context)) / 2 + 3}" class="uc-drop">−${fmtK(drop)}</text>`;
        }
        return s;
      }).join("");
      const dots = rep.map(t => susp[t.turn]
        ? `<circle cx="${x(t.turn)}" cy="${yIn(t.context || t.input || 0)}" r="4" class="uc-dot bad" data-u="${t.turn}"/>` : "").join("");
      const turnAxis = maxTurn > 1
        ? `<text x="${L}" y="${H - 4}" class="uc-cap">T1</text><text x="${W - R}" y="${H - 4}" text-anchor="end" class="uc-cap">T${maxTurn}</text>` : "";

      document.getElementById("usageCurve").innerHTML =
        `<svg viewBox="0 0 ${W} ${H}" class="uc-svg" id="ucSvg">${grid}${occArea}${occLine}${hitLine}${compAnno}${dots}${minHitAnno}
          <text x="${L}" y="${occTop - 8}" class="uc-lab">context / 轮（max ${fmtK(maxIn)}）· 断口 = missing</text>
          <text x="${L}" y="${hitTop - 8}" class="uc-lab">缓存命中率</text>
          <line x1="${L}" y1="${hitBot}" x2="${W - R}" y2="${hitBot}" class="uc-grid"/>
          <text x="${L - 6}" y="${hitBot + 3}" text-anchor="end" class="uc-cap">0%</text>
          <text x="${L - 6}" y="${hitTop + 3}" text-anchor="end" class="uc-cap">100%</text>
          ${turnAxis}</svg><div class="uc-tip" id="ucTip" hidden></div>`;

      const total = d.total || {};
      document.getElementById("usageSum").textContent =
        `Σ ${fmtK(total.total_tokens || 0)} tok · in ${fmtK(total.input || 0)} · out ${fmtK(total.output || 0)}` +
        ` · cache R ${fmtK(total.cache_read || 0)} · W ${fmtK(total.cache_write || 0)}` +
        (d.missing_turns ? ` · ${d.missing_turns} 轮缺` : "");

      const wrap = document.getElementById("usageFindingsWrap");
      wrap.hidden = !a.findings.length;
      document.getElementById("usageFindingsSum").textContent =
        `${a.findings.length} 处发现`;
      document.getElementById("usageFindings").innerHTML = a.findings.map(f => {
        const row = byTurn[f.turn];
        return `<button class="uf-row" type="button" data-useq="${row ? row.seq : ""}">
          <span class="uf-rule ${f.rule}">${URULE_LABEL[f.rule] || f.rule}</span>
          <span class="uf-turn">T${f.turn}</span>
          <span class="uf-detail">${esc(f.detail)}</span></button>`;
      }).join("");

      const svg = document.getElementById("ucSvg");
      const tip = document.getElementById("ucTip");
      svg.addEventListener("mousemove", ev => {
        const rect = svg.getBoundingClientRect();
        const mx = (ev.clientX - rect.left) / rect.width * W;
        const turn = Math.max(1, Math.min(maxTurn, Math.round(1 + (mx - L) / plotW * (maxTurn - 1))));
        const t = byTurn[turn];
        tip.hidden = !t;
        if (!t) return;
        const rate = (t.context || 0) > 0 && t.cache_read != null ? ((t.cache_read || 0) / t.context * 100).toFixed(1) + "%" : "—";
        tip.innerHTML = `<b>第 ${t.turn} 轮 · ${esc(t.status)}</b>` +
          `<div>context ${fmtNum(t.context)} · 输入 ${fmtNum(t.input)} · 输出 ${fmtNum(t.output)}</div>` +
          `<div>缓存读取 ${fmtNum(t.cache_read)} · 命中 ${rate}</div>` +
          (t.cache_write != null ? `<div>缓存写入 ${fmtNum(t.cache_write)}</div>` : "") +
          `<div>总 ${fmtNum(t.total_tokens)} tok${t.cost != null ? ` · $${fmtCost(t.cost)}` : ""}</div>` +
          (susp[t.turn] ? `<div class="uc-tip-bad">${URULE_LABEL[susp[t.turn]] || susp[t.turn]}</div>` : "");
        const px = Math.min(Math.max(x(turn) / W * rect.width, 70), rect.width - 70);
        tip.style.left = px + "px";
      });
      svg.addEventListener("mouseleave", () => { tip.hidden = true; });
      svg.addEventListener("click", ev => {
        const dot = ev.target.closest("[data-u]");
        if (!dot) return;
        const row = byTurn[+dot.dataset.u];
        if (row && row.seq) jumpToSeq(row.seq);
      });
      document.querySelectorAll("#usageFindings .uf-row").forEach(btn =>
        btn.addEventListener("click", () => { if (btn.dataset.useq) jumpToSeq(+btn.dataset.useq); }));
    }

    function fmtK(v) {
      return v >= 10000 ? (v / 1000).toFixed(v >= 100000 ? 0 : 1) + "K" : String(Math.round(v));
    }

    document.getElementById("usageBadge").addEventListener("click", toggleUsagePanel);
    document.getElementById("usageClose").addEventListener("click", toggleUsagePanel);
