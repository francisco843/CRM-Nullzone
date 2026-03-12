from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    industry TEXT,
    website TEXT,
    email TEXT,
    phone TEXT,
    city TEXT,
    country TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    role TEXT,
    status TEXT NOT NULL DEFAULT 'Lead',
    source TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    stage TEXT NOT NULL DEFAULT 'Prospecting',
    value REAL NOT NULL DEFAULT 0,
    owner TEXT,
    expected_close_date TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    related_type TEXT NOT NULL DEFAULT 'general',
    related_id INTEGER,
    due_date TEXT,
    priority TEXT NOT NULL DEFAULT 'Medium',
    status TEXT NOT NULL DEFAULT 'Pending',
    owner TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    action TEXT NOT NULL,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_contacts_company_id ON contacts(company_id);
CREATE INDEX IF NOT EXISTS idx_deals_company_id ON deals(company_id);
CREATE INDEX IF NOT EXISTS idx_deals_contact_id ON deals(contact_id);
CREATE INDEX IF NOT EXISTS idx_deals_stage ON deals(stage);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_activities_created_at ON activities(created_at DESC);
"""


def connect(database_path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(database_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(database_path: str | Path) -> None:
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(database_path) as connection:
        connection.executescript(SCHEMA)
        connection.commit()


def query_all(database_path: str | Path, sql: str, params: tuple[Any, ...] = ()) -> list[dict]:
    with connect(database_path) as connection:
        rows = connection.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def query_one(database_path: str | Path, sql: str, params: tuple[Any, ...] = ()) -> dict | None:
    with connect(database_path) as connection:
        row = connection.execute(sql, params).fetchone()
    return dict(row) if row else None


def execute(database_path: str | Path, sql: str, params: tuple[Any, ...] = ()) -> dict[str, int | None]:
    with connect(database_path) as connection:
        cursor = connection.execute(sql, params)
        connection.commit()
        return {"lastrowid": cursor.lastrowid, "rowcount": cursor.rowcount}


def executemany(database_path: str | Path, sql: str, rows: list[tuple[Any, ...]]) -> dict[str, int]:
    with connect(database_path) as connection:
        cursor = connection.executemany(sql, rows)
        connection.commit()
        return {"rowcount": cursor.rowcount}


def get_setting(database_path: str | Path, key: str, default: str | None = None) -> str | None:
    row = query_one(database_path, "SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def set_setting(database_path: str | Path, key: str, value: str) -> None:
    execute(
        database_path,
        """
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def register_activity(
    database_path: str | Path,
    entity_type: str,
    entity_id: int | None,
    action: str,
    summary: str,
) -> None:
    execute(
        database_path,
        """
        INSERT INTO activities (entity_type, entity_id, action, summary)
        VALUES (?, ?, ?, ?)
        """,
        (entity_type, entity_id, action, summary),
    )


def get_company_options(database_path: str | Path) -> list[dict]:
    return query_all(
        database_path,
        "SELECT id, name FROM companies ORDER BY name COLLATE NOCASE ASC",
    )


def get_contact_options(database_path: str | Path) -> list[dict]:
    return query_all(
        database_path,
        """
        SELECT id, first_name || ' ' || last_name AS name
        FROM contacts
        ORDER BY first_name COLLATE NOCASE ASC, last_name COLLATE NOCASE ASC
        """,
    )


def get_deal_options(database_path: str | Path) -> list[dict]:
    return query_all(
        database_path,
        "SELECT id, title AS name FROM deals ORDER BY title COLLATE NOCASE ASC",
    )


