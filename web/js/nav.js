// ata web · 左侧导航：agent 过滤页签、会话列表、首页态与标注角标

    function paintTabs() {
      const agents = [];
      for (const s of sessions) if (!agents.includes(s.agent)) agents.push(s.agent);
      const el = document.getElementById("sessTabs");
      const tab = (key, label) => {
        const cls = key ? (AGENT_CLASS[key] || "") : "";
        const dot = key ? `<i class="dot"></i>` : "";
        return `<button type="button" class="tab ${cls}" data-agent="${key}" aria-pressed="${(agentFilter ?? "") === key}">${dot}${esc(label)}</button>`;
      };
      el.innerHTML = tab("", "全部") + agents.map(a => tab(a, AGENT_LABELS[a] || a)).join("");
      el.querySelectorAll(".tab").forEach(btn => btn.addEventListener("click", () => {
        agentFilter = btn.dataset.agent || null;
        paintTabs();
        paintSessions();
      }));
    }

    function paintSessions() {
      const visible = agentFilter ? sessions.filter(session => session.agent === agentFilter) : sessions;
      document.getElementById("sessList").innerHTML = visible.map(session => {
        // 卡片 v2 meta 行：agent · 事件数 · 错误数 · 标注点 · 时间，一眼分诊。
        // 标注点与徽章共用 .adot 三态类；错误 0 时灰化不抢眼。
        const errs = Number(session.errorCount ?? 0);
        const latest = (session.scores || [])[(session.scores || []).length - 1];
        // 无错误不渲染错误列：卡片上只留异常信号
        const errsHtml = errs ? `<span class="errs" title="${errs} failed tool calls"><svg class="ico" style="width:9px;height:9px"><use href="#i-alert"/></svg>${errs}</span>` : "";
        const adot = latest ? `<span class="adot" data-v="${esc(latest.value)}"></span>` : `<span class="adot"></span>`;
        return `
        <button class="item ${AGENT_CLASS[session.agent] || ""}" type="button" data-sid="${session.id}" aria-current="${session.id === current.id}">
          <span class="t">${esc(session.title)}</span>
          <span class="meta">
            <span class="ag">${esc(AGENT_LABELS[session.agent] || session.agent)}</span>
            <span>${Number(session.eventCount ?? 0)} evts</span>
            ${errsHtml}
            ${adot}
            <span class="ts" data-ts="${Number(session.firstTs ?? 0)}" data-full="0" title="点击展开完整时间">${shortTime(Number(session.firstTs ?? 0))}</span>
          </span>
        </button>`;
      }).join("");
      document.querySelectorAll(".item").forEach(btn => btn.addEventListener("click", () => openSession(btn.dataset.sid)));
      document.querySelectorAll(".item .ts").forEach(el => el.addEventListener("click", (e) => {
        e.stopPropagation();
        const ms = Number(el.dataset.ts);
        const expanded = el.dataset.full === "1";
        el.textContent = expanded ? shortTime(ms) : fullTime(ms);
        el.dataset.full = expanded ? "0" : "1";
      }));
    }

    function showHome() {
      current = { id:"", agent:"", title:"", crumb:"", rows:[], older:false, cursor:0, toolsIndex:{} };
      selected = null;
      range = null;
      draft = null;
      viewport = null;
      agentFilter = null;
      searchQuery = "";
      document.getElementById("q").value = "";
      const empty = sessions.length ? "选择一条会话" : "no sessions";
      document.getElementById("crumb").textContent = empty;
      document.getElementById("homeEmpty").textContent = empty;
      document.getElementById("sidBox").hidden = true;
      document.getElementById("copySidBtn").hidden = true;
      tableFilter = "";
      resetSessionPanels();
      syncFilterChips();
      app.dataset.home = "true";
      app.dataset.inspect = "";
      paintTabs();
      paintSessions();
    }
