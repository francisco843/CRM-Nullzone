from __future__ import annotations

from datetime import date


def run(context: dict[str, object]) -> None:
    result = context["execute"](
        """
        UPDATE tasks
        SET status = 'Overdue'
        WHERE due_date IS NOT NULL
          AND due_date < ?
          AND status NOT IN ('Completed', 'Overdue')
        """,
        (date.today().isoformat(),),
    )

    if result["rowcount"]:
        context["register_activity"](
            "system",
            None,
            "addon",
            f"Addon 02_overdue_tasks marked {result['rowcount']} tasks as overdue.",
        )

    context["log"](f"Overdue tasks updated: {result['rowcount']}.")
