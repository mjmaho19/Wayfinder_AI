# Copyright Michael Mahoney February 2026

"""
run_worker.py — Background task worker for the Wayfinder agent pipeline.

Continuously polls the database for pending AgentTask rows and processes
them one at a time using Postgres row-level locking to prevent duplicate
execution across multiple worker instances. Dispatches each task to the
appropriate tool runner or the AI supervisor, stores results, and enqueues
follow-up tasks as directed by the supervisor's agentic loop.

Supported task types: weather, places, transit, alerts, email_alert,
culture, events, and supervisor_update.

Run from the repo root:
    python workers/run_worker.py
"""

from __future__ import annotations

import json
import os
import socket
import time
from datetime import datetime

# Import your Flask app + models from index.py
# Run from repo root:
#   python workers/run_worker.py
from index import app, db, WayfinderSubmission, AgentTask, ToolResult, TripPlan, PlanEdit  # type: ignore

from agents.supervisor import run_supervisor
from tools.weather_tool import run as run_weather
from tools.places_tool import run as run_places
from tools.transit_tool import run as run_transit
from tools.alerts_tool import run as run_alerts
from tools.email_alert_tool import run as run_email_alert
from tools.culture_tool import run as run_culture
from tools.events_tool import run as run_events


POLL_SECONDS = float(os.getenv("WAYFINDER_WORKER_POLL_SECONDS", "2.0"))
WORKER_ID = os.getenv("WAYFINDER_WORKER_ID") or socket.gethostname()

TOOL_RUNNERS = {
    "weather": run_weather,
    "places": run_places,
    "transit": run_transit,
    "alerts": run_alerts,
    "email_alert": run_email_alert,
    "culture": run_culture,
    "events": run_events,
}


def _safe_load_task_input(task: AgentTask) -> dict:
    """
    Parse a task's ``input_json`` field into a dictionary.

    Reads the ``input_json`` attribute from the task and attempts to
    deserialize it. Non-dict JSON values (e.g. a bare string or number)
    are wrapped under a ``"value"`` key. Malformed JSON is returned as
    a dict with a ``"raw"`` key containing the original string.

    Args:
        task: An ``AgentTask`` model instance whose ``input_json``
            attribute will be parsed.

    Returns:
        A dictionary representing the task input. Returns an empty
        dictionary if ``input_json`` is absent or empty.
    """
    raw = getattr(task, "input_json", None)
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {"value": obj}
    except Exception:
        return {"raw": raw}


def _ensure_supervisor_task(submission_id: int) -> None:
    """
    Enqueue a supervisor update task for a submission if one is not already pending.

    Checks whether a ``supervisor_update`` task in ``pending`` status already
    exists for the given submission. If not, creates one so the AI supervisor
    will re-evaluate the plan as new tool results arrive, driving the
    agentic loop forward.

    Args:
        submission_id: Primary key of the ``WayfinderSubmission`` to check
            and potentially enqueue a supervisor task for.
    """
    exists = (
        AgentTask.query.filter_by(submission_id=submission_id, task_type="supervisor_update", status="pending")
        .count()
        > 0
    )
    if not exists:
        db.session.add(
            AgentTask(
                submission_id=submission_id,
                task_type="supervisor_update",
                status="pending",
                input_json=json.dumps({"reason": "tool_result_updated"}),
                attempts=0,
                max_attempts=3,
            )
        )
        db.session.commit()


def _claim_next_task() -> AgentTask | None:
    """
    Atomically claim the oldest pending task using Postgres row locking.

    Queries for the earliest ``pending`` task by ``created_at``, locks it
    with ``SELECT FOR UPDATE SKIP LOCKED`` to prevent other worker instances
    from claiming the same row, then immediately marks it as ``running``
    and increments its attempt counter.

    Returns:
        The claimed and updated ``AgentTask`` instance, or ``None`` if no
        pending tasks are available.
    """
    task = (
        AgentTask.query.filter_by(status="pending")
        .order_by(AgentTask.created_at.asc())
        .with_for_update(skip_locked=True)
        .first()
    )
    if not task:
        return None

    task.status = "running"
    task.started_at = datetime.utcnow()
    task.worker_id = WORKER_ID
    task.attempts = (task.attempts or 0) + 1
    db.session.commit()
    return task


def _mark_failed(task: AgentTask, err: str) -> None:
    """
    Record a task failure and apply retry logic.

    Stores the error message and finish timestamp on the task. If the task
    has not yet exhausted its maximum allowed attempts, it is reset to
    ``pending`` so the worker will try it again. Otherwise it is marked
    ``failed`` permanently.

    Args:
        task: The ``AgentTask`` instance that failed.
        err: A string describing the error that caused the failure.
    """
    task.error = err
    task.finished_at = datetime.utcnow()

    # Retry logic
    if (task.attempts or 0) < (task.max_attempts or 1):
        task.status = "pending"
    else:
        task.status = "failed"

    db.session.commit()


