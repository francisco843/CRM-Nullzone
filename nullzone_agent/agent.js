#!/usr/bin/env node
/**
 * Remote Shell Agent  v2.1  (macOS only)
 *
 * ██████████████████████████████████████████████████████████████████
 * ██  WARNING: FULL UNRESTRICTED SHELL ACCESS                      ██
 * ██  This agent exposes a real PTY with NO command filtering.     ██
 * ██  ANY command typed in the browser runs on THIS Mac.           ██
 * ██  FOR PERSONAL LAB USE ONLY. Never run on shared or            ██
 * ██  production systems. Keep AGENT_TOKEN secret.                 ██
 * ██████████████████████████████████████████████████████████████████
 *
 * Supported: macOS 11+ (Big Sur and later), Intel and Apple Silicon.
 * Default shell: /bin/zsh  |  Fallback: /bin/bash
 *
 * Usage:
 *   PANEL_URL=https://your-repl.replit.app AGENT_TOKEN=your-token node agent.js
 *   Or create a .env file — see .env.example
 */

"use strict";

const fs   = require("fs");
const path = require("path");
const os   = require("os");
const [NODE_MAJOR] = process.versions.node.split(".").map(Number);

const MIN_NODE_MAJOR = 18;
const MAX_NODE_MAJOR = 24;

// ─── macOS guard ─────────────────────────────────────────────────────────────

if (process.platform !== "darwin") {
  console.error(
    "ERROR: This agent only supports macOS.\n" +
    `       Detected platform: ${process.platform}\n` +
    "       Run the agent on a Mac (Intel or Apple Silicon)."
  );
  process.exit(1);
}

// ─── Optional .env support ───────────────────────────────────────────────────

try {
  require("dotenv").config({ path: path.join(__dirname, ".env") });
} catch {}

// ─── Runtime guard ────────────────────────────────────────────────────────────
//
// node-pty is native code and is sensitive to unsupported Node majors.
// Fail fast with a clear error instead of surfacing a vague posix_spawnp error
// only after the browser starts a shell.

if (!Number.isInteger(NODE_MAJOR) || NODE_MAJOR < MIN_NODE_MAJOR || NODE_MAJOR > MAX_NODE_MAJOR) {
  console.error(
    "ERROR: Unsupported Node.js runtime for this agent.\n" +
    `       Detected: v${process.versions.node}\n` +
    `       Supported: >=${MIN_NODE_MAJOR} and <${MAX_NODE_MAJOR + 1}\n` +
    "       Recommended: Node 22 LTS.\n" +
    "       node-pty fails on this machine with the current Node version."
  );
  process.exit(1);
}

// ─── Required deps ────────────────────────────────────────────────────────────

const WebSocket = (() => {
  try { return require("ws"); }
  catch {
    console.error(
      "ERROR: 'ws' package not found.\n" +
      "Run:  npm install  (inside the agent/ directory)"
    );
    process.exit(1);
  }
})();

const pty = (() => {
  try { return require("node-pty"); }
  catch {
    console.error(
      "ERROR: 'node-pty' package not found.\n" +
      "Run:  npm install  (inside the agent/ directory)\n\n" +
      "If npm install fails with a build error, install Xcode Command Line Tools first:\n" +
      "  xcode-select --install\n" +
      "Then retry:  npm install"
    );
    process.exit(1);
  }
})();

// ─── Configuration ────────────────────────────────────────────────────────────

const PANEL_URL             = process.env.PANEL_URL;
const AGENT_TOKEN           = process.env.AGENT_TOKEN;
const AGENT_ID              = process.env.AGENT_ID || `agent-${os.hostname().replace(/\.local$/, "")}`;
const RECONNECT_DELAY_MS    = Math.max(1000,  parseInt(process.env.RECONNECT_DELAY_MS    || "5000",  10));
const MAX_RECONNECT_DELAY_MS= Math.max(5000,  parseInt(process.env.MAX_RECONNECT_DELAY_MS|| "30000", 10));

function validateConfig() {
  const missing = [];
  if (!PANEL_URL)   missing.push("PANEL_URL");
  if (!AGENT_TOKEN) missing.push("AGENT_TOKEN");
  if (missing.length) {
    console.error("Missing required configuration:", missing.join(", "));
    console.error("Create a .env file from .env.example or export the variables before running.");
    process.exit(1);
  }
}

// ─── Shell resolution (macOS only) ───────────────────────────────────────────
//
// Priority:
//   1. SHELL_OVERRIDE env var  (explicit override in .env)
//   2. /bin/zsh                (macOS default since Catalina 10.15)
//   3. /bin/bash               (always present on macOS)
//
// We do NOT use the SHELL env var from the user session because launchd
// does not inherit login environment variables, so SHELL would be empty
// when the agent runs as a LaunchAgent.

function resolveShell() {
  // Explicit override takes highest priority
  if (process.env.SHELL_OVERRIDE) return process.env.SHELL_OVERRIDE;

  // /bin/zsh — default since Catalina, always present on modern macOS
  if (fs.existsSync("/bin/zsh"))  return "/bin/zsh";

  // /bin/bash — fallback (always present on macOS, though deprecated in newer versions)
  if (fs.existsSync("/bin/bash")) return "/bin/bash";

  // This path should never be reached on macOS, but be safe
  throw new Error("Cannot find /bin/zsh or /bin/bash. Is this really macOS?");
}

// ─── PTY management ───────────────────────────────────────────────────────────

/** @type {import("node-pty").IPty | null} */
let currentPty = null;
let ptyExiting = false; // prevents double exit event on explicit session_end

