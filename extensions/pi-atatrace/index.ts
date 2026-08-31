import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { ATA_CONFIG } from "./config";

const ATA_URL = process.env.ATA_URL || ATA_CONFIG.endpoint;
// 只在真实 agent_start 建立生命周期；before_agent_start 不能提前制造 ID。
const lifecycleIds = new Map<string, string>();
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

// before_agent_start 的 toolSnippets 只有名字+单行描述；参数 schema 只能从
// ExtensionAPI 取（getAllTools/getActiveTools，锚定 b1efcf7 / v0.84.2）。
function toolsSnapshot(pi: ExtensionAPI): unknown {
  try {
    return { tools: pi.getAllTools?.() ?? [], active: pi.getActiveTools?.() ?? [] };
  } catch {
    return undefined;
  }
}

export default function (pi: ExtensionAPI) {
  for (const name of HOOKS) {
    pi.on(name, async (event, ctx) => {
      const session_id = ctx.sessionManager.getSessionId();
      const title = ctx.sessionManager.getSessionName?.() || session_id;
      let external_lifecycle_id: string | undefined;
      if (name === "agent_start") {
        // 只有真实生命周期开始才生成 ID；before_agent_start 不能提前占位。
        external_lifecycle_id = crypto.randomUUID();
        lifecycleIds.set(session_id, external_lifecycle_id);
      } else if (name !== "before_agent_start") {
        external_lifecycle_id = lifecycleIds.get(session_id);
      }
      // 推送失败只影响观测，不得阻塞宿主 hook 的生命周期。
      void postHook({
        name,
        session_id,
        title,
        agent_id: ATA_CONFIG.agentId,
        host: ATA_CONFIG.host,
        runtime: ATA_CONFIG.runtime,
        channel: process.env.ATA_CHANNEL || undefined,
        lineage: lineageFromEnv(),
        ...(external_lifecycle_id ? { external_lifecycle_id } : {}),
        event: jsonSafe(name === "before_agent_start" ? { ...event, toolsFull: toolsSnapshot(pi) } : event),
      });
      if (name === "agent_end" && external_lifecycle_id === lifecycleIds.get(session_id)) {
        lifecycleIds.delete(session_id);
      }
    });
  }
}
