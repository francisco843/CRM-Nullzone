#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# launchd-install.sh — Install the Remote Shell Agent as a macOS LaunchAgent
#
# What this does:
#   1. Detects the full path to a supported `node` binary (prefers Homebrew node@22)
#   2. Generates ~/Library/LaunchAgents/com.remoteshell.agent.plist
#   3. Loads the LaunchAgent so it starts now and on every future login
#
# Requirements:
#   - macOS (Big Sur 11+ recommended)
#   - Node.js 22 LTS recommended
#   - npm install already run inside the agent/ directory
#   - .env file present in the agent/ directory (see .env.example)
#
# Usage:
#   chmod +x launchd-install.sh
#   ./launchd-install.sh
#
# To uninstall:
#   launchctl unload ~/Library/LaunchAgents/com.remoteshell.agent.plist
#   rm ~/Library/LaunchAgents/com.remoteshell.agent.plist
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

PLIST_LABEL="com.remoteshell.agent"
PLIST_PATH="${HOME}/Library/LaunchAgents/${PLIST_LABEL}.plist"
LOG_FILE="/tmp/remoteshell-agent.log"

# ── Resolve agent directory (the directory containing this script) ────────────
AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_JS="${AGENT_DIR}/agent.js"

# ── Sanity checks ─────────────────────────────────────────────────────────────

if [[ "$(uname)" != "Darwin" ]]; then
  echo "ERROR: This script is for macOS only." >&2
  exit 1
fi

if [[ ! -f "${AGENT_JS}" ]]; then
  echo "ERROR: agent.js not found at ${AGENT_JS}" >&2
  exit 1
fi

if [[ ! -f "${AGENT_DIR}/node_modules/.bin/node-pty" ]] && \
   [[ ! -d "${AGENT_DIR}/node_modules/node-pty" ]]; then
  echo "ERROR: Dependencies not installed. Run:  npm install  (inside the agent/ directory)" >&2
  exit 1
fi

if [[ ! -f "${AGENT_DIR}/.env" ]]; then
  echo "ERROR: .env file not found in ${AGENT_DIR}" >&2
  echo "       Copy .env.example to .env and fill in PANEL_URL and AGENT_TOKEN." >&2
  exit 1
fi

# ── Detect node binary ────────────────────────────────────────────────────────
# launchd does not inherit the user's PATH, so we need the absolute path.

NODE_BIN="${NODE_BIN:-}"

if [[ -n "${NODE_BIN}" ]] && [[ ! -x "${NODE_BIN}" ]]; then
  echo "ERROR: NODE_BIN was provided but is not executable: ${NODE_BIN}" >&2
  exit 1
fi

if [[ -n "${NODE_BIN}" ]]; then
  echo "Using NODE_BIN override: ${NODE_BIN}"
fi

# 1. Homebrew node@22 (Apple Silicon)
if [[ -z "${NODE_BIN}" ]] && [[ -x "/opt/homebrew/opt/node@22/bin/node" ]]; then
  NODE_BIN="/opt/homebrew/opt/node@22/bin/node"
fi

# 2. Homebrew node@22 (Intel)
if [[ -z "${NODE_BIN}" ]] && [[ -x "/usr/local/opt/node@22/bin/node" ]]; then
  NODE_BIN="/usr/local/opt/node@22/bin/node"
fi

# 3. Whatever `node` resolves to in the current shell (covers nvm, volta, etc.)
if [[ -z "${NODE_BIN}" ]] && command -v node &>/dev/null; then
  NODE_BIN="$(command -v node)"
fi

# 4. Apple Silicon Homebrew latest
if [[ -z "${NODE_BIN}" ]] && [[ -x "/opt/homebrew/bin/node" ]]; then
  NODE_BIN="/opt/homebrew/bin/node"
fi

# 5. Intel Homebrew latest
if [[ -z "${NODE_BIN}" ]] && [[ -x "/usr/local/bin/node" ]]; then
  NODE_BIN="/usr/local/bin/node"
