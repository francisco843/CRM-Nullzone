from __future__ import annotations

from datetime import date, timedelta


def run(context: dict[str, object]) -> None:
    if context["get_setting"]("demo_seeded") == "1":
        context["log"]("The database already contains demo data.")
        return

    today = date.today()
    companies = [
        (
            "Nexa Logistics",
            "Logistics",
            "https://nexa.example",
            "ops@nexa.example",
            "+1 305 555 0101",
            "Miami",
            "USA",
            "Sample account focused on regional expansion.",
        ),
        (
            "Lumen Studio",
            "Marketing",
            "https://lumen.example",
            "hello@lumen.example",
            "+52 55 5555 0123",
            "Mexico City",
            "Mexico",
            "Company interested in automating its sales pipeline.",
        ),
    ]

    context["executemany"](
        """
        INSERT INTO companies (name, industry, website, email, phone, city, country, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        companies,
    )

    company_lookup = {
        row["name"]: row["id"]
        for row in context["query_all"]("SELECT id, name FROM companies")
    }

    contacts = [
        (
            "Alicia",
            "Mendez",
            "alicia@nexa.example",
            "+1 305 555 0110",
            company_lookup["Nexa Logistics"],
            "Head of Sales",
            "Customer",
            "Referral",
            "Primary contact for renewals.",
        ),
        (
            "Diego",
            "Ortega",
            "diego@lumen.example",
            "+52 55 5555 0199",
            company_lookup["Lumen Studio"],
            "Operations Lead",
            "Active",
            "LinkedIn",
            "Evaluating the annual plan with full onboarding.",
        ),
    ]

    context["executemany"](
        """
        INSERT INTO contacts (
            first_name, last_name, email, phone, company_id, role, status, source, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        contacts,
    )

    contact_lookup = {
        row["name"]: row["id"]
        for row in context["query_all"](
            "SELECT id, first_name || ' ' || last_name AS name FROM contacts"
        )
    }

    deals = [
        (
            "Q2 regional renewal",
            company_lookup["Nexa Logistics"],
            contact_lookup["Alicia Mendez"],
            "Negotiation",
            18500,
            "Alecks",
            (today + timedelta(days=12)).isoformat(),
            "Currently in legal approval.",
        ),
        (
            "2026 CRM implementation",
            company_lookup["Lumen Studio"],
            contact_lookup["Diego Ortega"],
            "Proposal",
            9200,
            "Growth Team",
            (today + timedelta(days=20)).isoformat(),
            "Proposal sent with reporting addon included.",
        ),
    ]

    context["executemany"](
        """
        INSERT INTO deals (
            title, company_id, contact_id, stage, value, owner, expected_close_date, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        deals,
    )

    deal_lookup = {
        row["name"]: row["id"]
        for row in context["query_all"]("SELECT id, title AS name FROM deals")
    }

    tasks = [
        (
            "Call to confirm contract signature",
            "deal",
            deal_lookup["Q2 regional renewal"],
            (today + timedelta(days=2)).isoformat(),
            "High",
            "Pending",
            "Alecks",
            "Review discounts before the call.",
        ),
        (
            "Prepare technical demo for the reporting addon",
            "deal",
            deal_lookup["2026 CRM implementation"],
            (today + timedelta(days=5)).isoformat(),
            "Medium",
            "In Progress",
            "Growth Team",
            "Present the dashboard and script runner.",
        ),
    ]

    context["executemany"](
        """
        INSERT INTO tasks (
            title, related_type, related_id, due_date, priority, status, owner, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        tasks,
    )

    context["set_setting"]("demo_seeded", "1")
    context["register_activity"](
        "system",
        None,
        "addon",
        "Addon 01_demo_seed loaded demo data for the CRM.",
    )
    context["log"]("Demo data loaded successfully.")
