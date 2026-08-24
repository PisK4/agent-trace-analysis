// ata web · 详情面板：全部 tab 的渲染与面板内事件绑定

    // 上一帧 body 的归属标记（行|tab），用于判断 <details> 快照能否跨重绘复用。
    let paintedDetailsKey = "";

    function paintInspector() {
      if (!selected) { app.dataset.inspect = ""; return; }
      app.dataset.inspect = "open";
      if (detailsWidth != null) details.style.width = `${detailsWidth}px`;
      else details.style.width = "";
      const tabs = tabsOf(selected);
      if (!tabs.includes(tab)) tab = tabs[0];
      const tag = document.getElementById("dTag");
      const loc = document.getElementById("dLoc");
      const body = document.getElementById("dBody");
      // follow 轮询每秒重绘会重置 DOM 里的 <details> 展开态（tool-card / jsonTree / think）。
      // 重绘前快照；仅当行与 tab 都没换（结构大概率一致）且数量对得上才按原顺序恢复。
      const detailsKey = `${selected.id}|${tab}`;
      const sameLayout = detailsKey === paintedDetailsKey;
      const openDetails = sameLayout ? [...body.querySelectorAll("details")].map(d => d.open) : [];
      if (selected.type === "request") {
        const row = byId(selected.id);
        tag.className = "kind request";
        tag.innerHTML = `<span class="req-chip-dot"></span>Request #${row.requestNo}`;
        loc.textContent = row.turn == null ? "SYSTEM" : `Turn ${row.turn} · ${row.group || "Step"}`;
        document.getElementById("tabs").innerHTML = tabs.map(id =>
          `<button class="tab" type="button" data-tab="${id}" aria-selected="${id === tab}">${id[0].toUpperCase() + id.slice(1)}</button>`
        ).join("");
        const siblings = current.rows.filter(item => item.requestNo === row.requestNo || item.parentId === row.id || (item.group === row.group && item.turn === row.turn));
        const tools = siblings.filter(item => item.kind === "tool").length;
        const subs = siblings.filter(item => item.kind === "subtool").length;
        if (tab === "summary") {
          body.innerHTML = `<dl class="kv">
            <div><dt>Status</dt><dd>${statusLabel(row.status)}</dd></div>
            <div><dt>Provider</dt><dd>${esc(current.agent || "Not present")}</dd></div>
            <div><dt>Model</dt><dd>${esc(modelLabel(row))}</dd></div>
            <div><dt>Tool calls</dt><dd>${tools}</dd></div>
            <div><dt>Subtool calls</dt><dd>${subs}</dd></div>
            <div><dt>Result</dt><dd><button class="jump" type="button" data-jump="${row.id}">Assistant Message <i>›</i></button></dd></div>
          </dl>`;
        } else if (tab === "usage") {
          const cum = sessionUsage();
          body.innerHTML = `<div class="sec"><div class="sec-h">This request</div>${usageCells(row.usage)}</div>
            <div class="sec"><div class="sec-h">Session cumulative${cum ? ` · ${cum.count} request${cum.count > 1 ? "s" : ""}` : ""}</div>${cum ? usageCells(cum.usage) : `<p class="miss">No reported usage in loaded window.</p>`}</div>`;
        } else {
          body.innerHTML = `<dl class="kv">
            <div><dt>Started</dt>${startedButton(row.startedAt)}</div>
            <div><dt>Duration</dt><dd>${durLabel(row.durationMs)}</dd></div>
            ${row.ttftMs != null ? `<div><dt>TTFT</dt><dd>${durLabel(row.ttftMs)}</dd></div>` : ""}
            ${row.decodingMs != null ? `<div><dt>Generation</dt><dd>${durLabel(row.decodingMs)}</dd></div>` : ""}
            ${row.outputTokens && row.decodingMs ? `<div><dt>Throughput</dt><dd>${(row.outputTokens / (row.decodingMs / 1000)).toFixed(1)} tok/s</dd></div>` : ""}
          </dl>`;
        }
      } else {
        const row = byId(selected.id);
        if (!row) { app.dataset.inspect = ""; return; }
        tag.className = `kind ${row.kind}`;
        tag.textContent = row.tag;
        loc.textContent = row.turn == null ? "SYSTEM" : `Turn ${row.turn} · Step ${row.step}`;
        document.getElementById("tabs").innerHTML = tabs.map(id => {
          const label = { summary:"Summary", payload:"Payload", result:"Result", schema:"Schema", timing:"Timing", preview:"Preview", raw:"Raw", source:"Source", prompt:"System Prompt", tools:"Tools", skills:"Skills", diff:"Diff" }[id] || id;
          return `<button class="tab" type="button" data-tab="${id}" aria-selected="${id === tab}">${label}</button>`;
        }).join("");
        const parent = row.parentId ? byId(row.parentId) : null;
        const grand = parent && parent.parentId ? byId(parent.parentId) : null;
        if (row.kind === "system") {
          if (tab === "prompt") body.innerHTML = `<div class="sec"><div class="copyable" data-copy="prompt">${markdown(row.promptText || "")}</div></div>`;
          else if (tab === "tools") body.innerHTML = (row.toolsCatalog || []).map(tool =>
            `<details class="tool-card"><summary>${esc(tool.name)}</summary><div class="inner"><p class="miss">${esc(tool.description)}</p>${tool.parameters && Object.keys(tool.parameters).length ? `<div class="tree">${jsonTree(tool.parameters)}</div>` : ""}</div></details>`
          ).join("");
          else if (tab === "skills") body.innerHTML = (row.skillsCatalog || []).length ? row.skillsCatalog.map(skill =>
            // skill 元素结构按 Pi Skill 接口防御式渲染：name 做标题，其余字段全部展示。
            `<details class="tool-card"><summary>${esc(skill.name || "skill")}</summary><div class="inner"><dl class="kv">${
              Object.entries(skill).filter(([k, v]) => k !== "name" && v != null).map(([k, v]) =>
                `<div><dt>${esc(k)}</dt><dd>${esc(typeof v === "object" ? JSON.stringify(v) : String(v))}</dd></div>`
              ).join("")
            }</dl></div></details>`
          ).join("") : `<div class="sec"><p class="miss">No skills injected in this round.</p></div>`;
          else body.innerHTML = `<div class="sec">${unifiedDiff(row.previousPrompt || "", row.promptText || "")}</div>`;
        } else if (row.kind === "compacted") {
          if (tab === "raw") {
            body.innerHTML = `<div class="sec"><div class="copyable" data-copy="raw"><pre class="blob">${esc(row.outputText || row.text || "No output")}</pre></div></div>`;
          } else {
            body.innerHTML = `<dl class="kv">
              <div><dt>Status</dt><dd>${statusLabel(row.status)}</dd></div>
              ${row.note ? `<div><dt>Note</dt><dd>${esc(row.note)}</dd></div>` : ""}
              <div><dt>Summary</dt><dd>${esc(row.text || "Context compacted")}</dd></div>
            </dl>`;
          }
        } else if (tab === "summary") {
          const toolSchema = row.schema || (current.toolsIndex && current.toolsIndex[row.name]);
          const isMarkdown = row.kind === "assistant" || row.kind === "user" || row.kind === "context";
          body.innerHTML = `
            <dl class="kv">
              ${parent ? `<div><dt>Hierarchy</dt><dd><button class="jump" type="button" data-jump="${parent.id}">${parent.kind === "assistant" ? "Assistant Message" : parent.tag} <i>›</i></button>${grand ? ` · <button class="jump" type="button" data-jump="${grand.id}">${grand.tag} <i>›</i></button>` : ""}</dd></div>` : ""}
              <div><dt>Status</dt><dd>${statusLabel(row.status)}</dd></div>
              ${row.kind === "assistant" && row.model ? `<div><dt>Model</dt><dd>${esc(modelLabel(row))}</dd></div>` : ""}
              ${row.kind === "assistant" ? tokenRows(row) : ""}
              ${(row.kind === "user" || row.kind === "context") ? `<div><dt>Duration</dt><dd>${durLabel(row.durationMs || 0)}</dd></div>` : ""}
              ${row.note ? `<div><dt>Note</dt><dd>${esc(row.note)}</dd></div>` : ""}
            </dl>
            ${isMarkdown ? section("Preview", "preview", `<div class="copyable" data-copy="preview">${previewBody(row)}</div>`) : ""}
            ${!isMarkdown && row.payload ? section("Payload", "payload", `<div class="copyable" data-copy="payload">${jsonView(`${row.id}:payload`, row.payload)}</div>`) : ""}
            ${!isMarkdown && row.result ? section("Result", "result", resultInner(row)) : ""}
            ${!isMarkdown && toolSchema ? section("Schema", "schema", `<div class="schema-box"><h3>${esc(toolSchema.name)}</h3>${toolSchema.description ? `<p>${esc(toolSchema.description)}</p>` : ""}</div>`) : ""}
            ${row.kind === "tool" && prevCallDiff(row) ? `<div class="sec"><div class="sec-h">Diff vs previous "${esc(row.name)}" call</div>${prevCallDiff(row)}</div>` : ""}
            ${section(row.kind === "assistant" ? "Request Timing" : "Timing", "timing", `<dl class="kv">
              <div><dt>Started</dt>${startedButton(row.startedAt)}</div>
              <div><dt>Duration</dt><dd>${durLabel(row.durationMs || 0)}</dd></div>
              <div><dt>Timing source</dt><dd>Session timestamps</dd></div>
            </dl>`)}`;
        } else if (tab === "payload") {
          body.innerHTML = row.payload
            ? `<div class="sec"><div class="copyable" data-copy="payload">${jsonView(`${row.id}:payload`, row.payload)}</div></div>`
            : row.payloadText ? `<div class="sec"><div class="copyable" data-copy="preview">${markdown(row.payloadText)}</div></div>`
            : `<div class="sec miss">No payload captured</div>`;
        } else if (tab === "result") {
          body.innerHTML = row.result
            ? `<div class="sec">${resultInner(row)}</div>`
            : `<div class="sec miss">No result captured</div>`;
        } else if (tab === "schema") {
          const toolSchema = row.schema || (current.toolsIndex && current.toolsIndex[row.name]);
          const params = toolSchema && toolSchema.parameters && typeof toolSchema.parameters === "object" && Object.keys(toolSchema.parameters).length ? toolSchema.parameters : null;
          body.innerHTML = toolSchema
            ? `<div class="sec"><div class="schema-box"><h3>${esc(toolSchema.name)}</h3>${toolSchema.description ? `<p>${esc(toolSchema.description)}</p>` : ""}</div>${params ? `<div class="tree">${jsonTree(params)}</div>` : `<p class="miss" style="margin-top:6px">Parameters not recorded in source log</p>`}</div>`
            : `<div class="sec miss">Schema unavailable</div>`;
        } else if (tab === "timing") {
          const throughput = row.outputTokens && row.decodingMs
            ? `${(row.outputTokens / (row.decodingMs / 1000)).toFixed(1)} tok/s`
            : null;
          body.innerHTML = `<dl class="kv">
            <div><dt>Started</dt>${startedButton(row.startedAt)}</div>
            <div><dt>Duration</dt><dd>${row.durationMs ? durLabel(row.durationMs) : "Pending"}</dd></div>
            <div><dt>TTFT</dt><dd>${row.ttftMs != null ? durLabel(row.ttftMs) : "First token unavailable"}</dd></div>
            <div><dt>Generation</dt><dd>${row.decodingMs != null ? durLabel(row.decodingMs) : "Not recorded"}</dd></div>
            ${throughput ? `<div><dt>Throughput</dt><dd>${throughput}</dd></div>` : `<div><dt>Throughput</dt><dd class="miss">Usage unavailable</dd></div>`}
            <div><dt>Timing source</dt><dd>Session timestamps</dd></div>
          </dl>`;
        } else if (tab === "preview") {
          body.innerHTML = `<div class="sec"><div class="copyable" data-copy="preview">${previewBody(row)}</div></div>`;
        } else if (tab === "raw" || tab === "source") {
          const raw = [row.thinking, row.outputText || row.payloadText || row.text].filter(Boolean).join("\n\n");
          body.innerHTML = `<div class="sec"><div class="copyable" data-copy="raw"><pre class="blob">${esc(raw || "No content")}</pre></div></div>`;
        }
      }
      document.querySelectorAll("#tabs .tab").forEach(btn => btn.addEventListener("click", () => { rememberTab(btn.dataset.tab); paintInspector(); }));
      body.querySelectorAll("[data-open]").forEach(btn => btn.addEventListener("click", () => { rememberTab(btn.dataset.open); paintInspector(); }));
      body.querySelectorAll("[data-vset]").forEach(btn => btn.addEventListener("click", () => { jsonViewMode[btn.dataset.vset] = btn.dataset.vmode; paintInspector(); }));
      body.querySelectorAll("[data-jump]").forEach(btn => btn.addEventListener("click", () => selectRecord(btn.dataset.jump)));
      body.querySelectorAll("[data-open-req]").forEach(btn => btn.addEventListener("click", () => selectRequest(btn.dataset.openReq)));
      const startedBtn = document.getElementById("startedBtn");
      if (startedBtn) startedBtn.addEventListener("click", (event) => {
        const sel = window.getSelection();
        if (sel && !sel.isCollapsed && sel.rangeCount && sel.getRangeAt(0).intersectsNode(event.currentTarget)) return;
        unixStarted = !unixStarted;
        paintInspector();
      });
      // 大块内容统一复制入口：chip 从 row 字段取原文，不从 DOM 抄
      // （markdown 保住源码、payload 抄不出干净 JSON）。
      const copyRow = byId(selected.id);
      if (copyRow) body.querySelectorAll("[data-copy]").forEach(wrap => {
        const btn = document.createElement("button");
        btn.className = "copy-chip";
        btn.type = "button";
        btn.title = "复制内容";
        btn.textContent = "⧉";
        btn.addEventListener("click", async () => {
          const kind = wrap.dataset.copy;
          let text = "";
          if (kind === "payload") text = JSON.stringify(copyRow.payload ?? null, null, 2);
          else if (kind === "raw") text = [copyRow.thinking, copyRow.outputText || copyRow.payloadText || copyRow.text].filter(Boolean).join("\n\n");
          else if (kind === "prompt") text = copyRow.promptText || "";
          else text = copyRow.result || copyRow.outputText || copyRow.payloadText || copyRow.text || "";
          try {
            await navigator.clipboard.writeText(text);
            btn.textContent = "✓";
          } catch {
            btn.textContent = "✕";
          }
          setTimeout(() => { btn.textContent = "⧉"; }, 900);
        });
        wrap.appendChild(btn);
      });
      const after = body.querySelectorAll("details");
      if (sameLayout && after.length === openDetails.length) after.forEach((d, i) => { d.open = openDetails[i]; });
      paintedDetailsKey = detailsKey;
      highlightMd();
    }
