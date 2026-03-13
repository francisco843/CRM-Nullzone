#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path.home() / "Downloads" / "TerminalBridge"
QUEUE_DIR = ROOT / "queue"
RESULTS_DIR = ROOT / "results"
STATE_FILE = ROOT / "state.json"
STOP_FILE = ROOT / "STOP"
POLL_SECONDS = 1.0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_layout() -> None:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def write_state(status: str, extra: dict | None = None) -> None:
    payload = {
        "status": status,
        "updated_at": now_iso(),
        "pid": os.getpid(),
        "cwd": os.getcwd(),
    }
    if extra:
        payload.update(extra)
    STATE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def handle_signal(signum, _frame) -> None:
    write_state("stopped", {"signal": signum})
    raise SystemExit(0)


def run_request(path: Path) -> None:
    request = json.loads(path.read_text(encoding="utf-8"))
    command = request["command"]
    cwd = request.get("cwd") or str(Path.home())
    timeout = int(request.get("timeout_seconds", 120))

    started_at = now_iso()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=os.environ.copy(),
            check=False,
        )
        result = {
            "id": request.get("id", path.stem),
            "command": command,
            "cwd": cwd,
            "started_at": started_at,
            "finished_at": now_iso(),
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    except Exception as exc:
        result = {
            "id": request.get("id", path.stem),
            "command": command,
            "cwd": cwd,
            "started_at": started_at,
            "finished_at": now_iso(),
            "returncode": -1,
            "stdout": "",
            "stderr": repr(exc),
        }

    result_path = RESULTS_DIR / f"{path.stem}.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    path.unlink(missing_ok=True)
    write_state("idle", {"last_request": request.get("id", path.stem)})


def main() -> None:
    ensure_layout()
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    write_state("idle")

    while True:
        if STOP_FILE.exists():
            write_state("stopped", {"reason": "stop file present"})
            break

        queued = sorted(QUEUE_DIR.glob("*.json"))
        if queued:
            write_state("busy", {"current_request": queued[0].stem})
            run_request(queued[0])
        else:
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
