from __future__ import annotations

import os
import socket
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
VENV_DIR = PROJECT_ROOT / ".venv"
REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"
APP_FILE = PROJECT_ROOT / "app.py"
AGENT_DIR = PROJECT_ROOT / "nullzone_agent"
AGENT_ENV = AGENT_DIR / ".env"
AGENT_ENV_EXAMPLE = AGENT_DIR / ".env.example"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000
PREFERRED_NODE_BIN_DIRS = (
    Path("/opt/homebrew/opt/node@22/bin"),
    Path("/usr/local/opt/node@22/bin"),
)
PTY_SMOKE_TEST = textwrap.dedent(
    """
    const pty = require('./node_modules/node-pty');
    const os = require('os');
    try {
      const p = pty.spawn('/bin/zsh', [], {
        name: 'xterm-256color',
        cols: 80,
        rows: 24,
        cwd: os.homedir(),
        env: process.env,
      });
      let done = false;
      p.onData(() => {
        if (done) return;
        done = true;
        p.kill();
        process.stdout.write('PTY_SMOKE_OK\\n');
        process.exit(0);
      });
      p.onExit(() => {
        if (!done) process.exit(1);
      });
      setTimeout(() => {
        if (!done) {
          process.stderr.write('PTY_SMOKE_TIMEOUT\\n');
          process.exit(1);
        }
      }, 2500);
    } catch (err) {
      process.stderr.write(`PTY_SMOKE_ERR ${err.message}\\n`);
      process.exit(1);
    }
    """
).strip()


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def run_command(command: list[str], cwd: Path | None = None) -> None:
    printable = " ".join(command)
    print(f"[crm-nullzone] {printable}")
    subprocess.check_call(command, cwd=str(cwd) if cwd else None)


def use_preferred_node_runtime() -> None:
    current_path = os.environ.get("PATH", "")
    for bin_dir in PREFERRED_NODE_BIN_DIRS:
        if not (bin_dir / "node").exists() or not (bin_dir / "npm").exists():
            continue

        bin_dir_str = str(bin_dir)
        path_parts = [part for part in current_path.split(os.pathsep) if part]
        if bin_dir_str not in path_parts:
            os.environ["PATH"] = f"{bin_dir_str}{os.pathsep}{current_path}" if current_path else bin_dir_str
        print(f"[crm-nullzone] Using Node runtime from {bin_dir_str}")
        return


def run_agent_pty_smoke_test() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", "-e", PTY_SMOKE_TEST],
        cwd=str(AGENT_DIR),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def ensure_agent_pty_runtime() -> None:
    result = run_agent_pty_smoke_test()
    if result.returncode == 0:
        return

    print("[crm-nullzone] node-pty PTY smoke test failed. Rebuilding node-pty from source.")
    run_command(["npm", "rebuild", "node-pty", "--build-from-source"], cwd=AGENT_DIR)

    retry = run_agent_pty_smoke_test()
    if retry.returncode == 0:
        print("[crm-nullzone] node-pty PTY smoke test passed after rebuild.")
        return

    combined_output = "\n".join(
        part.strip()
        for part in [retry.stdout, retry.stderr]
        if part and part.strip()
    )
    print("[crm-nullzone] WARNING: node-pty still cannot open a PTY.")
    if combined_output:
        print(combined_output)


def ensure_virtualenv() -> None:
    python_bin = venv_python()
    created = False
    if not python_bin.exists():
        run_command([sys.executable, "-m", "venv", str(VENV_DIR)])
        created = True

    if created:
        run_command([str(python_bin), "-m", "pip", "install", "--upgrade", "pip"])

    run_command([str(python_bin), "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)])


def ensure_agent_bootstrap() -> None:
    if sys.platform != "darwin":
        print("[crm-nullzone] Nullzone agent bootstrap skipped: only supported on macOS.")
        return

    if AGENT_ENV_EXAMPLE.exists() and not AGENT_ENV.exists():
        shutil.copyfile(AGENT_ENV_EXAMPLE, AGENT_ENV)
        print(
            "[crm-nullzone] Created nullzone_agent/.env from the example file. "
            "Edit PANEL_URL and AGENT_TOKEN before using the support agent."
        )

    if not AGENT_DIR.exists():
        print("[crm-nullzone] nullzone_agent/ folder not found. The CRM will still start.")
        return

    if shutil.which("node") is None or shutil.which("npm") is None:
        print("[crm-nullzone] Node.js 18-24 is required for the bundled Nullzone agent.")
        return

    if not (AGENT_DIR / "node_modules").exists():
        run_command(["npm", "install", "--no-audit", "--no-fund"], cwd=AGENT_DIR)

    ensure_agent_pty_runtime()


def port_is_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return sock.connect_ex((host, port)) != 0


def reserve_open_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def resolve_runtime_port() -> int:
    configured_port = os.environ.get("PORT")
    if configured_port:
        return int(configured_port)

    if port_is_available(DEFAULT_HOST, DEFAULT_PORT):
        return DEFAULT_PORT

    fallback_port = reserve_open_port(DEFAULT_HOST)
    print(
        f"[crm-nullzone] Port {DEFAULT_PORT} is busy. "
        f"Starting the CRM on http://{DEFAULT_HOST}:{fallback_port}"
    )
    return fallback_port


def main() -> None:
    use_preferred_node_runtime()
    ensure_virtualenv()
    ensure_agent_bootstrap()

    python_bin = venv_python()
    os.environ.setdefault("HOST", DEFAULT_HOST)
    os.environ["PORT"] = str(resolve_runtime_port())
    os.execv(str(python_bin), [str(python_bin), str(APP_FILE)])


if __name__ == "__main__":
    main()
