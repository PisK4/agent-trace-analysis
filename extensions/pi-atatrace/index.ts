import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const ATA_URL = process.env.ATA_URL || "http://127.0.0.1:8787";
const HOOKS = [
  "before_agent_start",
  "agent_start",
  "turn_start",
  "message_start",
  "message_end",
  "tool_execution_start",
  "tool_execution_end",
  "turn_end",
  "agent_end",
] as const;

function jsonSafe(value: unknown): unknown {
  try {
    return JSON.parse(JSON.stringify(value));
  } catch {
    return {};
  }
}

async function postHook(body: object): Promise<void> {
  try {
    await fetch(`${ATA_URL}/api/pi-hooks`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    // ATA down: skip. Next hook retries independently.
  }
}

export default function (pi: ExtensionAPI) {
  for (const name of HOOKS) {
    pi.on(name, async (event, ctx) => {
      const session_id = ctx.sessionManager.getSessionId();
      const title = ctx.sessionManager.getSessionName?.() || session_id;
      await postHook({
        name,
        session_id,
        title,
        event: jsonSafe(event),
      });
    });
  }
}
