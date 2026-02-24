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
from index import app, db, WayfinderSubmission, AgentTask, ToolResult, TripPlan  # type: ignore

from agents.supervisor import run_supervisor
from tools.weather_tool import run as run_weather
from tools.places_tool import run as run_places
from tools.transit_tool import run as run_transit


POLL_SECONDS = float(os.getenv("WAYFINDER_WORKER_POLL_SECONDS", "2.0"))
WORKER_ID = os.getenv("WAYFINDER_WORKER_ID") or socket.gethostname()

TOOL_RUNNERS = {
    "weather": run_weather,
    "places": run_places,
    "transit": run_transit,
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

    # pass task input through
    payload = runner(submission, task_input)

    tool_name = task.task_type  # keep tool_name aligned with task_type for simplicity
    result = ToolResult(
        submission_id=submission.id,
        tool_name=tool_name,
        result_json=json.dumps(payload),
    )
    db.session.add(result)

    # Update submission status to show progress
    if submission.status in ("pending", "processing"):
        submission.status = "processing"

    db.session.commit()

    # After tool completes, enqueue supervisor update
    _ensure_supervisor_task(submission.id)

    _mark_completed(task)


def _run_supervisor_task(task: AgentTask) -> None:
    submission = WayfinderSubmission.query.get(task.submission_id)
    if not submission:
        _mark_failed(task, f"Submission {task.submission_id} not found.")
        return

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
    }

    supervisor_out = run_supervisor(submission_dict, tool_results, current_plan)

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