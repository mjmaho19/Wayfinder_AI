# Copyright Michael Mahoney February 2026

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
    Actually use task.input_json (if present) and pass it into tools.
    Always returns a dict.
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
    Make sure there is a pending supervisor_update task for this submission,
    so the plan refreshes as tool results arrive (agentic loop).
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
    Atomically claim one pending task using Postgres row locking.
    Requires Postgres (Render) which you are using.
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
    central failure handler with retry logic.
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
    task.status = "completed"
    task.finished_at = datetime.utcnow()
    db.session.commit()


def _load_tool_payloads(submission_id: int, tool_name: str) -> list[dict]:
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
    Temporary first-version behavior:
    - if this submission already has any completed email_alert result, do not send again
    - only use alerts from the current alerts payload
    - only keep medium/high alerts
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