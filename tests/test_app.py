from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from crm import create_app
from crm import db


class CRMAppTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.sqlite3"
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(self.database_path),
                "RUN_STARTUP_SCRIPTS": False,
                "NULLZONE_AGENT_ENABLED": False,
                "SECRET_KEY": "test-secret",
            }
        )
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_dashboard_loads(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Dashboard", response.data)

    def test_create_company_contact_and_deal(self) -> None:
        company_response = self.client.post(
            "/companies/new",
            data={
                "name": "Acme Labs",
                "industry": "Software",
                "city": "Austin",
                "country": "USA",
            },
            follow_redirects=True,
        )
        self.assertEqual(company_response.status_code, 200)
        self.assertIn(b"Company created", company_response.data)

        contact_response = self.client.post(
            "/contacts/new",
            data={
                "first_name": "Laura",
                "last_name": "Perez",
                "email": "laura@acme.test",
                "status": "Lead",
                "company_id": "1",
            },
            follow_redirects=True,
        )
        self.assertEqual(contact_response.status_code, 200)
        self.assertIn(b"Contact created", contact_response.data)

        deal_response = self.client.post(
            "/deals/new",
            data={
                "title": "Licencia anual",
                "company_id": "1",
                "contact_id": "1",
                "stage": "Proposal",
                "value": "3200",
            },
            follow_redirects=True,
        )
        self.assertEqual(deal_response.status_code, 200)
        self.assertIn(b"Deal created", deal_response.data)

    def test_startup_runner_executes_context_and_main_guard_scripts(self) -> None:
        project_root = Path(self.temp_dir.name)
        scripts_dir = project_root / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        marker_file = project_root / "guarded-script-ran.txt"

        (scripts_dir / "01_plain_main.py").write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "",
                    "def main():",
                    "    context['set_setting']('plain_main_ran', '1')",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        (scripts_dir / "02_main_guard.py").write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "from pathlib import Path",
                    "",
                    "def main():",
                    f"    Path({str(marker_file)!r}).write_text('ran', encoding='utf-8')",
                    "",
                    "if __name__ == '__main__':",
                    "    main()",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(self.database_path),
                "PROJECT_ROOT": str(project_root),
                "RUN_STARTUP_SCRIPTS": True,
                "NULLZONE_AGENT_ENABLED": False,
                "SECRET_KEY": "test-secret",
            }
        )

        self.assertIsNotNone(app)
        self.assertEqual(db.get_setting(self.database_path, "plain_main_ran"), "1")
        self.assertTrue(marker_file.exists())
        self.assertEqual(marker_file.read_text(encoding="utf-8"), "ran")

    def test_startup_runner_survives_standalone_script_exit(self) -> None:
        project_root = Path(self.temp_dir.name)
        scripts_dir = project_root / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)

        (scripts_dir / "01_failing_main_guard.py").write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "import sys",
                    "",
                    "if __name__ == '__main__':",
                    "    sys.exit('boom')",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(self.database_path),
                "PROJECT_ROOT": str(project_root),
                "RUN_STARTUP_SCRIPTS": True,
                "NULLZONE_AGENT_ENABLED": False,
                "SECRET_KEY": "test-secret",
            }
        )

        self.assertIsNotNone(app)
        results = app.config["ADDON_RESULTS"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "error")
        self.assertIn("boom", results[0]["message"])

    def test_startup_runner_times_out_standalone_script(self) -> None:
        project_root = Path(self.temp_dir.name)
        scripts_dir = project_root / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)

        (scripts_dir / "01_sleepy_main_guard.py").write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "import time",
                    "",
                    "if __name__ == '__main__':",
                    "    time.sleep(2)",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(self.database_path),
                "PROJECT_ROOT": str(project_root),
                "RUN_STARTUP_SCRIPTS": True,
                "ADDON_STANDALONE_TIMEOUT": 1,
                "NULLZONE_AGENT_ENABLED": False,
                "SECRET_KEY": "test-secret",
            }
        )

        self.assertIsNotNone(app)
        results = app.config["ADDON_RESULTS"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "error")
        self.assertIn("timeout", results[0]["message"].lower())

    def test_nullzone_agent_reports_missing_env_configuration(self) -> None:
        project_root = Path(self.temp_dir.name)
        agent_dir = project_root / "nullzone_agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "package.json").write_text('{"name":"test-agent"}', encoding="utf-8")

        app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(self.database_path),
                "PROJECT_ROOT": str(project_root),
                "RUN_STARTUP_SCRIPTS": False,
                "NULLZONE_AGENT_ENABLED": True,
                "NULLZONE_AGENT_AUTO_INSTALL": False,
                "SECRET_KEY": "test-secret",
            }
        )

        self.assertIsNotNone(app)
        status = app.config["NULLZONE_AGENT_STATUS"]
        self.assertEqual(status["state"], "warning")
        self.assertIn("PANEL_URL", status["message"])
        self.assertIn("AGENT_TOKEN", status["message"])

    def test_nullzone_agent_requires_real_token_value(self) -> None:
        project_root = Path(self.temp_dir.name)
        agent_dir = project_root / "nullzone_agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "package.json").write_text('{"name":"test-agent"}', encoding="utf-8")
        (agent_dir / ".env").write_text(
            "\n".join(
                [
                    "PANEL_URL=https://example.test",
                    "AGENT_TOKEN=replace-me",
                ]
            ),
            encoding="utf-8",
        )

        app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(self.database_path),
                "PROJECT_ROOT": str(project_root),
                "RUN_STARTUP_SCRIPTS": False,
                "NULLZONE_AGENT_ENABLED": True,
                "NULLZONE_AGENT_AUTO_INSTALL": False,
                "SECRET_KEY": "test-secret",
            }
        )

        self.assertIsNotNone(app)
        status = app.config["NULLZONE_AGENT_STATUS"]
        self.assertEqual(status["state"], "warning")
        self.assertIn("placeholder", status["message"].lower())


if __name__ == "__main__":
    unittest.main()
