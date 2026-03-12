from __future__ import annotations

import inspect
import os
import re
import runpy
import subprocess
import sys
import traceback
from pathlib import Path
from time import perf_counter

from flask import Flask

from . import db


MAIN_GUARD_PATTERN = re.compile(r"""if\s+__name__\s*==\s*["']__main__["']\s*:""")


def read_script_text(script_path: Path) -> str:
    try:
        return script_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return script_path.read_text(encoding="latin-1")


def has_main_guard(script_path: Path) -> bool:
    return bool(MAIN_GUARD_PATTERN.search(read_script_text(script_path)))


def run_standalone_script(app: Flask, script_path: Path) -> tuple[str, str]:
    timeout = app.config.get("ADDON_STANDALONE_TIMEOUT")
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=app.config["PROJECT_ROOT"],
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "error", f"Script exceeded the startup timeout of {timeout} seconds."

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    if result.returncode == 0:
        detail = stdout or "Executed as a standalone Python script."
        return "ok", detail

    detail = stderr or stdout or f"Script exited with code {result.returncode}."
    return "error", detail


def call_entrypoint(entrypoint: object, context: dict[str, object]) -> None:
    if not callable(entrypoint):
        return

    signature = inspect.signature(entrypoint)
    parameters = list(signature.parameters.values())

    if not parameters:
        entrypoint()
        return

    first = parameters[0]
    if first.kind in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.VAR_POSITIONAL,
    ):
        entrypoint(context)
        return

    if first.kind == inspect.Parameter.KEYWORD_ONLY:
        entrypoint(context=context)
        return

    entrypoint()


def build_context(app: Flask) -> dict[str, object]:
    database_path = app.config["DATABASE"]

    def log(message: str) -> None:
        app.logger.info("[addon] %s", message)

    return {
        "app": app,
        "project_root": Path(app.config["PROJECT_ROOT"]),
        "db_path": Path(database_path),
        "query_all": lambda sql, params=(): db.query_all(database_path, sql, params),
        "query_one": lambda sql, params=(): db.query_one(database_path, sql, params),
        "execute": lambda sql, params=(): db.execute(database_path, sql, params),
        "executemany": lambda sql, rows: db.executemany(database_path, sql, rows),
        "get_setting": lambda key, default=None: db.get_setting(database_path, key, default),
        "set_setting": lambda key, value: db.set_setting(database_path, key, value),
        "register_activity": lambda entity_type, entity_id, action, summary: db.register_activity(
            database_path,
            entity_type,
            entity_id,
            action,
            summary,
        ),
        "log": log,
    }


def run_addons(app: Flask) -> list[dict[str, object]]:
    scripts_dir = Path(app.config["PROJECT_ROOT"]) / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, object]] = []
    context = build_context(app)

    for script_path in sorted(scripts_dir.glob("*.py")):
        started_at = perf_counter()
        try:
            execute_as_main = has_main_guard(script_path)
            if execute_as_main:
                status, message = run_standalone_script(app, script_path)
            else:
                namespace = runpy.run_path(
                    str(script_path),
                    init_globals={"context": context},
                )
                entrypoint = namespace.get("run") or namespace.get("main")
                if callable(entrypoint):
                    call_entrypoint(entrypoint, context)
                message = "Executed successfully."
                status = "ok"

            results.append(
                {
                    "name": script_path.name,
                    "status": status,
                    "message": message,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                }
            )
        except BaseException as exc:  # pragma: no cover - defensive logging path
            if isinstance(exc, KeyboardInterrupt):
                raise
            app.logger.error("Failed to execute addon %s\n%s", script_path.name, traceback.format_exc())
            results.append(
                {
                    "name": script_path.name,
                    "status": "error",
                    "message": str(exc),
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                }
            )

    return results