def _mark_completed(task: AgentTask) -> None:
    """
    Mark a task as successfully completed and record its finish time.

    Args:
        task: The ``AgentTask`` instance to mark as completed.
    """
    task.status = "completed"
    task.finished_at = datetime.utcnow()
    db.session.commit()


def _load_tool_payloads(submission_id: int, tool_name: str) -> list[dict]:
    """
    Load all stored payloads for a specific tool and submission.

    Queries ``ToolResult`` rows matching the given submission and tool name,
    ordered by creation time, and deserializes each ``result_json`` field.
    Rows that fail JSON parsing are silently skipped.

    Args:
        submission_id: Primary key of the target ``WayfinderSubmission``.
        tool_name: The tool name string to filter by (e.g. ``"email_alert"``).

    Returns:
        A list of parsed payload dictionaries in ascending creation order.
        Returns an empty list if no matching rows exist or all fail to parse.
    """
    rows = (
        ToolResult.query.filter_by(submission_id=submission_id, tool_name=tool_name)
        .order_by(ToolResult.created_at.asc())
        .all()
    )

    payloads = []
    for row in rows:
        try:
            payloads.append(json.loads(row.result_json))
        except Exception:
            continue
    return payloads


def _extract_new_alerts_for_email(submission_id: int, alert_payload: dict) -> list[dict]:
    """
    Determine which alerts from the current payload should trigger an email.

    Implements a send-once guard: if any prior ``email_alert`` result already
    exists for this submission, no alerts are returned. Otherwise, filters
    the current alerts payload down to medium- and high-severity items that
    have a non-empty title.

    Args:
        submission_id: Primary key of the ``WayfinderSubmission`` to check
            for prior email alert history.
        alert_payload: The parsed payload dictionary from the most recent
            alerts tool result, expected to contain an ``"alerts"`` list.

    Returns:
        A filtered list of alert dictionaries eligible for email delivery,
        or an empty list if a prior email has already been sent or no
        qualifying alerts exist.
    """
    prior_email_results = _load_tool_payloads(submission_id, "email_alert")
    if prior_email_results:
        return []

    alerts = alert_payload.get("alerts", []) or []
    filtered = []

    for alert in alerts:
        if not isinstance(alert, dict):
            continue

        severity = str(alert.get("severity") or "").lower()
        title = str(alert.get("title") or "").strip()

        if severity not in {"high", "medium"}:
            continue
        if not title:
            continue

        filtered.append(alert)

    return filtered


def _run_tool_task(task: AgentTask) -> None:
    """
    Execute a tool task and persist the result to the database.

    Loads the submission, resolves the correct tool runner from
    ``TOOL_RUNNERS``, invokes it with the task input, and saves the
    returned payload as a new ``ToolResult`` row. After saving, updates
    the submission status to ``"processing"`` if it is still pending.
    If the task is an alerts task and important alerts are found, enqueues
    an ``email_alert`` task (once per submission). Always enqueues a
    ``supervisor_update`` task so the plan is refreshed with the new data.

    Args:
        task: The claimed ``AgentTask`` instance to execute.
    """
    submission = WayfinderSubmission.query.get(task.submission_id)
    if not submission:
        _mark_failed(task, f"Submission {task.submission_id} not found.")
        return

    runner = TOOL_RUNNERS.get(task.task_type)
    if not runner:
        _mark_failed(task, f"Unknown tool task_type: {task.task_type}")
        return

    task_input = _safe_load_task_input(task)

    payload = runner(submission, task_input)

    tool_name = task.task_type
    result = ToolResult(
        submission_id=submission.id,
        tool_name=tool_name,
        result_json=json.dumps(payload),
    )
    db.session.add(result)

    if submission.status in ("pending", "processing"):
        submission.status = "processing"

    db.session.commit()

    # If alerts found anything important, queue one email notification
    if task.task_type == "alerts":
        new_alerts = _extract_new_alerts_for_email(submission.id, payload)

        if submission.email and new_alerts:
            exists = (
                AgentTask.query.filter(
                    AgentTask.submission_id == submission.id,
                    AgentTask.task_type == "email_alert",
                    AgentTask.status.in_(["pending", "running"]),
                ).count()
                > 0
            )

            if not exists:
                db.session.add(
                    AgentTask(
                        submission_id=submission.id,
                        task_type="email_alert",
                        status="pending",
                        input_json=json.dumps(
                            {
                                "email": submission.email,
                                "alerts": new_alerts[:5],
                            }
                        ),
                        attempts=0,
                        max_attempts=3,
                    )
                )
                db.session.commit()

    _ensure_supervisor_task(submission.id)
    _mark_completed(task)


