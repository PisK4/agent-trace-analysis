import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { ATA_CONFIG } from "./config";

const ATA_URL = process.env.ATA_URL || ATA_CONFIG.endpoint;
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

const LINEAGE_ENV_KEYS = [
  "PI_SUBAGENT_CHILD",
  "PI_SUBAGENT_ORCHESTRATOR_SESSION_ID",
  "PI_SUBAGENT_RUN_ID",
  "PI_SUBAGENT_PARENT_ROOT_RUN_ID",
  "PI_SUBAGENT_PARENT_RUN_ID",
  "PI_SUBAGENT_CHILD_AGENT",
  "PI_SUBAGENT_PARENT_DEPTH",
  "PI_SUBAGENT_PARENT_PATH",
] as const;

function lineageFromEnv(): Record<string, string> | undefined {
  const out: Record<string, string> = {};
  for (const k of LINEAGE_ENV_KEYS) {
    const v = process.env[k];
    if (v) out[k] = v;
  }
  return Object.keys(out).length ? out : undefined;
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
        agent_id: ATA_CONFIG.agentId,
        host: ATA_CONFIG.host,
        runtime: ATA_CONFIG.runtime,
        channel: process.env.ATA_CHANNEL || undefined,
        lineage: lineageFromEnv(),
        event: jsonSafe(event),
      });
    });
  }
}
