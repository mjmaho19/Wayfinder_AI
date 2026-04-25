# Copyright Michael Mahoney, Edgar Falfan February 2026

# AI Supervisor — Groq-powered, replaces the rule-based stub.
# Called by run_worker.py → _run_supervisor_task() with this exact signature:
#
#   run_supervisor(submission_dict, tool_results, current_plan) -> dict

from __future__ import annotations

import json
import logging
import os

from openai import OpenAI

from utils.plan_utils import (
    _strip_fences,
    _slim_current_plan,
    _slim_tool_results,
    _validate_grounding,
    _index_results,
    _get_tool_payload,
)

logger = logging.getLogger(__name__)

REQUIRED_TOOLS = ["weather", "places", "transit", "culture", "events"]

_client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1",
)

SYSTEM_PROMPT = """
You are Wayfinder's AI travel planning supervisor.

You receive a JSON object with:
  - "submission": traveler details (origin/destination/dates/budget/preferences/raw_request)
  - "tool_results": summarized tool payloads
  - "current_plan": previous plan or null
  - "edit_request": optional

Return ONLY valid JSON (no markdown, no fences, no extra text):

{
  "status": "processing" | "completed",
  "summary": "2-3 sentence summary",
  "new_tasks": [{"task_type":"weather|places|transit|culture|events", "input": {}}],
  "plan": {
    "trip": {"traveler_name":"","origin":"","destination":"","travel_dates":"","budget":""},

    "preference_profile": {
      "food_likes": [],
      "activity_likes": [],
      "budget_style": "budget|mid|splurge|unknown",
      "pace": "relaxed|moderate|packed|unknown",
      "notes": ""
    },

    "curated_itinerary": [
      {
        "day": 1,
        "date": "",
        "lodging": {"name": "", "type": "hotel"},
        "meals": {
            "breakfast": {"name": "", "type": "restaurant", "time": "9:00 AM"},
            "lunch":     {"name": "", "type": "restaurant", "time": "1:00 PM"},
            "dinner":    {"name": "", "type": "restaurant", "time": "7:00 PM"}
        },
        "activities": [
            {"name": "", "type": "poi", "time": "10:30 AM"},
            {"name": "", "type": "poi", "time": "2:30 PM"}
        ],
        "why_these": "<=120 characters>"
      }
    ],

    "highlights": ["", "", ""],
    "warnings": [],
    "estimated_cost": "estimate or null",

    "sections": {},
    "meta": {"missing_tools": [], "tool_count": 0}
  }
}

HARD RULES:
- Mark status "completed" ONLY when weather, places, AND transit results exist.
- Only add new_tasks for tools with NO result yet.
- Grounding: every lodging/meal/activity name in curated_itinerary MUST match an item name in places items provided in tool_results.
  If you cannot find matches, leave the field blank AND add a warning AND request new places task.
- Do NOT invent place names.
- Keep curated_itinerary decisions aligned with budget_style and preferences.
- You MUST produce a curated_itinerary entry for EVERY day in the travel date range.
- If travel_dates spans N days, curated_itinerary MUST have length N.
- Do NOT stop early due to limited places.
- If there is at least one grounded candidate of the needed type, re-use grounded candidates to fill all days rather than leaving blanks.
- Avoid repeating the same restaurant in consecutive meal slots when possible, but filling the itinerary is more important than avoiding repetition.
- If dates are ambiguous, assume inclusive range and set a warning.
- Always request culture and events tasks when they have no result yet.
- Schedule all activities between 9:00 AM and 9:00 PM.
- Meals are fixed: breakfast 9:00 AM, lunch 1:00 PM, dinner 7:00 PM. Each meal takes 1 hour.
- Activities fill the remaining gaps: activity_1 at 10:30 AM, activity_2 at 2:30 PM.
- Never schedule anything after 9:00 PM.

When choosing places:
- Prefer higher rating
- Prefer higher user_rating_count
- Prefer shorter distance
- Respect budget_style
- Re-use grounded places when necessary
- Blank a field only if there are truly no grounded candidates for that slot type
""".strip()


def run_supervisor(
    submission: dict,
    tool_results: list[dict],
    current_plan: dict | None,
) -> dict:

    slim_results = _slim_tool_results(tool_results)
    current_plan = _slim_current_plan(current_plan)

    edit_request = submission.get("edit_request") if isinstance(submission, dict) else None

    user_message = json.dumps({
        "submission": submission,
        "tool_results": slim_results,
        "current_plan": current_plan,
        "edit_request": edit_request,
    }, separators=(",", ":"), ensure_ascii=False)

    logger.info(
        f"[Supervisor] Calling Groq — submission={submission.get('id')} "
        f"tool_results={len(tool_results)}"
    )

    try:
        response = _client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=4096,
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
        logger.error(f"[Supervisor] Groq returned non-JSON: {exc}\nRaw:\n{raw}")
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

    _validate_grounding(plan, tool_results)

    # Store full (unslimmed) payloads in sections for dashboard rendering
    for r in tool_results:
        tool_name = r.get("tool_name", "")
        val = _get_tool_payload(r)
        plan["sections"].setdefault(tool_name, val)

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