def get_dashboard_data(database_path: str | Path) -> dict[str, Any]:
    today = date.today().isoformat()
    metrics = query_one(
        database_path,
        """
        SELECT
            (SELECT COUNT(*) FROM companies) AS companies,
            (SELECT COUNT(*) FROM contacts) AS contacts,
            (SELECT COUNT(*) FROM deals) AS deals,
            (SELECT COUNT(*) FROM tasks) AS tasks,
            (SELECT COUNT(*) FROM tasks WHERE status NOT IN ('Completed')) AS open_tasks,
            (
                SELECT COUNT(*)
                FROM tasks
                WHERE due_date IS NOT NULL
                  AND due_date < ?
                  AND status NOT IN ('Completed')
            ) AS overdue_tasks,
            (
                SELECT COALESCE(SUM(value), 0)
                FROM deals
                WHERE stage NOT IN ('Won', 'Lost')
            ) AS pipeline_value,
            (
                SELECT COALESCE(SUM(value), 0)
                FROM deals
                WHERE stage = 'Won'
            ) AS won_value
        """,
        (today,),
    ) or {}

    stage_summary = query_all(
        database_path,
        """
        SELECT stage, COUNT(*) AS total, COALESCE(SUM(value), 0) AS value
        FROM deals
        GROUP BY stage
        ORDER BY CASE stage
            WHEN 'Prospecting' THEN 1
            WHEN 'Qualified' THEN 2
            WHEN 'Proposal' THEN 3
            WHEN 'Negotiation' THEN 4
            WHEN 'Won' THEN 5
            WHEN 'Lost' THEN 6
            ELSE 7
        END
        """,
    )

    due_tasks = query_all(
        database_path,
        """
        SELECT
            tasks.*,
            CASE tasks.related_type
                WHEN 'company' THEN (SELECT name FROM companies WHERE id = tasks.related_id)
                WHEN 'contact' THEN (
                    SELECT first_name || ' ' || last_name
                    FROM contacts
                    WHERE id = tasks.related_id
                )
                WHEN 'deal' THEN (SELECT title FROM deals WHERE id = tasks.related_id)
                ELSE 'General'
            END AS related_label,
            CASE
                WHEN tasks.due_date IS NOT NULL
                     AND tasks.due_date < ?
                     AND tasks.status NOT IN ('Completed')
                THEN 1
                ELSE 0
            END AS is_overdue
        FROM tasks
        WHERE tasks.status NOT IN ('Completed')
        ORDER BY
            CASE WHEN tasks.due_date IS NULL THEN 1 ELSE 0 END,
            tasks.due_date ASC,
            tasks.created_at DESC
        LIMIT 6
        """,
        (today,),
    )

    recent_deals = query_all(
        database_path,
        """
        SELECT
            deals.*,
            companies.name AS company_name,
            contacts.first_name || ' ' || contacts.last_name AS contact_name
        FROM deals
        LEFT JOIN companies ON companies.id = deals.company_id
        LEFT JOIN contacts ON contacts.id = deals.contact_id
        ORDER BY deals.created_at DESC
        LIMIT 6
        """,
    )

    recent_activity = query_all(
        database_path,
        """
        SELECT *
        FROM activities
        ORDER BY created_at DESC
        LIMIT 10
        """,
    )

    return {
        "metrics": metrics,
        "stage_summary": stage_summary,
        "due_tasks": due_tasks,
        "recent_deals": recent_deals,
        "recent_activity": recent_activity,
    }


def get_contact_summary(database_path: str | Path) -> dict[str, int]:
    return query_one(
        database_path,
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status = 'Active' THEN 1 ELSE 0 END) AS active,
            SUM(CASE WHEN status = 'Customer' THEN 1 ELSE 0 END) AS customers,
            SUM(CASE WHEN company_id IS NOT NULL THEN 1 ELSE 0 END) AS linked_companies
        FROM contacts
        """,
    ) or {"total": 0, "active": 0, "customers": 0, "linked_companies": 0}


def list_contacts(database_path: str | Path, search: str = "") -> list[dict]:
    like = f"%{search.strip()}%"
    return query_all(
        database_path,
        """
        SELECT
            contacts.*,
            companies.name AS company_name
        FROM contacts
        LEFT JOIN companies ON companies.id = contacts.company_id
        WHERE
            ? = ''
            OR contacts.first_name LIKE ?
            OR contacts.last_name LIKE ?
            OR contacts.email LIKE ?
            OR contacts.phone LIKE ?
            OR companies.name LIKE ?
        ORDER BY contacts.created_at DESC
        """,
        (search.strip(), like, like, like, like, like),
    )


def get_contact(database_path: str | Path, contact_id: int) -> dict | None:
    return query_one(
        database_path,
        """
        SELECT *
        FROM contacts
        WHERE id = ?
        """,
        (contact_id,),
    )


def create_contact(database_path: str | Path, payload: dict[str, Any]) -> int:
    result = execute(
        database_path,
        """
        INSERT INTO contacts (
            first_name, last_name, email, phone, company_id, role, status, source, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["first_name"],
            payload["last_name"],
            payload.get("email"),
            payload.get("phone"),
            payload.get("company_id"),
            payload.get("role"),
            payload["status"],
            payload.get("source"),
            payload.get("notes"),
        ),
    )
    contact_id = int(result["lastrowid"] or 0)
    register_activity(
        database_path,
        "contact",
        contact_id,
        "created",
        f"New contact created: {payload['first_name']} {payload['last_name']}.",
    )
    return contact_id


