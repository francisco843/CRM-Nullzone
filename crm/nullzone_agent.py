from __future__ import annotations

import atexit
import os
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from flask import Flask


REQUIRED_ENV_KEYS = ("PANEL_URL", "AGENT_TOKEN")

_PROCESS_LOCK = threading.Lock()
_MANAGED_PROCESS: subprocess.Popen[str] | None = None
_MANAGED_LOG_HANDLE: Any | None = None
_MANAGED_PID_PATH: Path | None = None
_MANAGED_PID: int | None = None
_ATEXIT_REGISTERED = False


def setup_nullzone_agent(app: Flask) -> dict[str, Any]:
    agent_dir = Path(app.config["NULLZONE_AGENT_DIR"])
    env_path = Path(app.config["NULLZONE_AGENT_ENV_PATH"])
    log_path = Path(app.config["NULLZONE_AGENT_LOG_PATH"])
    pid_path = Path(app.config["NULLZONE_AGENT_PID_PATH"])

    details = [
        detail("Folder", display_path(agent_dir, app)),
        detail("Config", display_path(env_path, app)),
        detail("Log", display_path(log_path, app)),
    ]

    if not app.config.get("NULLZONE_AGENT_ENABLED", True):
        return agent_status(
            "disabled",
            "Disabled",
            "Nullzone IT Support Agent integration is turned off.",
            details,
        )

    if platform.system() != "Darwin":
        return agent_status(
            "warning",
            "macOS only",
            "The bundled Nullzone agent only supports macOS, so the CRM skipped startup.",
            details,
            hint="Run this CRM on a Mac to use the integrated support agent.",
        )

    if not agent_dir.exists():
        return agent_status(
            "error",
            "Agent folder missing",
            "The CRM could not find the bundled Nullzone agent files.",
            details,
            hint="Restore the `nullzone_agent/` folder and restart the CRM.",
        )

    running_pid = current_running_pid(pid_path)
    if running_pid:
        details.append(detail("PID", str(running_pid)))
        return agent_status(
            "running",
            "Running",
            "Nullzone IT Support Agent is already running.",
            details,
        )

    if not app.config.get("NULLZONE_AGENT_AUTO_START", True):
        return agent_status(
            "disabled",
            "Auto-start off",
            "The integrated agent is configured but automatic startup is disabled.",
            details,
            hint="Set `NULLZONE_AGENT_AUTO_START=True` to launch it with the CRM.",
        )

    env_data = read_env_file(env_path)
    missing_keys = [key for key in REQUIRED_ENV_KEYS if not env_data.get(key)]
    if missing_keys:
        return agent_status(
            "warning",
            "Configuration needed",
            f"Missing required values: {', '.join(missing_keys)}.",
            details,
            hint="Edit `nullzone_agent/.env` with a valid PANEL_URL and AGENT_TOKEN.",
        )

    placeholder_token = env_data.get("AGENT_TOKEN", "").strip().lower()
    if placeholder_token in {"replace-me", "changeme", "your-token"}:
        return agent_status(
            "warning",
            "Configuration needed",
            "AGENT_TOKEN still uses the placeholder value from `.env.example`.",
            details,
            hint="Replace the example AGENT_TOKEN in `nullzone_agent/.env` before starting the integrated agent.",
        )

    node_binary = shutil.which("node")
    if not node_binary:
        return agent_status(
            "error",
            "Node.js missing",
            "The CRM could not find `node` in PATH, so the agent could not start.",
            details,
            hint="Install Node.js 18-24 on this Mac and restart the CRM.",
        )

    dependencies_result = ensure_node_dependencies(
        agent_dir=agent_dir,
        auto_install=bool(app.config.get("NULLZONE_AGENT_AUTO_INSTALL", True)),
        timeout=int(app.config.get("NULLZONE_AGENT_INSTALL_TIMEOUT", 300)),
    )
    if dependencies_result["status"] == "error":
        return agent_status(
            "error",
            "Dependency install failed",
            dependencies_result["message"],
            details,
            hint="Review the npm error and retry the CRM launcher.",
            log_excerpt=dependencies_result.get("log_excerpt"),
        )

    if dependencies_result["message"]:
        details.append(detail("Dependencies", dependencies_result["message"]))

    startup_result = start_agent_process(
        app=app,
        agent_dir=agent_dir,
        env_path=env_path,
        log_path=log_path,
        pid_path=pid_path,
        node_binary=node_binary,
        env_data=env_data,
    )
    startup_result["details"] = details + startup_result.get("details", [])
    return startup_result


def detail(label: str, value: str) -> dict[str, str]:
    return {"label": label, "value": value}


def display_path(path: Path, app: Flask) -> str:
    project_root = Path(app.config["PROJECT_ROOT"])
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


def agent_status(
    state: str,
    label: str,
    message: str,
    details: list[dict[str, str]] | None = None,
    *,
    hint: str | None = None,
    log_excerpt: str | None = None,
) -> dict[str, Any]:
    return {
        "state": state,
        "label": label,
        "message": message,
        "details": details or [],
        "hint": hint,
        "log_excerpt": log_excerpt,
    }


