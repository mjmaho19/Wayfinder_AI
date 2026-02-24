# Copyright Michael Mahoney February 2026

# PLACEHOLDER STUB SO PROGRAM STAYS DEMO-ABLE, REAL AGENT SUPERVISOR IMPLEMENTED LATER
# builds a plan from whatever ToolResults exist
# asks for missing tasks (agentic behavior) until all required tool outputs exist
# marks completed once it has all of them

from __future__ import annotations

from typing import Any


REQUIRED_TOOLS = ["weather", "places", "lodging", "transit"]


def _index_results(tool_results: list[dict]) -> dict[str, Any]:
    """
    tool_results: [{ "tool_name": "weather", "payload": {...} }, ...]
    returns dict keyed by tool_name
    """
    out: dict[str, Any] = {}
    for r in tool_results:
        name = (r.get("tool_name") or "").strip()
        payload = r.get("payload")
        if name:
            out[name] = payload
    return out


def run_supervisor(
    submission: dict,
    tool_results: list[dict],
    current_plan: dict | None,
) -> dict:
    """
    STUB supervisor (non-LLM) that:
    - Detects missing tool outputs
    - Requests tasks for missing tool outputs (agentic loop)
    - Produces a simple plan JSON for the dashboard to render
    """
    results = _index_results(tool_results)

    missing = [t for t in REQUIRED_TOOLS if t not in results]

    new_tasks: list[dict] = []
    for t in missing:
        # Task input_json can be used by tools later (Upgrade 1 now supported in worker)
        new_tasks.append(
            {
                "task_type": t,
                "input": {
                    "note": "requested_by_supervisor",
                    "destination": submission.get("desired_destination"),
                    "origin": submission.get("origin"),
                    "travel_dates": submission.get("travel_dates"),
                },
            }
        )

    # Build a plan object that is stable for the dashboard to consume later.
    # Keep this schema consistent going forward.
    plan: dict[str, Any] = {
        "trip": {
            "traveler_name": submission.get("traveler_name"),
            "origin": submission.get("origin"),
            "destination": submission.get("desired_destination"),
            "travel_dates": submission.get("travel_dates"),
            "budget": submission.get("budget"),
        },
        "sections": {
            "weather": results.get("weather"),
            "places": results.get("places"),
            "lodging": results.get("lodging"),
            "transit": results.get("transit"),
        },
        "meta": {
            "missing_tools": missing,
            "tool_count": len(results),
        },
    }

    # Status logic
    if missing:
        status = "processing"
        summary = f"Gathering data ({len(results)}/{len(REQUIRED_TOOLS)} complete)…"
    else:
        status = "completed"
        summary = "Plan ready (stub supervisor)."

    return {
        "status": status,
        "summary": summary,
        "plan": plan,
        "new_tasks": new_tasks,
    }