def update_contact(database_path: str | Path, contact_id: int, payload: dict[str, Any]) -> None:
    execute(
        database_path,
        """
        UPDATE contacts
        SET
            first_name = ?,
            last_name = ?,
            email = ?,
            phone = ?,
            company_id = ?,
            role = ?,
            status = ?,
            source = ?,
            notes = ?
        WHERE id = ?
        """,
        (
            payload["first_name"],
            payload["last_name"],
            payload.get("email"),
            payload.get("phone"),
            payload.get("company_id"),
            payload.get("role"),
            payload["status"],
            payload.get("source"),
            payload.get("notes"),
            contact_id,
        ),
    )
    register_activity(
        database_path,
        "contact",
        contact_id,
        "updated",
        f"Contact updated: {payload['first_name']} {payload['last_name']}.",
    )


def delete_contact(database_path: str | Path, contact_id: int) -> None:
    contact = get_contact(database_path, contact_id)
    execute(database_path, "DELETE FROM contacts WHERE id = ?", (contact_id,))
    if contact:
        register_activity(
            database_path,
            "contact",
            contact_id,
            "deleted",
            f"Contact deleted: {contact['first_name']} {contact['last_name']}.",
        )


def get_company_summary(database_path: str | Path) -> dict[str, int | float]:
    return query_one(
        database_path,
        """
        SELECT
            COUNT(*) AS total,
            (
                SELECT COUNT(*)
                FROM companies c
                WHERE EXISTS (
                    SELECT 1 FROM contacts ct WHERE ct.company_id = c.id
                )
            ) AS with_contacts,
            (
                SELECT COUNT(*)
                FROM companies c
                WHERE EXISTS (
                    SELECT 1 FROM deals d WHERE d.company_id = c.id
                )
            ) AS with_deals,
            (
                SELECT COALESCE(SUM(value), 0)
                FROM deals
                WHERE stage NOT IN ('Won', 'Lost')
            ) AS active_pipeline
        FROM companies
        """,
    ) or {"total": 0, "with_contacts": 0, "with_deals": 0, "active_pipeline": 0}


def list_companies(database_path: str | Path, search: str = "") -> list[dict]:
    like = f"%{search.strip()}%"
    return query_all(
        database_path,
        """
        SELECT
            companies.*,
            (
                SELECT COUNT(*)
                FROM contacts
                WHERE contacts.company_id = companies.id
            ) AS contact_count,
            (
                SELECT COUNT(*)
                FROM deals
                WHERE deals.company_id = companies.id
            ) AS deal_count,
            (
                SELECT COALESCE(SUM(deals.value), 0)
                FROM deals
                WHERE deals.company_id = companies.id
                  AND deals.stage NOT IN ('Won', 'Lost')
            ) AS pipeline_value
        FROM companies
        WHERE
            ? = ''
            OR companies.name LIKE ?
            OR companies.industry LIKE ?
            OR companies.city LIKE ?
            OR companies.country LIKE ?
        ORDER BY companies.created_at DESC
        """,
        (search.strip(), like, like, like, like),
    )


def get_company(database_path: str | Path, company_id: int) -> dict | None:
    return query_one(database_path, "SELECT * FROM companies WHERE id = ?", (company_id,))