def read_env_file(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def ensure_node_dependencies(agent_dir: Path, auto_install: bool, timeout: int) -> dict[str, str | None]:
    if (agent_dir / "node_modules").exists():
        return {"status": "ok", "message": None, "log_excerpt": None}

    if not auto_install:
        return {
            "status": "error",
            "message": "The `nullzone_agent/node_modules/` folder is missing and auto-install is disabled.",
            "log_excerpt": None,
        }

    npm_binary = shutil.which("npm")
    if not npm_binary:
        return {
            "status": "error",
            "message": "The CRM could not find `npm` in PATH to install the bundled agent dependencies.",
            "log_excerpt": None,
        }

    try:
        result = subprocess.run(
            [npm_binary, "install", "--no-audit", "--no-fund"],
            cwd=agent_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "message": "The automatic `npm install` timed out while preparing the bundled agent.",
            "log_excerpt": None,
        }

    if result.returncode != 0:
        combined_output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
        return {
            "status": "error",
            "message": "Automatic `npm install` failed for the bundled Nullzone agent.",
            "log_excerpt": trim_output(combined_output),
        }

    return {
        "status": "ok",
        "message": "Installed Node dependencies automatically.",
        "log_excerpt": None,
    }


def start_agent_process(
    *,
    app: Flask,
    agent_dir: Path,
    env_path: Path,
    log_path: Path,
    pid_path: Path,
    node_binary: str,
    env_data: dict[str, str],
) -> dict[str, Any]:
    global _ATEXIT_REGISTERED
    global _MANAGED_LOG_HANDLE
    global _MANAGED_PID
    global _MANAGED_PID_PATH
    global _MANAGED_PROCESS

    with _PROCESS_LOCK:
        existing_pid = current_running_pid(pid_path)
        if existing_pid:
            return agent_status(
                "running",
                "Running",
                "Nullzone IT Support Agent is already running.",
                [detail("PID", str(existing_pid))],
            )

        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(log_path, "a", encoding="utf-8")
        log_handle.write(f"\n[{timestamp()}] Starting Nullzone IT Support Agent from CRM.\n")
        log_handle.flush()

        process_env = os.environ.copy()
        process_env.update(env_data)
        process_env["NULLZONE_AGENT_CONFIG_PATH"] = str(env_path)

        process = subprocess.Popen(
            [node_binary, "agent.js"],
            cwd=agent_dir,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            env=process_env,
        )

        time.sleep(1.0)
        if process.poll() is not None:
            log_handle.write(f"[{timestamp()}] Agent exited during startup.\n")
            log_handle.flush()
            log_handle.close()
            return agent_status(
                "error",
                "Startup failed",
                "The bundled Nullzone agent exited immediately after launch.",
                [detail("Exit code", str(process.returncode or 0))],
                hint="Inspect the agent log and verify Node.js plus `.env` values.",
                log_excerpt=read_log_tail(log_path),
            )

        _MANAGED_PROCESS = process
        _MANAGED_LOG_HANDLE = log_handle
        _MANAGED_PID_PATH = pid_path
        _MANAGED_PID = process.pid
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(process.pid), encoding="utf-8")

        if not _ATEXIT_REGISTERED:
            atexit.register(stop_managed_agent)
            _ATEXIT_REGISTERED = True

    app.logger.info("Nullzone IT Support Agent started with PID %s", process.pid)
    return agent_status(
        "running",
        "Running",
        "Nullzone IT Support Agent started automatically with the CRM.",
        [detail("PID", str(process.pid))],
    )


def stop_managed_agent() -> None:
    global _MANAGED_LOG_HANDLE
    global _MANAGED_PID
    global _MANAGED_PID_PATH
    global _MANAGED_PROCESS

    with _PROCESS_LOCK:
        process = _MANAGED_PROCESS
        pid_path = _MANAGED_PID_PATH
        managed_pid = _MANAGED_PID

        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

        if pid_path and managed_pid and pid_path.exists():
            try:
                recorded_pid = int(pid_path.read_text(encoding="utf-8").strip())
            except ValueError:
                recorded_pid = None
            if recorded_pid == managed_pid:
                pid_path.unlink(missing_ok=True)

        if _MANAGED_LOG_HANDLE:
            _MANAGED_LOG_HANDLE.close()

        _MANAGED_PROCESS = None
        _MANAGED_LOG_HANDLE = None
        _MANAGED_PID_PATH = None
        _MANAGED_PID = None


def current_running_pid(pid_path: Path) -> int | None:
    if _MANAGED_PROCESS and _MANAGED_PROCESS.poll() is None:
        return _MANAGED_PROCESS.pid

    if not pid_path.exists():
        return None

    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except ValueError:
        pid_path.unlink(missing_ok=True)
        return None

    if process_is_alive(pid):
        return pid

    pid_path.unlink(missing_ok=True)
    return None


def process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_log_tail(log_path: Path, limit: int = 12) -> str | None:
    if not log_path.exists():
        return None
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        return None
    return "\n".join(lines[-limit:])


def trim_output(output: str | None, limit: int = 1200) -> str | None:
    if not output:
        return None
    if len(output) <= limit:
        return output
    return output[-limit:]


def timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")
