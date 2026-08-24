// ata web · DOM 引用与全局可变状态。普通 script 共享全局作用域，加载顺序见 index.html

    const app = document.getElementById("app");
    const track = document.getElementById("track");
    const lanesEl = document.getElementById("lanes");
    const turnLinesEl = document.getElementById("turnLines");
    const selFill = document.getElementById("selFill");
    const selEdge = document.getElementById("selEdge");
    const hoverLine = document.getElementById("hoverLine");
    const earlierBtn = document.getElementById("earlier");
    const tip = document.getElementById("tip");
    const tbody = document.getElementById("rows");
    const scroller = document.getElementById("scroller");
    const details = document.getElementById("details");
    const resize = document.getElementById("resize");

    let current = { id:"", agent:"", title:"", crumb:"", rows:[], older:false, cursor:0, toolsIndex:{} };
    let agentFilter = null;
    const AGENT_LABELS = { pi: "Pi", cue: "Cue", droid: "Droid", claude: "Claude Code", codex: "Codex" };
    const AGENT_CLASS = { pi: "agent-pi", cue: "agent-cue", droid: "agent-droid", claude: "agent-claude", codex: "agent-codex" };
    let selected = null;
    let follow = true;
    let actualDuration = false;
    let actualTime = false;
    let range = null;
    let draft = null;
    let viewport = null;
    let tab = "summary";
    let tabHistory = ["summary"];
    let tipTimer = 0;
    let unixStarted = false;
    // 详情栏宽度跨会话记忆：拖拽/键盘调整后写入 localStorage，双击分隔条重置。
    let detailsWidth = (() => {
      try {
        const v = parseInt(localStorage.getItem("ata.detailsWidth"), 10);
        return Number.isFinite(v) && v > 0 ? v : null;
      } catch { return null; }
    })();
    let collapsedTurns = new Set();
    let collapsedAssistants = new Set();
    let loadingOlder = false;
    let searchQuery = "";
    let virtualWindow = { start: 0, end: 40 };
