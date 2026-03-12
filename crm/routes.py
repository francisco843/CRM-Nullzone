from __future__ import annotations

from flask import Blueprint, Flask, current_app, flash, redirect, render_template, request, url_for

from . import db


bp = Blueprint("crm", __name__)

CONTACT_STATUSES = ["Lead", "Active", "Customer", "Dormant"]
DEAL_STAGES = ["Prospecting", "Qualified", "Proposal", "Negotiation", "Won", "Lost"]
TASK_PRIORITIES = ["Low", "Medium", "High", "Critical"]
TASK_STATUSES = ["Pending", "In Progress", "Completed", "Blocked", "Overdue"]


def register_routes(app: Flask) -> None:
    app.register_blueprint(bp)


def database_path() -> str:
    return current_app.config["DATABASE"]


def clean_text(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


def clean_int(value: str | None) -> int | None:
    normalized = clean_text(value)
    if not normalized:
        return None
    try:
        return int(normalized)
    except ValueError:
        return None


def clean_float(value: str | None) -> float:
    normalized = clean_text(value)
    if not normalized:
        return 0.0
    try:
        return float(normalized.replace(",", ""))
    except ValueError:
        return 0.0


def parse_related_reference(value: str | None) -> tuple[str, int | None]:
    normalized = clean_text(value)
    if not normalized:
        return "general", None

    try:
        related_type, related_id = normalized.split(":", 1)
        return related_type, int(related_id)
    except (ValueError, TypeError):
        return "general", None


def build_related_reference(task: dict | None) -> str:
    if not task:
        return ""
    related_type = task.get("related_type")
    related_id = task.get("related_id")
    if related_type and related_id:
        return f"{related_type}:{related_id}"
    return ""


def relation_options() -> dict[str, list[dict]]:
    path = database_path()
    return {
        "companies": db.get_company_options(path),
        "contacts": db.get_contact_options(path),
        "deals": db.get_deal_options(path),
    }


@bp.get("/")
def dashboard():
    data = db.get_dashboard_data(database_path())
    stage_totals = [stage["total"] for stage in data["stage_summary"]]
    max_stage_total = max(stage_totals) if stage_totals else 1
    return render_template(
        "dashboard.html",
        data=data,
        max_stage_total=max_stage_total,
        addon_results=current_app.config.get("ADDON_RESULTS", []),
        nullzone_agent_status=current_app.config.get("NULLZONE_AGENT_STATUS", {}),
    )


@bp.get("/search")
def search():
    query = (request.args.get("q") or "").strip()
    results = db.search_everything(database_path(), query) if query else {
        "companies": [],
        "contacts": [],
        "deals": [],
        "tasks": [],
    }
    return render_template("search.html", query=query, results=results)


@bp.get("/contacts")
def contacts():
    query = (request.args.get("q") or "").strip()
    return render_template(
        "contacts.html",
        contacts=db.list_contacts(database_path(), query),
        query=query,
        summary=db.get_contact_summary(database_path()),
    )


@bp.route("/contacts/new", methods=["GET", "POST"])
def new_contact():
    if request.method == "POST":
        payload = {
            "first_name": (request.form.get("first_name") or "").strip(),
            "last_name": (request.form.get("last_name") or "").strip(),
            "email": clean_text(request.form.get("email")),
            "phone": clean_text(request.form.get("phone")),
            "company_id": clean_int(request.form.get("company_id")),
            "role": clean_text(request.form.get("role")),
            "status": request.form.get("status") or "Lead",
            "source": clean_text(request.form.get("source")),
            "notes": clean_text(request.form.get("notes")),
        }

        if not payload["first_name"] or not payload["last_name"]:
            flash("First and last name are required.", "error")
        else:
            db.create_contact(database_path(), payload)
            flash("Contact created successfully.", "success")
            return redirect(url_for("crm.contacts"))

    return render_template(
        "contact_form.html",
        contact=None,
        companies=db.get_company_options(database_path()),
        contact_statuses=CONTACT_STATUSES,
    )


@bp.route("/contacts/<int:contact_id>/edit", methods=["GET", "POST"])
def edit_contact(contact_id: int):
    contact = db.get_contact(database_path(), contact_id)
    if not contact:
        flash("Contact does not exist.", "error")
        return redirect(url_for("crm.contacts"))

    if request.method == "POST":
        payload = {
            "first_name": (request.form.get("first_name") or "").strip(),
            "last_name": (request.form.get("last_name") or "").strip(),
            "email": clean_text(request.form.get("email")),
            "phone": clean_text(request.form.get("phone")),
            "company_id": clean_int(request.form.get("company_id")),
            "role": clean_text(request.form.get("role")),
            "status": request.form.get("status") or "Lead",
            "source": clean_text(request.form.get("source")),
            "notes": clean_text(request.form.get("notes")),
        }

        if not payload["first_name"] or not payload["last_name"]:
            flash("First and last name are required.", "error")
        else:
            db.update_contact(database_path(), contact_id, payload)
            flash("Contact updated.", "success")
            return redirect(url_for("crm.contacts"))

        contact = {**contact, **payload}

    return render_template(
        "contact_form.html",
        contact=contact,
        companies=db.get_company_options(database_path()),
        contact_statuses=CONTACT_STATUSES,
    )


@bp.post("/contacts/<int:contact_id>/delete")
def delete_contact(contact_id: int):
    db.delete_contact(database_path(), contact_id)
    flash("Contact deleted.", "success")
    return redirect(url_for("crm.contacts"))


@bp.get("/companies")
def companies():
    query = (request.args.get("q") or "").strip()
    return render_template(
        "companies.html",
        companies=db.list_companies(database_path(), query),
        query=query,
        summary=db.get_company_summary(database_path()),
    )


@bp.route("/companies/new", methods=["GET", "POST"])
def new_company():
    if request.method == "POST":
        payload = {
            "name": (request.form.get("name") or "").strip(),
            "industry": clean_text(request.form.get("industry")),
            "website": clean_text(request.form.get("website")),
            "email": clean_text(request.form.get("email")),
            "phone": clean_text(request.form.get("phone")),
            "city": clean_text(request.form.get("city")),
            "country": clean_text(request.form.get("country")),
            "notes": clean_text(request.form.get("notes")),
        }

        if not payload["name"]:
            flash("Company name is required.", "error")
        else:
            db.create_company(database_path(), payload)
            flash("Company created successfully.", "success")
            return redirect(url_for("crm.companies"))

    return render_template("company_form.html", company=None)


@bp.route("/companies/<int:company_id>/edit", methods=["GET", "POST"])
def edit_company(company_id: int):
    company = db.get_company(database_path(), company_id)
    if not company:
        flash("Company does not exist.", "error")
        return redirect(url_for("crm.companies"))

    if request.method == "POST":
        payload = {
            "name": (request.form.get("name") or "").strip(),
            "industry": clean_text(request.form.get("industry")),
            "website": clean_text(request.form.get("website")),
            "email": clean_text(request.form.get("email")),
            "phone": clean_text(request.form.get("phone")),
            "city": clean_text(request.form.get("city")),
            "country": clean_text(request.form.get("country")),
            "notes": clean_text(request.form.get("notes")),
        }

        if not payload["name"]:
            flash("Company name is required.", "error")
        else:
            db.update_company(database_path(), company_id, payload)
            flash("Company updated.", "success")
            return redirect(url_for("crm.companies"))

        company = {**company, **payload}

    return render_template("company_form.html", company=company)


@bp.post("/companies/<int:company_id>/delete")
def delete_company(company_id: int):
    db.delete_company(database_path(), company_id)
    flash("Company deleted.", "success")
    return redirect(url_for("crm.companies"))


@bp.get("/deals")
def deals():
    query = (request.args.get("q") or "").strip()
    return render_template(
        "deals.html",
        deals=db.list_deals(database_path(), query),
        query=query,
        summary=db.get_deal_summary(database_path()),
    )


@bp.route("/deals/new", methods=["GET", "POST"])
def new_deal():
    if request.method == "POST":
        payload = {
            "title": (request.form.get("title") or "").strip(),
            "company_id": clean_int(request.form.get("company_id")),
            "contact_id": clean_int(request.form.get("contact_id")),
            "stage": request.form.get("stage") or "Prospecting",
            "value": clean_float(request.form.get("value")),
            "owner": clean_text(request.form.get("owner")),
            "expected_close_date": clean_text(request.form.get("expected_close_date")),
            "notes": clean_text(request.form.get("notes")),
        }

        if not payload["title"]:
            flash("Deal title is required.", "error")
        else:
            db.create_deal(database_path(), payload)
            flash("Deal created successfully.", "success")
            return redirect(url_for("crm.deals"))

    return render_template(
        "deal_form.html",
        deal=None,
        companies=db.get_company_options(database_path()),
        contacts=db.get_contact_options(database_path()),
        deal_stages=DEAL_STAGES,
    )


@bp.route("/deals/<int:deal_id>/edit", methods=["GET", "POST"])
def edit_deal(deal_id: int):
    deal = db.get_deal(database_path(), deal_id)
    if not deal:
        flash("Deal does not exist.", "error")
        return redirect(url_for("crm.deals"))

    if request.method == "POST":
        payload = {
            "title": (request.form.get("title") or "").strip(),
            "company_id": clean_int(request.form.get("company_id")),
            "contact_id": clean_int(request.form.get("contact_id")),
            "stage": request.form.get("stage") or "Prospecting",
            "value": clean_float(request.form.get("value")),
            "owner": clean_text(request.form.get("owner")),
            "expected_close_date": clean_text(request.form.get("expected_close_date")),
            "notes": clean_text(request.form.get("notes")),
        }

        if not payload["title"]:
            flash("Deal title is required.", "error")
        else:
            db.update_deal(database_path(), deal_id, payload)
            flash("Deal updated.", "success")
            return redirect(url_for("crm.deals"))

        deal = {**deal, **payload}

    return render_template(
        "deal_form.html",
        deal=deal,
        companies=db.get_company_options(database_path()),
        contacts=db.get_contact_options(database_path()),
        deal_stages=DEAL_STAGES,
    )


@bp.post("/deals/<int:deal_id>/delete")
def delete_deal(deal_id: int):
    db.delete_deal(database_path(), deal_id)
    flash("Deal deleted.", "success")
    return redirect(url_for("crm.deals"))


@bp.get("/tasks")
def tasks():
    query = (request.args.get("q") or "").strip()
    return render_template(
        "tasks.html",
        tasks=db.list_tasks(database_path(), query),
        query=query,
        summary=db.get_task_summary(database_path()),
    )


@bp.route("/tasks/new", methods=["GET", "POST"])
def new_task():
    if request.method == "POST":
        related_type, related_id = parse_related_reference(request.form.get("related_reference"))
        payload = {
            "title": (request.form.get("title") or "").strip(),
            "related_type": related_type,
            "related_id": related_id,
            "due_date": clean_text(request.form.get("due_date")),
            "priority": request.form.get("priority") or "Medium",
            "status": request.form.get("status") or "Pending",
            "owner": clean_text(request.form.get("owner")),
            "notes": clean_text(request.form.get("notes")),
        }

        if not payload["title"]:
            flash("Task title is required.", "error")
        else:
            db.create_task(database_path(), payload)
            flash("Task created successfully.", "success")
            return redirect(url_for("crm.tasks"))

    return render_template(
        "task_form.html",
        task=None,
        task_priorities=TASK_PRIORITIES,
        task_statuses=TASK_STATUSES,
        relation_options=relation_options(),
        selected_reference="",
    )


@bp.route("/tasks/<int:task_id>/edit", methods=["GET", "POST"])
def edit_task(task_id: int):
    task = db.get_task(database_path(), task_id)
    if not task:
        flash("Task does not exist.", "error")
        return redirect(url_for("crm.tasks"))

    if request.method == "POST":
        related_type, related_id = parse_related_reference(request.form.get("related_reference"))
        payload = {
            "title": (request.form.get("title") or "").strip(),
            "related_type": related_type,
            "related_id": related_id,
            "due_date": clean_text(request.form.get("due_date")),
            "priority": request.form.get("priority") or "Medium",
            "status": request.form.get("status") or "Pending",
            "owner": clean_text(request.form.get("owner")),
            "notes": clean_text(request.form.get("notes")),
        }

        if not payload["title"]:
            flash("Task title is required.", "error")
        else:
            db.update_task(database_path(), task_id, payload)
            flash("Task updated.", "success")
            return redirect(url_for("crm.tasks"))

        task = {**task, **payload}

    return render_template(
        "task_form.html",
        task=task,
        task_priorities=TASK_PRIORITIES,
        task_statuses=TASK_STATUSES,
        relation_options=relation_options(),
        selected_reference=build_related_reference(task),
    )


@bp.post("/tasks/<int:task_id>/delete")
def delete_task(task_id: int):
    db.delete_task(database_path(), task_id)
    flash("Task deleted.", "success")
    return redirect(url_for("crm.tasks"))
