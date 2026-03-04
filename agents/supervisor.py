# Copyright Michael Mahoney, Edgar Falfan February 2026

# AI Supervisor — Groq-powered, replaces the rule-based stub.
# Called by run_worker.py → _run_supervisor_task() with this exact signature:
#
#   run_supervisor(submission_dict, tool_results, current_plan) -> dict

from __future__ import annotations

import json
import logging
import os
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)

REQUIRED_TOOLS = ["weather", "places", "transit"]

_client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1",
)

SYSTEM_PROMPT = """
You are Wayfinder's AI travel planning supervisor.

You receive a JSON object with:
  - "submission"   : traveler details
  - "tool_results" : summarized data already collected
  - "current_plan" : previous plan or null

Return ONLY a valid JSON object with NO markdown fences, NO extra text:

{
  "status": "processing" or "completed",
  "summary": "2-3 sentence summary",
  "new_tasks": [{"task_type": "weather|places|transit", "input": {}}],
  "plan": {
    "trip": {"traveler_name": "", "origin": "", "destination": "", "travel_dates": "", "budget": ""},
    "itinerary": [{"day": 1, "date": "", "morning": "", "afternoon": "", "evening": "", "lodging": "", "notes": ""}],
    "highlights": ["top pick 1", "top pick 2", "top pick 3"],
    "warnings": ["important warning"],
    "estimated_cost": "estimate or null",
    "sections": {},
    "meta": {"missing_tools": [], "tool_count": 0}
  }
}

Rules:
- status "completed" only when weather, places, AND transit all present
- Only add to new_tasks tools with NO result yet
- Use real place names and ratings from the data provided
- Return pure JSON only, absolutely no markdown or code fences
""".strip()


def _slim_tool_results(tool_results: list[dict]) -> list[dict]:
    """
    Reduce tool result payloads so they fit within Groq's context window.
    Keeps the most useful fields, drops coordinates and redundant data.
    """
    slimmed = []
    for r in tool_results:
        tool_name = r.get("tool_name", "")
        payload = r.get("payload", {})

        if tool_name == "places" and isinstance(payload, dict):
            items = payload.get("items", [])
            # Keep top 3 per category, only name/type/rating/distance
            by_type: dict[str, list] = {}
            for item in items:
                t = item.get("type", "other")
                by_type.setdefault(t, [])
                if len(by_type[t]) < 3:
                    by_type[t].append({
                        "name": item.get("name"),
                        "type": t,
                        "rating": item.get("rating"),
                        "distance_mi": item.get("distance_mi"),
                    })
            slim_items = [i for group in by_type.values() for i in group]
            slimmed.append({
                "tool_name": tool_name,
                "payload": {
                    "destination": payload.get("destination"),
                    "items": slim_items,
                }
            })

        elif tool_name == "weather" and isinstance(payload, dict):
            slimmed.append({
                "tool_name": tool_name,
                "payload": {
                    "location": payload.get("location"),
                    "current": payload.get("current", {}),
                }
            })

        elif tool_name == "transit" and isinstance(payload, dict):
            slimmed.append({
                "tool_name": tool_name,
                "payload": {
                    "origin": payload.get("origin"),
                    "destination": payload.get("destination"),
                    "options": payload.get("options", []),
                }
            })

        else:
            slimmed.append(r)

    return slimmed


def _strip_fences(raw: str) -> str:
    """Remove markdown code fences Groq sometimes wraps around JSON."""
    clean = raw.strip()
    if clean.startswith("```"):
        parts = clean.split("```")
        # parts[1] is the content between first and second ```
        content = parts[1] if len(parts) > 1 else clean
        if content.startswith("json"):
            content = content[4:]
        return content.strip()
    return clean


def run_supervisor(
    submission: dict,
    tool_results: list[dict],
    current_plan: dict | None,
) -> dict:
    slim_results = _slim_tool_results(tool_results)

    edit_request = submission.get("edit_request") if isinstance(submission, dict) else None

    user_message = json.dumps({
        "submission": submission,
        "tool_results": slim_results,
        "current_plan": current_plan,  # must save so edit requests work
        "edit_request": edit_request,
    }, indent=2)

    logger.info(
        f"[Supervisor] Calling Groq — submission={submission.get('id')} "
        f"tool_results={len(tool_results)}"
    )

    try:
        response = _client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=2048,
            timeout=30,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
        raw = response.choices[0].message.content
        clean = _strip_fences(raw)
        decision = json.loads(clean)

    except json.JSONDecodeError as exc:
        logger.error(f"[Supervisor] Groq returned non-JSON: {exc}\nRaw: {raw[:300]}")
        return _fallback(submission, tool_results, f"JSON parse error: {exc}")

    except Exception as exc:
        logger.error(f"[Supervisor] API error: {exc}")
        return _fallback(submission, tool_results, str(exc))

    decision.setdefault("status", "processing")
    decision.setdefault("summary", "Plan is being assembled…")
    decision.setdefault("new_tasks", [])
    decision.setdefault("plan", {})

    plan = decision["plan"]
    plan.setdefault("sections", {})

    # Store full (unslimmed) payloads in sections for dashboard rendering
    for r in tool_results:
        tool_name = r.get("tool_name", "")
        plan["sections"].setdefault(tool_name, r.get("payload"))

    results_index = {r["tool_name"] for r in tool_results if r.get("tool_name")}
    missing = [t for t in REQUIRED_TOOLS if t not in results_index]
    plan["meta"] = {
        "missing_tools": missing,
        "tool_count": len(results_index),
    }

    logger.info(
        f"[Supervisor] Decision: status={decision['status']} "
        f"new_tasks={[t['task_type'] for t in decision['new_tasks']]}"
    )

    return decision


def _index_results(tool_results: list[dict]) -> dict[str, Any]:
    return {
        (r.get("tool_name") or "").strip(): r.get("payload")
        for r in tool_results
        if r.get("tool_name")
    }


def _fallback(submission: dict, tool_results: list[dict], error_msg: str) -> dict:
    results = _index_results(tool_results)
    missing = [t for t in REQUIRED_TOOLS if t not in results]

    new_tasks = [
        {
            "task_type": t,
            "input": {
                "note": "requested_by_supervisor_fallback",
                "destination": submission.get("desired_destination"),
                "origin": submission.get("origin"),
                "travel_dates": submission.get("travel_dates"),
            },
        }
        for t in missing
    ]

    return {
        "status": "processing" if missing else "completed",
        "summary": f"Supervisor fallback active ({error_msg}). "
                   f"{len(results)}/{len(REQUIRED_TOOLS)} tools complete.",
        "new_tasks": new_tasks,
        "plan": {
            "trip": {
                "traveler_name": submission.get("traveler_name"),
                "origin": submission.get("origin"),
                "destination": submission.get("desired_destination"),
                "travel_dates": submission.get("travel_dates"),
                "budget": submission.get("budget"),
            },
            "sections": {t: results.get(t) for t in REQUIRED_TOOLS},
            "meta": {"missing_tools": missing, "tool_count": len(results)},
        },
    }