def _run_supervisor_task(task: AgentTask) -> None:
    """
    Run the AI supervisor and update the trip plan in the database.

    Loads the submission, all existing tool results, and the current saved
    plan, then calls the AI supervisor to produce an updated plan and a list
    of any additional tool tasks still needed. Persists the new plan to the
    ``TripPlan`` table, updates the submission status, marks any associated
    ``PlanEdit`` as applied, and enqueues the supervisor-requested follow-up
    tasks — skipping any that are already pending or running.

    Args:
        task: The claimed ``AgentTask`` instance of type ``supervisor_update``.
            Its ``input_json`` may contain a ``plan_edit_id`` when the
            supervisor run was triggered by a user edit request.
    """
    submission = WayfinderSubmission.query.get(task.submission_id)
    if not submission:
        _mark_failed(task, f"Submission {task.submission_id} not found.")
        return

    # read supervisor_update task input (may include plan_edit_id)
    task_input = _safe_load_task_input(task)

    plan_edit = None
    edit_request = None
    if task_input.get("reason") == "plan_edit":
        plan_edit_id = task_input.get("plan_edit_id")
        if plan_edit_id:
            plan_edit = PlanEdit.query.get(plan_edit_id)
            if plan_edit:
                edit_request = {
                    "id": plan_edit.id,
                    "source": plan_edit.source,
                    "user_message": plan_edit.user_message,
                }

    # Load all tool results for this submission
    results = (
        ToolResult.query.filter_by(submission_id=submission.id)
        .order_by(ToolResult.created_at.asc())
        .all()
    )

    tool_results = []
    for r in results:
        try:
            payload = json.loads(r.result_json)
        except Exception:
            payload = {"raw": r.result_json}
        tool_results.append({"tool_name": r.tool_name, "payload": payload})

    plan_row = TripPlan.query.filter_by(submission_id=submission.id).first()
    current_plan = None
    if plan_row and plan_row.plan_json:
        try:
            current_plan = json.loads(plan_row.plan_json)
        except Exception:
            current_plan = None

    submission_dict = {
        "id": submission.id,
        "traveler_name": submission.traveler_name,
        "email": submission.email,
        "origin": submission.origin,
        "desired_destination": submission.desired_destination,
        "travel_dates": submission.travel_dates,
        "budget": submission.budget,
        "preferences": submission.preferences,
        "raw_request": submission.raw_request,

        # attach edit request so supervisor can apply it
        "edit_request": edit_request,
    }

    try:
        supervisor_out = run_supervisor(submission_dict, tool_results, current_plan)
    except Exception as exc:
        # Mark edit failed if this supervisor run was caused by an edit
        if plan_edit:
            plan_edit.status = "failed"
            db.session.commit()
        _mark_failed(task, f"Supervisor error: {type(exc).__name__}: {exc}")
        return

    status = supervisor_out.get("status", "processing")
    plan = supervisor_out.get("plan", {})
    summary = supervisor_out.get("summary", "")

    if not plan_row:
        plan_row = TripPlan(submission_id=submission.id)
        db.session.add(plan_row)

    plan_row.plan_json = json.dumps(plan)
    plan_row.summary = summary

    # Update submission status
    submission.status = status
    db.session.commit()

    # if we processed an edit, mark it applied
    if plan_edit:
        plan_edit.status = "applied"
        db.session.commit()

    # Agentic behavior: enqueue tasks supervisor says are missing
    new_tasks = supervisor_out.get("new_tasks") or []
    for spec in new_tasks:
        task_type = spec.get("task_type")
        input_obj = spec.get("input") or {}

        if not task_type:
            continue

        # Avoid duplicates: don't enqueue if pending/running exists for this type
        exists = (
            AgentTask.query.filter(
                AgentTask.submission_id == submission.id,
                AgentTask.task_type == task_type,
                AgentTask.status.in_(["pending", "running"]),
            ).count()
            > 0
        )
        if exists:
            continue

        db.session.add(
            AgentTask(
                submission_id=submission.id,
                task_type=task_type,
                status="pending",
                input_json=json.dumps(input_obj),
                attempts=0,
                max_attempts=3,
            )
        )
    db.session.commit()

    _mark_completed(task)


def main() -> None:
    """
    Start the Wayfinder background worker loop.

    Prints the worker ID and poll interval, then enters an infinite loop
    inside the Flask application context. On each iteration, attempts to
    claim a pending task and dispatches it to either ``_run_supervisor_task``
    or ``_run_tool_task`` based on its type. Sleeps for ``POLL_SECONDS``
    when no tasks are available. Unhandled exceptions are caught, the
    in-progress task is marked failed, and the loop continues after a
    brief sleep to avoid tight error loops.
    """
    print(f"[Wayfinder Worker] Starting worker_id={WORKER_ID} poll={POLL_SECONDS}s")

    with app.app_context():
        while True:
            task: AgentTask | None = None
            try:
                task = _claim_next_task()
                if not task:
                    time.sleep(POLL_SECONDS)
                    continue

                if task.task_type == "supervisor_update":
                    _run_supervisor_task(task)
                else:
                    _run_tool_task(task)

            except Exception as e:
                # if we were running a task, mark it failed properly
                try:
                    if task is not None:
                        _mark_failed(task, f"{type(e).__name__}: {e}")
                except Exception as mark_err:
                    print(f"[Wayfinder Worker] ERROR while marking failed: {mark_err}")

                print(f"[Wayfinder Worker] ERROR: {type(e).__name__}: {e}")
                time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()