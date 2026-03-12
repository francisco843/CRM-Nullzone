from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from flask import Flask

from .addons import run_addons
from .db import init_db
from .nullzone_agent import setup_nullzone_agent
from .routes import register_routes


def format_currency(value: float | int | None) -> str:
    amount = float(value or 0)
    return f"${amount:,.2f}"


def format_datetime(value: str | None) -> str:
    if not value:
        return "No date"
    normalized = value.replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(normalized, fmt)
            if fmt == "%Y-%m-%d":
                return parsed.strftime("%d %b %Y")
            return parsed.strftime("%d %b %Y · %H:%M")
        except ValueError:
            continue
    return value


def slugify(value: str | None) -> str:
    if not value:
        return ""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)

    project_root = Path(__file__).resolve().parent.parent

    app.config.from_mapping(
        APP_NAME="CRM Nullzone",
        PROJECT_ROOT=str(project_root),
        RUN_STARTUP_SCRIPTS=True,
        ADDON_STANDALONE_TIMEOUT=30,
        SECRET_KEY="crm-github-local-secret",
        NULLZONE_AGENT_ENABLED=True,
        NULLZONE_AGENT_AUTO_START=True,
        NULLZONE_AGENT_AUTO_INSTALL=True,
        NULLZONE_AGENT_INSTALL_TIMEOUT=300,
    )

    if test_config:
        app.config.update(test_config)

    project_root = Path(app.config["PROJECT_ROOT"])
    database_path = Path(app.config.get("DATABASE") or (project_root / "instance" / "crm.sqlite3"))
    app.config["DATABASE"] = str(database_path)
    app.config["NULLZONE_AGENT_DIR"] = app.config.get("NULLZONE_AGENT_DIR") or str(project_root / "nullzone_agent")
    app.config["NULLZONE_AGENT_ENV_PATH"] = app.config.get("NULLZONE_AGENT_ENV_PATH") or str(
        Path(app.config["NULLZONE_AGENT_DIR"]) / ".env"
    )
    app.config["NULLZONE_AGENT_LOG_PATH"] = app.config.get("NULLZONE_AGENT_LOG_PATH") or str(
        project_root / "instance" / "nullzone_agent.log"
    )
    app.config["NULLZONE_AGENT_PID_PATH"] = app.config.get("NULLZONE_AGENT_PID_PATH") or str(
        project_root / "instance" / "nullzone_agent.pid"
    )

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    init_db(app.config["DATABASE"])

    app.add_template_filter(format_currency, "currency")
    app.add_template_filter(format_datetime, "datetime")
    app.add_template_filter(slugify, "slugify")

    @app.context_processor
    def inject_globals() -> dict[str, object]:
        return {
            "app_name": app.config["APP_NAME"],
            "current_year": datetime.now().year,
        }

    register_routes(app)
    app.config["ADDON_RESULTS"] = (
        run_addons(app) if app.config.get("RUN_STARTUP_SCRIPTS", True) else []
    )
    app.config["NULLZONE_AGENT_STATUS"] = setup_nullzone_agent(app)

    return app
