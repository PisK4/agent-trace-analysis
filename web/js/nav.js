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
      document.getElementById("sessList").innerHTML = visible.map(session => `
        <button class="item ${AGENT_CLASS[session.agent] || ""}" type="button" data-sid="${session.id}" aria-current="${session.id === current.id}">
          <span class="t">${esc(session.title)}</span>
          <small class="agent">${esc(AGENT_LABELS[session.agent] || session.agent)}</small>
          <small class="ts" data-ts="${Number(session.firstTs ?? 0)}" data-full="0" title="点击展开完整时间">${shortTime(Number(session.firstTs ?? 0))}</small>
        </button>`).join("");
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
      app.dataset.home = "true";
      app.dataset.inspect = "";
      paintTabs();
      paintSessions();
    }