function spawnPty(ws, cols, rows) {
  if (currentPty) {
    safeSend(ws, { type: "error", message: "A PTY session is already active. End it first." });
    return;
  }

  let shell;
  try { shell = resolveShell(); }
  catch (err) {
    safeSend(ws, { type: "error", message: err.message });
    return;
  }

  ptyExiting = false;
  console.log(`[${ts()}] Spawning PTY  shell=${shell}  size=${cols}x${rows}`);

  let ptyProcess;
  try {
    ptyProcess = pty.spawn(shell, [], {
      name: "xterm-256color",
      cols: Math.max(1, cols),
      rows: Math.max(1, rows),
      cwd:  os.homedir(),
      env:  process.env,
    });
  } catch (err) {
    console.error(`[${ts()}] Failed to spawn PTY: ${err.message}`);
    safeSend(ws, { type: "error", message: `Failed to spawn shell (${shell}): ${err.message}` });
    return;
  }

  currentPty = ptyProcess;

  ptyProcess.onData((data) => {
    safeSend(ws, { type: "data", data });
  });

  ptyProcess.onExit(({ exitCode, signal }) => {
    console.log(`[${ts()}] PTY exited  code=${exitCode}  signal=${signal}`);
    currentPty = null;
    if (!ptyExiting) {
      // User typed `exit` or shell exited on its own
      safeSend(ws, { type: "exit", code: exitCode ?? 0 });
    }
  });

  safeSend(ws, { type: "session_started" });
  console.log(`[${ts()}] PTY session started  (${shell})`);
}

function killPty(ws) {
  if (currentPty) {
    ptyExiting = true;
    try { currentPty.kill(); } catch {}
    currentPty = null;
    if (ws) safeSend(ws, { type: "exit", code: 0 });
    console.log(`[${ts()}] PTY session terminated by request`);
  }
}

// ─── WebSocket client ─────────────────────────────────────────────────────────

let ws             = null;
let reconnectDelay = RECONNECT_DELAY_MS;
let isShuttingDown = false;

function buildWsUrl() {
  const base   = PANEL_URL.replace(/\/$/, "");
  const wsBase = base.replace(/^https?:\/\//, (m) => m === "https://" ? "wss://" : "ws://");
  return (
    `${wsBase}/api/ws/agent` +
    `?token=${encodeURIComponent(AGENT_TOKEN)}` +
    `&agentId=${encodeURIComponent(AGENT_ID)}`
  );
}

function buildWsOrigin() {
  const base = PANEL_URL.replace(/\/$/, "");
  try {
    return new URL(base).origin;
  } catch {
    return base;
  }
}

function connect() {
  if (isShuttingDown) return;

  console.log(`[${ts()}] Connecting to backend...`);
  ws = new WebSocket(buildWsUrl(), {
    handshakeTimeout: 10_000,
    headers: { Origin: buildWsOrigin() },
  });

  ws.on("open", () => {
    console.log(`[${ts()}] Connected  (agentId: ${AGENT_ID})`);
    reconnectDelay = RECONNECT_DELAY_MS; // reset backoff on successful connect
    safeSend(ws, {
      type:     "hello",
      agentId:  AGENT_ID,
      platform: "darwin",
      arch:     process.arch,           // "x64" (Intel) or "arm64" (Apple Silicon)
      shell:    resolveShell(),
    });
  });

  ws.on("message", (raw) => {
    let msg;
    try { msg = JSON.parse(raw.toString()); }
    catch { return; }

    switch (msg.type) {
      case "session_start":
        spawnPty(ws, msg.cols ?? 80, msg.rows ?? 24);
        break;

      case "data":
        if (currentPty && typeof msg.data === "string") {
          currentPty.write(msg.data);
        }
        break;

      case "resize":
        if (currentPty && typeof msg.cols === "number" && typeof msg.rows === "number") {
          try { currentPty.resize(Math.max(1, msg.cols), Math.max(1, msg.rows)); } catch {}
        }
        break;

      case "session_end":
        console.log(`[${ts()}] Session end requested by browser`);
        killPty(ws);
        break;
    }
  });

  ws.on("close", (code, reason) => {
    console.log(`[${ts()}] Disconnected  code=${code}  reason=${String(reason) || "(none)"}`);
    killPty(null); // kill PTY silently on disconnect
    if (!isShuttingDown) scheduleReconnect();
  });

  ws.on("error", (err) => {
    // 'error' is always followed by 'close'; reconnect is handled there
    console.error(`[${ts()}] WS error: ${err.message}`);
  });
}

function safeSend(ws, msg) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    try { ws.send(JSON.stringify(msg)); } catch {}
  }
}

function scheduleReconnect() {
  console.log(`[${ts()}] Reconnecting in ${(reconnectDelay / 1000).toFixed(1)}s ...`);
  setTimeout(() => {
    reconnectDelay = Math.min(reconnectDelay * 1.5, MAX_RECONNECT_DELAY_MS);
    connect();
  }, reconnectDelay);
}

function ts() { return new Date().toISOString(); }

// ─── Graceful shutdown ────────────────────────────────────────────────────────

function shutdown(sig) {
  isShuttingDown = true;
  console.log(`\n[${ts()}] Received ${sig} — shutting down.`);
  killPty(ws);
  if (ws) ws.close(1000, "Agent shutting down");
  process.exit(0);
}

process.on("SIGINT",  () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));

// ─── Entry point ──────────────────────────────────────────────────────────────

console.log("══════════════════════════════════════════════════════════");
console.log("  Remote Shell Agent  v2.1  [macOS]");
console.log("  !!!  FULL UNRESTRICTED SHELL ACCESS  !!!");
console.log("  FOR PERSONAL LAB USE ONLY");
console.log("  Any command run in the browser panel executes here.");
console.log("══════════════════════════════════════════════════════════");

validateConfig();
connect();
