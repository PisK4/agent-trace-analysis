// ata web · 工具层：常量、fetch/API 封装、格式化与搜索、JSON 树/diff/markdown 渲染工具

    const MINIMUM_DRAG_PX = 3;
    const MINIMUM_ZOOM_OPERATIONS = 4;
    const EDGE_PAN_ZONE_FRACTION = 0.08;
    const EDGE_PAN_STEP_FRACTION = 0.025;
    const MAXIMUM_EDGE_PAN_PX = 32;
    const TIMELINE_TOOLTIP_DELAY_MS = 500;
    const VIRTUAL_THRESHOLD = 100;
    const OVERSCAN = 12;
    const CONTENT_ROW_HEIGHT = 30;
    const COLLAPSED_SUMMARY_HEIGHT = 20;
    const DETAILS_MIN = 320;
    const DETAILS_MAX = 720;
    const TABLE_MIN = 280;
    const DETAILS_STEP = 16;
    const LOAD_NEAR_TOP = 48;

    const at = (hms) => {
      const [hour, minute, rest] = hms.split(":");
      const [second, millis = "0"] = rest.split(".");
      return new Date(2026, 7, 14, Number(hour), Number(minute), Number(second), Number(millis)).getTime();
    };
    const API = "";
    let sessions = [];

    const emptyUsage = () => ({ status: "n/a", input: null, output: null, cacheRead: null, cacheWrite: null });

    async function fetchJSON(path) {
      const res = await fetch(API + path);
      if (!res.ok) throw new Error(path + " " + res.status);
      return res.json();
    }

    async function loadSession(id, query = "") {
      const sep = query ? (query.startsWith("?") ? query : "?" + query) : "";
      const page = await fetchJSON("/api/sessions/" + encodeURIComponent(id) + sep);
      return {
        id: page.id,
        agent: page.agent,
        title: page.title,
        crumb: page.crumb,
        rows: page.rows,
        older: page.has_older,
        cursor: page.cursor,
        turns: page.turns,
        scores: page.scores || [],
        toolsIndex: page.tools_index || {}
      };
    }

    // 归组：run 列表来自 /api/runs（低频变化，进会话页时懒加载一次）
    let runsLoaded = false;
    async function ensureRunsLoaded() {
      if (runsLoaded) return;
      const box = document.getElementById("assignRun");
      try {
        const runs = await fetchJSON("/api/runs");
        for (const r of runs) {
          const opt = document.createElement("option");
          opt.value = r.run_id;
          opt.textContent = `${r.run_id} · ${r.description}`;
          box.appendChild(opt);
        }
        runsLoaded = true;
      } catch { /* 服务不可达时保持空下拉，归组按钮会拦 */ }
    }
    const laneOf = (kind) => kind === "tool" || kind === "subtool" ? 2 : kind === "assistant" || kind === "compacted" ? 1 : 0;
    const kindLabel = (kind) => ({
      system:"SYSTEM", user:"USER", context:"CONTEXT", compacted:"COMPACTED",
      assistant:"ASSISTANT", tool:"TOOL", subtool:"SUBTOOL"
    }[kind] || String(kind).toUpperCase());
    const timelineMode = () => actualDuration ? (actualTime ? "actual" : "duration") : (actualTime ? "time" : "sequence");
    const byId = (id) => current.rows.find(row => row.id === id);
    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, ch => ({ "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;" }[ch]));
    const fmtNum = (value) => value == null ? null : Number(value).toLocaleString("en-US");
    const clock = (ms) => {
      const d = new Date(ms);
      const p = (n, w=2) => String(n).padStart(w, "0");
      return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
    };
    const dayClock = (ms) => {
      const d = new Date(ms);
      const p = (n, w=2) => String(n).padStart(w, "0");
      return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${clock(ms)}`;
    };
    const p2 = (n) => String(n).padStart(2, "0");
    const shortTime = (ms) => {
      if (!ms) return "—";
      const d = new Date(ms);
      return `${p2(d.getHours())}:${p2(d.getMinutes())}`;
    };
    const fullTime = (ms) => {
      if (!ms) return "—";
      const d = new Date(ms);
      return `${d.getFullYear()}-${p2(d.getMonth()+1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}`;
    };
    const durLabel = (ms) => ms < 1000 ? `${Math.round(ms)} ms` : `${(ms/1000).toFixed(ms < 10000 ? 2 : 1)} s`;
    const commaMs = (ms) => `${Math.round(ms).toLocaleString("en-US")} ms`;
    const orderedRange = (a, b) => a <= b ? { start:a, end:b } : { start:b, end:a };
    const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
    const centeredRange = (center, width, minimum, maximum) => {
      const clampedWidth = Math.min(maximum - minimum, Math.max(0, width));
      const start = Math.min(Math.max(center - clampedWidth / 2, minimum), maximum - clampedWidth);
      return { start, end: start + clampedWidth };
    };
    const searchBlob = (row) => [
      row.tag, row.kind, row.text, row.extra, row.name, row.result, row.outputText,
      row.payloadText, row.promptText, row.note, row.thinking, row.model, row.effort,
      row.schema && row.schema.name,
      row.schema && row.schema.description, JSON.stringify(row.payload || "")
    ].join(" ").toLowerCase();
    const searchTerms = () => searchQuery.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const rowMatches = (row) => {
      const terms = searchTerms();
      if (!terms.length) return true;
      const blob = searchBlob(row);
      return terms.every(term => blob.includes(term));
    };
    const statusLabel = (status) => status === "failed" ? "Failed" : status === "cancelled" ? "Cancelled" : status === "pending" ? "Pending" : "Completed";
    const modelLabel = (row) => {
      if (!row || !row.model) return "Not present";
      return row.effort ? `${row.model} · ${row.effort}` : row.model;
    };
    const compactPreview = (text) => String(text || "").replace(/\s+/g, " ").trim();
    const rowContent = (row) => {
      if (row.kind === "tool" || row.kind === "subtool") {
        return compactPreview(row.text || row.name || row.tag);
      }
      if (row.text) return compactPreview(row.text);
      if (row.kind !== "assistant") return compactPreview(row.text);
      const names = [];
      for (const item of current.rows) {
        if (item.parentId !== row.id || (item.kind !== "tool" && item.kind !== "subtool")) continue;
        if (item.name && !names.includes(item.name)) names.push(item.name);
      }
      return names.join(" · ");
    };

    function tabsOf(target) {
      if (target.type === "request") return ["summary", "usage", "timing"];
      const row = byId(target.id);
      if (!row) return ["summary"];
      if (row.kind === "system") return row.previousPrompt ? ["diff", "prompt", "tools"] : ["prompt", "tools"];
      if (row.kind === "compacted") return ["summary", "raw"];
      if (row.kind === "tool" || row.kind === "subtool") {
        const tabs = ["summary"];
        if (row.payload || row.payloadText) tabs.push("payload");
        if (row.result || row.resultJson) tabs.push("result");
        tabs.push("schema", "timing");
        return tabs;
      }
      const tabs = ["summary", "preview", "raw"];
      if (row.messageSource) tabs.push("source");
      return tabs;
    }

    function rememberTab(id) {
      tab = id;
      tabHistory = tabHistory.filter(item => item !== id).concat(id);
    }
    function restoreTab(target) {
      const tabs = tabsOf(target);
      const found = [...tabHistory].reverse().find(id => tabs.includes(id));
      tab = found || tabs[0];
    }

    function collapsibleTurns() {
      const counts = new Map();
      for (const row of current.rows) {
        if (row.turn == null || row.kind === "system") continue;
        counts.set(row.turn, (counts.get(row.turn) || 0) + 1);
      }
      return [...counts.entries()].filter(([, n]) => n > 1).map(([turn]) => turn);
    }
    function collapsibleAssistants() {
      const ids = [];
      for (let i = 0; i < current.rows.length; i++) {
        const row = current.rows[i];
        const next = current.rows[i + 1];
        if (row.kind === "assistant" && next && (next.kind === "tool" || next.kind === "subtool")) ids.push(row.id);
      }
      return ids;
    }
    // 视图状态只存「tree 还是 pretty raw」，数据永远来自投影原文。
    const jsonViewMode = {};
    // ponytail: 阈值写死；真嫌小再提成常量或设置项。
    const STR_FOLD = 400, ARR_SLICE = 20;

    function parseMaybe(text) {
      if (typeof text !== "string" || text.length < 2) return null;
      const c = text[0];
      if (c !== "{" && c !== "[") return null;
      try {
        const v = JSON.parse(text);
        return v && typeof v === "object" ? v : null;
      } catch { return null; }
    }

    function jsonTree(value, key) {
      const label = k => `<span class="k">${esc(k)}</span>: `;
      if (value && typeof value === "object") {
        let entries, fold = "";
        if (Array.isArray(value)) {
          entries = value.slice(0, ARR_SLICE).map((item, i) => jsonTree(item, String(i)));
          if (value.length > ARR_SLICE)
            fold = `<details><summary><span class="miss">… ${value.length - ARR_SLICE} more items</span></summary>`
              + value.slice(ARR_SLICE).map((item, i) => jsonTree(item, String(i))).join("") + `</details>`;
        } else {
          entries = Object.entries(value).map(([k, v]) => jsonTree(v, k));
        }
        const name = key == null ? (Array.isArray(value) ? `array[${value.length}]` : "object") : esc(key);
        return `<details open><summary><span class="k">${name}</span></summary>${entries.join("")}${fold}</details>`;
      }
      if (typeof value === "string" && value.length > STR_FOLD) {
        const nested = parseMaybe(value);
        // 字符串里又嵌了一层 JSON（double-encoded）：展开成子树。
        if (nested)
          return `<div>${key != null ? label(key) : ""}<details open><summary><span class="s">"(embedded JSON · ${fmtNum(value.length)} chars)"</span></summary><div class="tree">${jsonTree(nested)}</div></details></div>`;
        return `<div>${key != null ? label(key) : ""}<details><summary><span class="s">"${esc(value.slice(0, STR_FOLD))}…"</span> <span class="miss">(${fmtNum(value.length)} chars)</span></summary><span class="s">${esc(value)}</span></details></div>`;
      }
      const shown = typeof value === "string" ? `"${esc(value)}"` : esc(value);
      const cls = typeof value === "string" ? "s" : "n";
      return `<div>${key != null ? label(key) : ""}<span class="${cls}">${shown}</span></div>`;
    }

    // 可解析 JSON 的内容给 tree/raw 双视图；raw 是 pretty-print 后走 hljs 高亮。
    function jsonView(stateKey, parsed) {
      const mode = jsonViewMode[stateKey] || "tree";
      const body = mode === "raw"
        ? `<pre class="blob lang-json">${esc(JSON.stringify(parsed, null, 2))}</pre>`
        : `<div class="tree">${jsonTree(parsed)}</div>`;
      return `<span class="view-toggle">
          <button type="button" data-vset="${stateKey}" data-vmode="tree" aria-selected="${mode === "tree"}">Tree</button>
          <button type="button" data-vset="${stateKey}" data-vmode="raw" aria-selected="${mode === "raw"}">Raw</button>
        </span>${body}`;
    }

    // ponytail: 只裁公共前后缀、不做 LCS，对「模型改了几个字段」这类局部编辑够用；
    // 大范围改写会显示成大段 +/-，届时再上真正的 diff 算法。
    function lineDiff(before, after) {
      const A = before.split("\n"), B = after.split("\n");
      let s = 0;
      while (s < A.length && s < B.length && A[s] === B[s]) s++;
      let e = 0;
      while (e < A.length - s && e < B.length - s && A[A.length - 1 - e] === B[B.length - 1 - e]) e++;
      const ctx = 2, parts = [];
      if (s > ctx) parts.push(`<span class="miss">… ${s - ctx} unchanged lines</span>`);
      for (let i = Math.max(0, s - ctx); i < s; i++) parts.push(`  ${esc(A[i])}`);
      for (let i = s; i < A.length - e; i++) parts.push(`<span class="del">- ${esc(A[i])}</span>`);
      for (let i = s; i < B.length - e; i++) parts.push(`<span class="add">+ ${esc(B[i])}</span>`);
      const tailStart = Math.max(A.length - e, s);
      if (A.length - tailStart > ctx) parts.push(`<span class="miss">… ${A.length - e - tailStart - ctx} unchanged lines</span>`);
      for (let i = tailStart; i < Math.min(tailStart + ctx, A.length); i++) parts.push(`  ${esc(A[i])}`);
      return `<pre class="blob diff">${parts.join("\n") || "Identical arguments"}</pre>`;
    }
    if (window.marked) {
      // 语料是本地会话文本，不构成高信任边界：原始 HTML 一律转义成文本，
      // 链接只放行 http(s) 协议。表格/换行走 GFM（marked 默认 gfm 开启）。
      marked.use({
        gfm: true,
        breaks: true,
        renderer: {
          html(token) { return esc(token.raw); },
          link(token) {
            const href = token.href || "";
            if (!/^(https?:)?\/\//i.test(href) && !/^mailto:/i.test(href)) return esc(token.text);
            return `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(token.text)}</a>`;
          }
        }
      });
    }
    function markdown(text) {
      const source = text ?? "";
      let html;
      try {
        html = window.marked ? marked.parse(source) : esc(source).replace(/\n/g, "<br>");
      } catch (err) {
        html = esc(source).replace(/\n/g, "<br>");
      }
      return `<div class="md">${html}</div>`;
    }
    function highlightMd() {
      if (!window.hljs) return;
      document.querySelectorAll(".md pre code").forEach(el => {
        if (el.dataset.highlighted) return;
        try { hljs.highlightElement(el); } catch (err) { /* 保留纯文本 */ }
        el.dataset.highlighted = "1";
      });
      document.querySelectorAll("pre.blob.lang-json").forEach(el => {
        if (el.dataset.highlighted) return;
        try { hljs.highlightElement(el); } catch (err) { /* 保留纯文本 */ }
        el.dataset.highlighted = "1";
      });
    }
    const fmtCost = (value) => value == null ? null : (Math.abs(value) < 0.01 ? Number(value).toPrecision(3) : fmtNum(value));
    function usageCells(usage) {
      const cell = (label, value, status) => {
        const miss = status === "n/a" || status === "missing" || value == null;
        return `<div class="u-cell"><span>${label}</span>${miss ? `<b class="miss">${status === "n/a" ? "—" : "Missing"}</b>` : `<b>${value}</b>`}</div>`;
      };
      const status = usage.status;
      const st = (value) => status === "n/a" ? "n/a" : value == null ? "missing" : status;
      return `<div class="usage-grid">
        ${cell("Input", fmtNum(usage.input), st(usage.input))}
        ${cell("Output", fmtNum(usage.output), st(usage.output))}
        ${cell("Cache read", fmtNum(usage.cacheRead), st(usage.cacheRead))}
        ${cell("Cache write", fmtNum(usage.cacheWrite), st(usage.cacheWrite))}
        ${cell("Total tokens", fmtNum(usage.totalTokens), st(usage.totalTokens))}
        ${cell("Cost", fmtCost(usage.cost), st(usage.cost))}
      </div>`;
    }
    function sessionUsage() {
      // Session cumulative：按已加载窗口内所有 reported 的 assistant 行累计
      // （与 dsh 的窗口投影同思路：只统计前端已到手的数据）。
      const total = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: 0 };
      let count = 0;
      for (const row of current.rows) {
        const u = row.usage;
        if (row.kind !== "assistant" || !u || u.status !== "reported") continue;
        count += 1;
        for (const key of ["input", "output", "cacheRead", "cacheWrite", "totalTokens", "cost"]) {
          if (typeof u[key] === "number") total[key] += u[key];
        }
      }
      if (!count) return null;
      return { usage: { ...total, status: "reported" }, count };
    }
    function section(label, tabId, inner) {
      return `<div class="sec"><button class="sec-h" type="button" data-open="${tabId}">${label} <span>›</span></button>${inner}</div>`;
    }
    function thinkingBlock(text) {
      if (!text) return "";
      return `<details class="think"><summary>Thinking</summary><div class="think-body">${markdown(text)}</div></details>`;
    }
    function previewBody(row) {
      const shown = row.kind === "assistant"
        ? (row.outputText || "")
        : (row.payloadText || row.outputText || row.text || "");
      // 整条正文就是一份 JSON（Cue 意图 context 等）：不进 markdown，给结构化视图。
      const parsed = row.kind === "assistant" ? null : parseMaybe(shown);
      // 像 JSON 但解析失败（上游截断损坏）：至少给等宽块，别让 marked 糊成一段。
      const brokenJson = !parsed && !row.thinking && /^\s*[{[]/.test(shown) && shown.length > 200;
      const html = thinkingBlock(row.thinking)
        + (shown
          ? (parsed ? jsonView(`${row.id}:body`, parsed)
            : brokenJson ? `<pre class="blob">${esc(shown)}</pre>`
            : markdown(shown))
          : "");
      return html || `<p class="miss">No content</p>`;
    }
    function tokenRows(row) {
      const usage = row.usage || {};
      const output = usage.output;
      const think = usage.reasoning;
      const content = output != null && think != null ? Math.max(0, output - think) : null;
      return `<div><dt>Tokens</dt><dd>${output == null ? "—" : `${fmtNum(output)} tok`}</dd></div>`
        + (think != null ? `<div><dt>Reasoning</dt><dd>${fmtNum(think)} tok</dd></div>` : "")
        + (content != null ? `<div><dt>Content</dt><dd>${fmtNum(content)} tok</dd></div>` : "");
    }
    function startedButton(ms) {
      if (!Number.isFinite(ms)) return `<dd>Not available</dd>`;
      const label = unixStarted ? (ms / 1000).toFixed(3) : dayClock(ms);
      return `<dd><button class="stamp" id="startedBtn" type="button" title="${unixStarted ? "Show local time" : "Show Unix timestamp"}">${label}</button></dd>`;
    }
    function unifiedDiff(before, after) {
      if (before === after) return `<pre class="blob miss">No prompt change</pre>`;
      return `<pre class="blob diff"><span class="del">- ${esc(before)}</span>\n<span class="add">+ ${esc(after)}</span></pre>`;
    }

    // 工具 result：能解析成 JSON 就给双视图，否则维持原文 pre。
    function resultInner(row) {
      const parsed = parseMaybe(row.result || "");
      return `<div class="copyable" data-copy="result">${
        parsed ? jsonView(`${row.id}:result`, parsed) : `<pre class="blob">${esc(row.result)}</pre>`
      }</div>`;
    }

    // 同名工具的上一次调用入参 diff；没有前例或两侧 payload 都缺时返回空。
    function prevCallDiff(row) {
      const same = current.rows.filter(r => r.kind === "tool" && r.name === row.name && r._seq < row._seq);
      const prev = same[same.length - 1];
      if (!prev || !row.payload || !prev.payload) return "";
      return lineDiff(JSON.stringify(prev.payload, null, 2), JSON.stringify(row.payload, null, 2));
    }
