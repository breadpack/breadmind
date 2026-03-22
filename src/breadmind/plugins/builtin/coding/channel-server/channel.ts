#!/usr/bin/env bun
/**
 * BreadMind Channel MCP Server for Claude Code.
 *
 * Bridges Claude Code sessions with BreadMind's ChannelSupervisor.
 * - Claude Code → BreadMind: forwards channel notifications via HTTP POST
 * - BreadMind → Claude Code: receives replies via HTTP and sends them through the reply tool
 *
 * Environment variables:
 *   BREADMIND_SUPERVISOR_PORT - HTTP port where ChannelSupervisor listens (required)
 *   CHANNEL_PORT              - HTTP port for receiving replies from BreadMind (default: 18901)
 *   SESSION_ID                - Unique session identifier (required)
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const SUPERVISOR_PORT = parseInt(process.env.BREADMIND_SUPERVISOR_PORT || "0");
const CHANNEL_PORT = parseInt(process.env.CHANNEL_PORT || "18901");
const SESSION_ID = process.env.SESSION_ID || "unknown";

if (!SUPERVISOR_PORT) {
  console.error("BREADMIND_SUPERVISOR_PORT is required");
  process.exit(1);
}

const SUPERVISOR_URL = `http://127.0.0.1:${SUPERVISOR_PORT}`;

// Pending replies from BreadMind — keyed by a simple incrementing ID
let pendingReplies: Map<string, (text: string) => void> = new Map();

// ── MCP Server ──────────────────────────────────────────────────────────

const mcp = new Server(
  { name: "breadmind-channel", version: "0.1.0" },
  {
    capabilities: {
      experimental: { "claude/channel": {} },
      tools: {},
    },
    instructions: `You are supervised by BreadMind, an AI infrastructure agent.
Report progress at these specific points by sending a channel notification:

1. AFTER creating or modifying files: list filenames and brief description
2. AFTER running tests: report pass/fail count with failure details
3. WHEN you need approval for a risky action (deleting files, changing configs): describe what and why
4. WHEN you are unsure about implementation direction: describe your options
5. WHEN work is complete: provide a summary of everything done

Format each report as JSON:
{"event_type": "files_changed"|"test_result"|"approval_needed"|"direction_check"|"completed"|"error", "details": "...", "files_changed": [...], "error": "..."}

BreadMind will reply with instructions through the breadmind_reply tool. Follow those instructions.
Do NOT wait for a reply on routine progress reports — keep working. Only pause when event_type is "approval_needed" or "direction_check".`,
  }
);

// ── Reply Tool (BreadMind → Claude Code) ────────────────────────────────

mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "breadmind_reply",
      description:
        "Receive instructions from BreadMind supervisor. This tool is called when BreadMind sends a reply to a previous event.",
      inputSchema: {
        type: "object",
        properties: {
          session_id: {
            type: "string",
            description: "Session identifier",
          },
          text: {
            type: "string",
            description: "Reply message from BreadMind",
          },
        },
        required: ["session_id", "text"],
      },
    },
  ],
}));

mcp.setRequestHandler(CallToolRequestSchema, async (req) => {
  if (req.params.name === "breadmind_reply") {
    const { text } = req.params.arguments as {
      session_id: string;
      text: string;
    };
    return { content: [{ type: "text", text: `[BreadMind] ${text}` }] };
  }
  throw new Error(`unknown tool: ${req.params.name}`);
});

// ── Notification Forwarding (Claude Code → BreadMind) ───────────────────

// Override the notification method to intercept channel events
const origNotification = mcp.notification.bind(mcp);

// Listen for tool calls from Claude Code that contain progress info
// The actual forwarding happens when Claude Code sends channel notifications

// ── HTTP Server (receives replies from BreadMind supervisor) ────────────

Bun.serve({
  port: CHANNEL_PORT,
  hostname: "127.0.0.1",
  async fetch(req) {
    const url = new URL(req.url);

    if (req.method === "POST" && url.pathname === "/reply") {
      // BreadMind sends a reply → push into Claude Code session
      const body = await req.json();
      const { message } = body as { message: string };

      await mcp.notification({
        method: "notifications/claude/channel",
        params: {
          content: `[BreadMind Supervisor] ${message}`,
          meta: { source: "breadmind", session_id: SESSION_ID },
        },
      });

      return new Response(JSON.stringify({ ok: true }), {
        headers: { "Content-Type": "application/json" },
      });
    }

    if (req.method === "GET" && url.pathname === "/health") {
      return new Response(JSON.stringify({ status: "ok", session_id: SESSION_ID }), {
        headers: { "Content-Type": "application/json" },
      });
    }

    return new Response("not found", { status: 404 });
  },
});

// ── Connect to Claude Code ──────────────────────────────────────────────

const transport = new StdioServerTransport();
await mcp.connect(transport);

// Notify supervisor that channel is ready
try {
  await fetch(`${SUPERVISOR_URL}/channel-ready`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: SESSION_ID, channel_port: CHANNEL_PORT }),
  });
} catch {
  // Supervisor may not be ready yet — non-fatal
}

// ── Forward Claude Code tool results as events to supervisor ────────────
// Claude Code doesn't send channel notifications itself — we intercept
// by watching for the patterns in the instructions we gave it.
// The actual mechanism is: Claude will write to stdout in JSON format
// and the MCP SDK handles the protocol. We hook into the notification
// emission to forward to supervisor.

const origEmit = mcp.notification.bind(mcp);
mcp.notification = async (notification: any) => {
  // Forward channel notifications to BreadMind supervisor
  if (notification.method === "notifications/claude/channel") {
    try {
      await fetch(`${SUPERVISOR_URL}/event`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: SESSION_ID,
          content: notification.params?.content || "",
          meta: notification.params?.meta || {},
          timestamp: new Date().toISOString(),
        }),
      });
    } catch {
      // Non-fatal: supervisor may be busy
    }
  }
  return origEmit(notification);
};

console.error(`[breadmind-channel] Ready on port ${CHANNEL_PORT}, supervisor at ${SUPERVISOR_URL}`);