def create_company(database_path: str | Path, payload: dict[str, Any]) -> int:
    result = execute(
        database_path,
        """
        INSERT INTO companies (name, industry, website, email, phone, city, country, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["name"],
            payload.get("industry"),
            payload.get("website"),
            payload.get("email"),
            payload.get("phone"),
            payload.get("city"),
            payload.get("country"),
            payload.get("notes"),
        ),
    )
    company_id = int(result["lastrowid"] or 0)
    register_activity(
        database_path,
        "company",
        company_id,
        "created",
        f"Company created: {payload['name']}.",
    )
    return company_id


def update_company(database_path: str | Path, company_id: int, payload: dict[str, Any]) -> None:
    execute(
        database_path,
        """
        UPDATE companies
        SET
            name = ?,
            industry = ?,
            website = ?,
            email = ?,
            phone = ?,
            city = ?,
            country = ?,
            notes = ?
        WHERE id = ?
        """,
        (
            payload["name"],
            payload.get("industry"),
            payload.get("website"),
            payload.get("email"),
            payload.get("phone"),
            payload.get("city"),
            payload.get("country"),
            payload.get("notes"),
            company_id,
        ),
    )
    register_activity(
        database_path,
        "company",
        company_id,
        "updated",
        f"Company updated: {payload['name']}.",
    )


def delete_company(database_path: str | Path, company_id: int) -> None:
    company = get_company(database_path, company_id)
    execute(database_path, "DELETE FROM companies WHERE id = ?", (company_id,))
    if company:
        register_activity(
            database_path,
            "company",
            company_id,
            "deleted",
            f"Company deleted: {company['name']}.",
        )


def get_deal_summary(database_path: str | Path) -> dict[str, int | float]:
    return query_one(
        database_path,
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(CASE WHEN stage NOT IN ('Won', 'Lost') THEN value ELSE 0 END), 0) AS pipeline_value,
            COALESCE(SUM(CASE WHEN stage = 'Won' THEN value ELSE 0 END), 0) AS won_value,
            SUM(CASE WHEN stage = 'Negotiation' THEN 1 ELSE 0 END) AS negotiation
        FROM deals
        """,
    ) or {"total": 0, "pipeline_value": 0, "won_value": 0, "negotiation": 0}


def list_deals(database_path: str | Path, search: str = "") -> list[dict]:
    like = f"%{search.strip()}%"
    return query_all(
        database_path,
        """
        SELECT
            deals.*,
            companies.name AS company_name,
            contacts.first_name || ' ' || contacts.last_name AS contact_name
        FROM deals
        LEFT JOIN companies ON companies.id = deals.company_id
        LEFT JOIN contacts ON contacts.id = deals.contact_id
        WHERE
            ? = ''
            OR deals.title LIKE ?
            OR deals.stage LIKE ?
            OR deals.owner LIKE ?
            OR companies.name LIKE ?
            OR contacts.first_name LIKE ?
            OR contacts.last_name LIKE ?
        ORDER BY deals.created_at DESC
        """,
        (search.strip(), like, like, like, like, like, like),
    )


def get_deal(database_path: str | Path, deal_id: int) -> dict | None:
    return query_one(database_path, "SELECT * FROM deals WHERE id = ?", (deal_id,))


def create_deal(database_path: str | Path, payload: dict[str, Any]) -> int:
    result = execute(
        database_path,
        """
        INSERT INTO deals (
            title, company_id, contact_id, stage, value, owner, expected_close_date, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["title"],
            payload.get("company_id"),
            payload.get("contact_id"),
            payload["stage"],
            payload["value"],
            payload.get("owner"),
            payload.get("expected_close_date"),
            payload.get("notes"),
        ),
    )
    deal_id = int(result["lastrowid"] or 0)
    register_activity(
        database_path,
        "deal",
        deal_id,
        "created",
        f"Deal created: {payload['title']}.",
    )
    return deal_id


def update_deal(database_path: str | Path, deal_id: int, payload: dict[str, Any]) -> None:
    execute(
        database_path,
        """
        UPDATE deals
        SET
            title = ?,
            company_id = ?,
            contact_id = ?,
            stage = ?,
            value = ?,
            owner = ?,
            expected_close_date = ?,
            notes = ?
        WHERE id = ?
        """,
        (
            payload["title"],
            payload.get("company_id"),
            payload.get("contact_id"),
            payload["stage"],
            payload["value"],
            payload.get("owner"),
            payload.get("expected_close_date"),
            payload.get("notes"),
            deal_id,
        ),
    )
    register_activity(
        database_path,
        "deal",
        deal_id,
        "updated",
        f"Deal updated: {payload['title']}.",
    )


def delete_deal(database_path: str | Path, deal_id: int) -> None:
    deal = get_deal(database_path, deal_id)
    execute(database_path, "DELETE FROM deals WHERE id = ?", (deal_id,))
    if deal:
        register_activity(
            database_path,
            "deal",
            deal_id,
            "deleted",
            f"Deal deleted: {deal['title']}.",
        )


def get_task_summary(database_path: str | Path) -> dict[str, int]:
    today = date.today().isoformat()
    return query_one(
        database_path,
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) AS completed,
            SUM(CASE WHEN status NOT IN ('Completed') THEN 1 ELSE 0 END) AS open,
            SUM(
                CASE
                    WHEN due_date IS NOT NULL
                     AND due_date < ?
                     AND status NOT IN ('Completed')
                    THEN 1
                    ELSE 0
                END
            ) AS overdue
        FROM tasks
        """,
        (today,),
    ) or {"total": 0, "completed": 0, "open": 0, "overdue": 0}