fi

# 6. nvm default
if [[ -z "${NODE_BIN}" ]] && [[ -x "${HOME}/.nvm/versions/node/$(ls "${HOME}/.nvm/versions/node/" 2>/dev/null | tail -1)/bin/node" ]]; then
  NODE_BIN="${HOME}/.nvm/versions/node/$(ls "${HOME}/.nvm/versions/node/" | tail -1)/bin/node"
fi

if [[ -z "${NODE_BIN}" ]]; then
  echo "ERROR: Cannot find node. Install Node.js (https://nodejs.org) and retry." >&2
  exit 1
fi

NODE_VERSION="$(${NODE_BIN} --version)"
NODE_MAJOR="${NODE_VERSION#v}"
NODE_MAJOR="${NODE_MAJOR%%.*}"

if [[ "${NODE_MAJOR}" -lt 18 || "${NODE_MAJOR}" -ge 25 ]]; then
  echo "ERROR: Unsupported Node.js version for this agent: ${NODE_VERSION}" >&2
  echo "       Supported: >=18 and <25" >&2
  echo "       Recommended: Node 22 LTS." >&2
  echo "       If installed with Homebrew: brew install node@22" >&2
  echo "       Then rerun with:" >&2
  echo "         NODE_BIN=\$(brew --prefix node@22)/bin/node ./launchd-install.sh" >&2
  exit 1
fi

echo "Using node:      ${NODE_BIN}  (${NODE_VERSION})"
echo "Agent directory: ${AGENT_DIR}"
echo "Log file:        ${LOG_FILE}"
echo ""

# ── Unload any existing instance ──────────────────────────────────────────────

if launchctl list "${PLIST_LABEL}" &>/dev/null; then
  echo "Unloading existing LaunchAgent..."
  launchctl unload "${PLIST_PATH}" 2>/dev/null || true
fi

# ── Write plist ───────────────────────────────────────────────────────────────

mkdir -p "${HOME}/Library/LaunchAgents"

cat > "${PLIST_PATH}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <!-- Unique identifier for launchd -->
  <key>Label</key>
  <string>${PLIST_LABEL}</string>

  <!-- Run: node agent.js -->
  <key>ProgramArguments</key>
  <array>
    <string>${NODE_BIN}</string>
    <string>${AGENT_JS}</string>
  </array>

  <!-- Working directory (agent.js loads .env from here) -->
  <key>WorkingDirectory</key>
  <string>${AGENT_DIR}</string>

  <!-- Start immediately when loaded and on every login -->
  <key>RunAtLoad</key>
  <true/>

  <!-- Restart if the process crashes (exits non-zero or via signal).
       SuccessfulExit=false means "don't restart on clean exit (code 0)".
       This lets Ctrl-C / SIGTERM stop the agent without an instant restart. -->
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>

  <!-- Minimum interval between restarts (seconds) to avoid fast crash loops -->
  <key>ThrottleInterval</key>
  <integer>10</integer>

  <!-- Log stdout and stderr to a single file -->
  <key>StandardOutPath</key>
  <string>${LOG_FILE}</string>
  <key>StandardErrorPath</key>
  <string>${LOG_FILE}</string>
</dict>
</plist>
PLIST

echo "Plist written to: ${PLIST_PATH}"

# ── Load the LaunchAgent ──────────────────────────────────────────────────────

launchctl load "${PLIST_PATH}"
echo ""
echo "✓ LaunchAgent installed and started."
echo ""
echo "Useful commands:"
echo "  View live logs:    tail -f ${LOG_FILE}"
echo "  Stop agent:        launchctl unload ${PLIST_PATH}"
echo "  Start agent:       launchctl load   ${PLIST_PATH}"
echo "  Uninstall:         launchctl unload ${PLIST_PATH} && rm ${PLIST_PATH}"
echo ""
echo "The agent will now start automatically on every login."
