const ATA_URL = process.env.ATA_URL || "http://127.0.0.1:8787";

function usageFromAssistant(message: any) {
  const raw = message?.usage || {};
  const stop = message?.stopReason;
  const counts = [raw.input || 0, raw.output || 0, raw.cacheRead || 0, raw.cacheWrite || 0];
  if ((stop === "error" || stop === "aborted") && counts.every((n: number) => n === 0)) {
    return { status: "missing", input: null, output: null, cache_read: null, cache_write: null, total_tokens: null, cost: null };
  }
  if (!message?.usage) return null;
  return {
    status: "reported",
    input: raw.input,
    output: raw.output,
    cache_read: raw.cacheRead,
    cache_write: raw.cacheWrite,
    total_tokens: raw.totalTokens,
    cost: raw.cost?.total ?? raw.cost ?? null,
  };
}

function messageText(msg: any) {
  const content = msg?.content;
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content.map((b: any) => (typeof b === "string" ? b : b?.type === "text" ? b.text : "")).filter(Boolean).join("\n");
}

async function post(event: object) {
  await fetch(`${ATA_URL}/api/events`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(event),
  });
}

export default function (pi: any) {
  const state: any = {};
  const sessionId = () => state.session_id || pi?.sessionManager?.getSessionId?.() || "pi-session";

  const send = (partial: object) => post({ v: 1, agent_id: "pi", session_id: sessionId(), ...partial });

  pi.on("agent_start", async (_event: any, ctx: any) => {
    state.session_id = ctx?.sessionManager?.getSessionId?.() || sessionId();
    await send({ id: `${sessionId()}:opened`, ts: Date.now(), type: "session.opened", turn: null, payload: { title: state.session_id } });
  });
  pi.on("turn_start", async (event: any) => {
    const turn = (event.turnIndex ?? 0) + 1;
    state.turn = turn;
    await send({ id: `${sessionId()}:turn:${turn}:start`, ts: event.timestamp || Date.now(), type: "turn.started", turn, payload: {} });
  });
  pi.on("message_end", async (event: any) => {
    const msg = event.message || {};
    if (msg.role !== "user" && msg.role !== "assistant") return;
    const turn = state.turn || 1;
    const mid = String(msg.responseId || `${sessionId()}:${turn}:${msg.role}`);
    if (msg.role === "assistant") state.last_assistant_id = mid;
    await send({
      id: `${sessionId()}:msg:${mid}:end`,
      ts: msg.timestamp || Date.now(),
      type: "message.upserted",
      turn,
      payload: {
        message_id: mid,
        role: msg.role,
        text: messageText(msg).slice(0, 200),
        status: "completed",
        request_no: msg.role === "assistant" ? (state.request_no = (state.request_no || 0) + 1) : null,
        usage: msg.role === "assistant" ? usageFromAssistant(msg) : null,
        started_at: msg.timestamp || Date.now(),
        duration_ms: 1,
        output_text: msg.role === "assistant" ? messageText(msg) : null,
      },
    });
  });
  pi.on("tool_execution_start", async (event: any) => {
    await send({
      id: `${sessionId()}:tool:${event.toolCallId}`,
      ts: Date.now(),
      type: "tool.upserted",
      turn: state.turn || 1,
      payload: {
        tool_call_id: event.toolCallId,
        parent_message_id: state.last_assistant_id,
        name: event.toolName,
        text: event.args?.path || event.toolName,
        status: "pending",
        payload: event.args || {},
        result: null,
        started_at: Date.now(),
        duration_ms: null,
      },
    });
  });
  pi.on("tool_execution_end", async (event: any) => {
    const result = typeof event.result === "string" ? event.result : messageText({ content: event.result?.content });
    await send({
      id: `${sessionId()}:tool:${event.toolCallId}`,
      ts: Date.now(),
      type: "tool.upserted",
      turn: state.turn || 1,
      payload: {
        tool_call_id: event.toolCallId,
        parent_message_id: state.last_assistant_id,
        name: event.toolName,
        text: (result || event.toolCallId).slice(0, 200),
        status: event.isError ? "failed" : "completed",
        payload: event.args || null,
        result,
        started_at: Date.now(),
        duration_ms: 1,
      },
    });
  });
  pi.on("turn_end", async (event: any) => {
    const turn = (event.turnIndex ?? (state.turn || 1) - 1) + 1;
    const usage = usageFromAssistant(event.message || {});
    await send({ id: `${sessionId()}:turn:${turn}:end`, ts: Date.now(), type: "turn.ended", turn, payload: { usage } });
  });
  pi.on("agent_end", async () => {
    await send({ id: `${sessionId()}:closed`, ts: Date.now(), type: "session.closed", turn: null, payload: {} });
  });
}