def list_tasks(database_path: str | Path, search: str = "") -> list[dict]:
    today = date.today().isoformat()
    like = f"%{search.strip()}%"
    return query_all(
        database_path,
        """
        SELECT
            tasks.*,
            CASE tasks.related_type
                WHEN 'company' THEN (SELECT name FROM companies WHERE id = tasks.related_id)
                WHEN 'contact' THEN (
                    SELECT first_name || ' ' || last_name
                    FROM contacts
                    WHERE id = tasks.related_id
                )
                WHEN 'deal' THEN (SELECT title FROM deals WHERE id = tasks.related_id)
                ELSE 'General'
            END AS related_label,
            CASE
                WHEN tasks.due_date IS NOT NULL
                     AND tasks.due_date < ?
                     AND tasks.status NOT IN ('Completed')
                THEN 1
                ELSE 0
            END AS is_overdue
        FROM tasks
        WHERE
            ? = ''
            OR tasks.title LIKE ?
            OR tasks.priority LIKE ?
            OR tasks.status LIKE ?
            OR tasks.owner LIKE ?
        ORDER BY
            CASE WHEN tasks.status = 'Overdue' THEN 0 ELSE 1 END,
            CASE WHEN tasks.due_date IS NULL THEN 1 ELSE 0 END,
            tasks.due_date ASC,
            tasks.created_at DESC
        """,
        (today, search.strip(), like, like, like, like),
    )


def get_task(database_path: str | Path, task_id: int) -> dict | None:
    return query_one(database_path, "SELECT * FROM tasks WHERE id = ?", (task_id,))


def create_task(database_path: str | Path, payload: dict[str, Any]) -> int:
    result = execute(
        database_path,
        """
        INSERT INTO tasks (
            title, related_type, related_id, due_date, priority, status, owner, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["title"],
            payload["related_type"],
            payload.get("related_id"),
            payload.get("due_date"),
            payload["priority"],
            payload["status"],
            payload.get("owner"),
            payload.get("notes"),
        ),
    )
    task_id = int(result["lastrowid"] or 0)
    register_activity(
        database_path,
        "task",
        task_id,
        "created",
        f"Task created: {payload['title']}.",
    )
    return task_id


def update_task(database_path: str | Path, task_id: int, payload: dict[str, Any]) -> None:
    execute(
        database_path,
        """
        UPDATE tasks
        SET
            title = ?,
            related_type = ?,
            related_id = ?,
            due_date = ?,
            priority = ?,
            status = ?,
            owner = ?,
            notes = ?
        WHERE id = ?
        """,
        (
            payload["title"],
            payload["related_type"],
            payload.get("related_id"),
            payload.get("due_date"),
            payload["priority"],
            payload["status"],
            payload.get("owner"),
            payload.get("notes"),
            task_id,
        ),
    )
    register_activity(
        database_path,
        "task",
        task_id,
        "updated",
        f"Task updated: {payload['title']}.",
    )


def delete_task(database_path: str | Path, task_id: int) -> None:
    task = get_task(database_path, task_id)
    execute(database_path, "DELETE FROM tasks WHERE id = ?", (task_id,))
    if task:
        register_activity(
            database_path,
            "task",
            task_id,
            "deleted",
            f"Task deleted: {task['title']}.",
        )


def search_everything(database_path: str | Path, query: str) -> dict[str, list[dict]]:
    return {
        "companies": list_companies(database_path, query)[:8],
        "contacts": list_contacts(database_path, query)[:8],
        "deals": list_deals(database_path, query)[:8],
        "tasks": list_tasks(database_path, query)[:8],
    }
