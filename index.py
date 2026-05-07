# Copyright Michael Mahoney, Edgar Falfan February 2026

from __future__ import annotations

from datetime import datetime
import os
import json
import re

from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

from utils.plan_utils import _safe_json_loads, _canonical_item_type, _sort_place_candidates

load_dotenv()

app = Flask(__name__)
application = app

# Config
app.config["SECRET_KEY"] = os.getenv("FLASK_KEY", "dev-only-change-me")

database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL is not set. Add it to your .env file.")

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["FLASK_APP"] = "index.py"

db = SQLAlchemy(app)
migrate = Migrate(app, db)


# Models

class WayfinderSubmission(db.Model):
    __tablename__ = "wayfinder_submission"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Core traveler info
    traveler_name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), nullable=True)

    # Travel-specific fields
    origin = db.Column(db.String(200), nullable=True)
    desired_destination = db.Column(db.String(200), nullable=True)
    travel_dates = db.Column(db.String(200), nullable=True)
    budget = db.Column(db.String(100), nullable=True)

    # Freeform input
    preferences = db.Column(db.Text, nullable=True)
    raw_request = db.Column(db.Text, nullable=False)

    # AI pipeline fields
    status = db.Column(db.String(50), nullable=False, default="pending")
    agent_result = db.Column(db.Text, nullable=True)


class AgentTask(db.Model):
    __tablename__ = "agent_task"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    submission_id = db.Column(db.Integer, db.ForeignKey("wayfinder_submission.id"), nullable=False, index=True)
    task_type = db.Column(db.String(50), nullable=False)  # e.g., "weather", "places", "transit"
    status = db.Column(db.String(50), nullable=False, default="pending")  # pending/running/completed/failed

    input_json = db.Column(db.Text, nullable=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=3)
    worker_id = db.Column(db.String(200), nullable=True)

    # fields for debugging / workers
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    error = db.Column(db.Text, nullable=True)

    submission = db.relationship("WayfinderSubmission", backref=db.backref("tasks", lazy=True))


class ToolResult(db.Model):
    __tablename__ = "tool_result"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    submission_id = db.Column(db.Integer, db.ForeignKey("wayfinder_submission.id"), nullable=False, index=True)
    tool_name = db.Column(db.String(50), nullable=False)  # e.g., "weather_api", "places_api"
    # Keep it as TEXT for now; store JSON as a string (simple & works everywhere)
    result_json = db.Column(db.Text, nullable=False)

    submission = db.relationship("WayfinderSubmission", backref=db.backref("tool_results", lazy=True))


class TripPlan(db.Model):
    __tablename__ = "trip_plan"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    submission_id = db.Column(db.Integer, db.ForeignKey("wayfinder_submission.id"), nullable=False, unique=True)
    # store the current best plan as JSON string for now
    plan_json = db.Column(db.Text, nullable=True)
    summary = db.Column(db.Text, nullable=True)

    submission = db.relationship("WayfinderSubmission", backref=db.backref("trip_plan", uselist=False))


class PlanEdit(db.Model):
    __tablename__ = "plan_edit"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    submission_id = db.Column(db.Integer, db.ForeignKey("wayfinder_submission.id"), nullable=False, index=True)

    source = db.Column(db.String(50), nullable=False, default="chat")  # chat/dashboard/etc
    status = db.Column(db.String(50), nullable=False, default="pending")  # pending/applied/failed/rejected

    user_message = db.Column(db.Text, nullable=False)
    assistant_reply = db.Column(db.Text, nullable=True)

    # optional: later store structured patch/diff
    edit_json = db.Column(db.Text, nullable=True)

    submission = db.relationship("WayfinderSubmission", backref=db.backref("plan_edits", lazy=True))


def _canonicalize_plan_item_types(plan: dict | None) -> dict | None:
    """
    Normalize itinerary item types in a trip plan.

    Forces lodging items to use the "hotel" type, meal items to use the
    "restaurant" type, and activity items to use the "poi" type.

    Args:
        plan: Trip plan dictionary to normalize.

    Returns:
        A copied and updated plan dictionary, or the original value if it is
        not a dictionary.
    """
    if not isinstance(plan, dict):
        return plan

    updated = dict(plan)
    itinerary = []

    for day in updated.get("curated_itinerary", []) or []:
        if not isinstance(day, dict):
            itinerary.append(day)
            continue

        d = dict(day)

        lodging = dict(d.get("lodging") or {})
        if lodging:
            lodging["type"] = "hotel"
            d["lodging"] = lodging

        meals = dict(d.get("meals") or {})
        for slot in ["breakfast", "lunch", "dinner"]:
            meal = dict(meals.get(slot) or {})
            if meal:
                meal["type"] = "restaurant"
                meals[slot] = meal
        d["meals"] = meals

        activities = []
        for act in d.get("activities", []) or []:
            a = dict(act or {})
            if a:
                a["type"] = "poi"
            activities.append(a)
        d["activities"] = activities

        itinerary.append(d)

    updated["curated_itinerary"] = itinerary
    if updated.get("itinerary"):
        updated["itinerary"] = itinerary

    return updated


def _clean_destination_text(value: str | None) -> str | None:
    """
    Clean a destination string from a chat-based edit request.

    Removes common leading phrases such as "a trip to", "trip to", or "to",
    as well as trailing punctuation and the word "instead".

    Args:
        value: Raw destination text from the user or edit payload.

    Returns:
        A cleaned destination string, None if the result is empty, or the
        original value if no value was provided.
    """
    if not value:
        return value

    d = value.strip()

    d = re.sub(r"^[Aa]\s+trip\s+to\s+", "", d, flags=re.IGNORECASE)
    d = re.sub(r"^[Tt]rip\s+to\s+", "", d, flags=re.IGNORECASE)
    d = re.sub(r"^[Tt]o\s+", "", d, flags=re.IGNORECASE)
    d = re.sub(r"\?+$", "", d)
    d = re.sub(r"\.+$", "", d)
    d = re.sub(r"\s+instead$", "", d, flags=re.IGNORECASE)
    d = d.strip()

    return d or None


def _get_current_slot_item(day_plan: dict, slot: str) -> dict:
    """
    Get the current itinerary item for a specific day and slot.

    Supports lodging, meal slots, and the first or second activity slot.

    Args:
        day_plan: Dictionary representing one day of the itinerary.
        slot: Slot name such as "lodging", "breakfast", "lunch",
            "dinner", "activity_1", or "activity_2".

    Returns:
        A dictionary containing the current item's name and type. If the
        slot or item is missing, returns empty default values.
    """
    if not isinstance(day_plan, dict):
        return {"name": "", "type": ""}

    if slot == "lodging":
        item = day_plan.get("lodging") or {}
        return {
            "name": item.get("name") or "",
            "type": item.get("type") or "hotel",
        }

    if slot in {"breakfast", "lunch", "dinner"}:
        item = ((day_plan.get("meals") or {}).get(slot) or {})
        return {
            "name": item.get("name") or "",
            "type": item.get("type") or "restaurant",
        }

    if slot == "activity_1":
        acts = day_plan.get("activities") or []
        item = acts[0] if len(acts) > 0 and isinstance(acts[0], dict) else {}
        return {
            "name": item.get("name") or "",
            "type": item.get("type") or "poi",
        }

    if slot == "activity_2":
        acts = day_plan.get("activities") or []
        item = acts[1] if len(acts) > 1 and isinstance(acts[1], dict) else {}
        return {
            "name": item.get("name") or "",
            "type": item.get("type") or "poi",
        }

    return {"name": "", "type": ""}


def _normalize_plan(plan_dict: dict | None) -> dict | None:
    """
    Normalize the structure of a trip plan dictionary.

    Ensures the plan has matching "itinerary" and "curated_itinerary" fields,
    initializes missing sections, and canonicalizes itinerary item types.

    Args:
        plan_dict: Trip plan dictionary to normalize.

    Returns:
        A normalized trip plan dictionary, or None if the input is invalid.
    """
    if not isinstance(plan_dict, dict):
        return None

    plan = dict(plan_dict)

    if not plan.get("itinerary") and plan.get("curated_itinerary"):
        plan["itinerary"] = plan["curated_itinerary"]

    if not plan.get("curated_itinerary") and plan.get("itinerary"):
        plan["curated_itinerary"] = plan["itinerary"]

    if not isinstance(plan.get("curated_itinerary"), list):
        plan["curated_itinerary"] = []

    if not isinstance(plan.get("sections"), dict):
        plan["sections"] = {}

    plan = _canonicalize_plan_item_types(plan)
    return plan


def _extract_day_number(user_message: str) -> int | None:
    """
    Extract a day number from a user message.

    Looks for text in the format "day N", such as "day 2".

    Args:
        user_message: Message text from the user.

    Returns:
        The extracted day number as an integer, or None if no day number
        is found.
    """
    m = re.search(r"\bday\s+(\d+)\b", user_message, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _detect_specific_edit_request(user_message: str) -> dict | None:
    """
    Detect whether a user message is asking for a specific itinerary edit.

    Looks for edit-related words, a day number, and a target slot such as
    lodging, a meal, or an activity.

    Args:
        user_message: Message text from the user.

    Returns:
        A structured edit request dictionary if a specific edit is detected,
        otherwise None.
    """
    text = (user_message or "").strip().lower()
    if not text:
        return None

    edit_words = ["change", "swap", "replace", "different", "instead", "another"]
    if not any(word in text for word in edit_words):
        return None

    day = _extract_day_number(text)
    if day is None:
        return None

    if "hotel" in text or "lodging" in text or "stay" in text:
        return {
            "intent": "specific_itinerary_edit",
            "day": day,
            "slot": "lodging",
            "item_type": "hotel",
            "user_request": user_message,
        }

    for meal_slot in ["breakfast", "lunch", "dinner"]:
        if meal_slot in text:
            return {
                "intent": "specific_itinerary_edit",
                "day": day,
                "slot": meal_slot,
                "item_type": "restaurant",
                "user_request": user_message,
            }

    if "activity 1" in text or "first activity" in text:
        return {
            "intent": "specific_itinerary_edit",
            "day": day,
            "slot": "activity_1",
            "item_type": "poi",
            "user_request": user_message,
        }

    if "activity 2" in text or "second activity" in text:
        return {
            "intent": "specific_itinerary_edit",
            "day": day,
            "slot": "activity_2",
            "item_type": "poi",
            "user_request": user_message,
        }

    if "activity" in text or "attraction" in text or "museum" in text or "place" in text:
        return {
            "intent": "specific_itinerary_edit",
            "day": day,
            "slot": "activity_1",
            "item_type": "poi",
            "user_request": user_message,
        }

    return None


def _candidate_matches_user_request(item: dict, user_message: str) -> bool:
    """
    Check whether a candidate place matches the user's requested preferences.

    Compares soft keywords from the user message, such as cuisine, budget,
    or activity type, against the candidate place metadata.

    Args:
        item: Place result dictionary.
        user_message: User's edit request or preference message.

    Returns:
        True if the candidate place matches the request, or if no specific
        soft keyword was requested. Otherwise, False.
    """
    text = (user_message or "").lower()

    haystack_parts = [
        item.get("name") or "",
        item.get("primary_type") or "",
        item.get("editorial_summary") or "",
        item.get("address") or "",
        " ".join(item.get("types") or []),
        item.get("price_level") or "",
    ]
    haystack = " ".join(str(x).lower() for x in haystack_parts if x)

    soft_keywords = [
        "italian", "southern", "seafood", "steak", "museum", "park", "casino",
        "fancy", "luxury", "cheap", "budget", "upscale", "romantic"
    ]
    requested = [k for k in soft_keywords if k in text]
    if not requested:
        return True

    return any(k in haystack for k in requested)


def _get_candidate_places(plan: dict, edit_request: dict, limit: int = 8) -> list[dict]:
    """
    Get candidate replacement places for a specific itinerary edit.

    Filters places from the plan by item type, removes the current item,
    applies user preference matching, sorts the candidates, and returns a
    compact list of place details.

    Args:
        plan: Current trip plan dictionary.
        edit_request: Structured edit request dictionary.
        limit: Maximum number of candidate places to return.

    Returns:
        A list of compact candidate place dictionaries.
    """

    sections = plan.get("sections") or {}
    places = sections.get("places") or {}
    items = places.get("items") or []

    wanted_type = _canonical_item_type(edit_request.get("item_type"))
    user_message = edit_request.get("user_request") or ""

    day_number = edit_request.get("day")
    slot = edit_request.get("slot") or ""
    day_plan = _get_day_plan(plan, day_number) if isinstance(day_number, int) else None
    current_item = _get_current_slot_item(day_plan or {}, slot)
    current_name = (current_item.get("name") or "").strip()

    filtered = []
    for item in items:
        item_name = (item.get("name") or "").strip()

        if _canonical_item_type(item.get("type")) != wanted_type:
            continue
        if not item_name:
            continue
        if current_name and item_name == current_name:
            continue
        if not _candidate_matches_user_request(item, user_message):
            continue

        filtered.append(item)

    if not filtered:
        filtered = [
            item for item in items
            if _canonical_item_type(item.get("type")) == wanted_type
            and (item.get("name") or "").strip()
            and ((item.get("name") or "").strip() != current_name if current_name else True)
        ]

    filtered = sorted(filtered, key=_sort_place_candidates)

    compact = []
    for item in filtered[:limit]:
        compact.append({
            "name": item.get("name"),
            "type": item.get("type"),
            "rating": item.get("rating"),
            "user_rating_count": item.get("user_rating_count"),
            "price_level": item.get("price_level"),
            "distance_mi": item.get("distance_mi"),
            "primary_type": item.get("primary_type"),
        })
    return compact


def _get_day_plan(plan: dict, day_number: int) -> dict | None:
    """
    Retrieve one day from the trip itinerary.

    Args:
        plan: Current trip plan dictionary.
        day_number: Day number to look up.

    Returns:
        The matching day plan dictionary, or None if the day is not found.
    """
    for day in plan.get("curated_itinerary", []):
        if day.get("day") == day_number:
            return day
    return None


def _build_general_chat_context(plan: dict) -> dict:
    """
    Build a compact plan context for general chat responses.

    Includes the trip overview, preferences, highlights, warnings, itinerary,
    and slimmed-down place details for use by the chat agent.

    Args:
        plan: Current trip plan dictionary.

    Returns:
        A compact dictionary containing the information needed for general
        itinerary chat.
    """
    sections = plan.get("sections") or {}
    places = sections.get("places") or {}
    place_items = places.get("items") or []

    slim_place_details = []
    for item in place_items:
        if not isinstance(item, dict):
            continue

        item_type = _canonical_item_type(item.get("type"))
        if item_type not in {"restaurant", "hotel", "poi", "shop", "bathroom"}:
            continue

        slim_place_details.append({
            "name": item.get("name"),
            "type": item_type,
            "editorial_summary": item.get("editorial_summary"),
            "rating": item.get("rating"),
            "user_rating_count": item.get("user_rating_count"),
            "price_level": item.get("price_level"),
            "primary_type": item.get("primary_type"),
            "address": item.get("address"),
            "distance_mi": item.get("distance_mi"),
        })

    return {
        "trip": plan.get("trip"),
        "preference_profile": plan.get("preference_profile"),
        "highlights": plan.get("highlights"),
        "warnings": plan.get("warnings"),
        "curated_itinerary": plan.get("curated_itinerary"),
        "place_details": slim_place_details,
    }


def _build_specific_edit_context(plan: dict, edit_request: dict) -> dict:
    """
    Build a compact context for a specific itinerary edit request.

    Includes the requested edit, the current item being replaced, the current
    day plan, and candidate replacement places.

    Args:
        plan: Current trip plan dictionary.
        edit_request: Structured edit request dictionary.

    Returns:
        A compact dictionary containing the information needed to propose
        a specific itinerary edit.
    """
    day_number = edit_request["day"]
    day_plan = _get_day_plan(plan, day_number)
    current_item = _get_current_slot_item(day_plan or {}, edit_request.get("slot") or "")
    old_name = (current_item.get("name") or "").strip()
    candidates = _get_candidate_places(plan, edit_request, limit=8)

    return {
        "trip": plan.get("trip"),
        "preference_profile": plan.get("preference_profile"),
        "requested_edit": {
            **edit_request,
            "old_name": old_name,
        },
        "target": {
            "day": day_number,
            "slot": edit_request.get("slot"),
            "item_type": edit_request.get("item_type"),
            "current_item": current_item,
        },
        "current_day_plan": day_plan,
        "candidate_places": candidates,
    }

def _validate_proposed_edit(plan: dict, proposed_edit: dict) -> tuple[bool, str]:
    """
    Validate a proposed itinerary edit before applying it.

    Ensures the edit has a valid day, slot, item type, replacement value,
    and that the replacement is grounded in the allowed places from the plan.

    Args:
        plan: Current trip plan dictionary.
        proposed_edit: Proposed edit dictionary returned by the chat agent.

    Returns:
        A tuple containing a boolean success value and an error message.
        If validation succeeds, the error message is an empty string.
    """
    if not isinstance(proposed_edit, dict):
        return False, "Invalid proposed edit payload."

    day = proposed_edit.get("day")
    slot = proposed_edit.get("slot")
    item_type = _canonical_item_type(proposed_edit.get("item_type"))
    replace_with = (proposed_edit.get("replace_with") or "").strip()

    if not isinstance(day, int):
        return False, "Missing or invalid day."
    if slot not in {"lodging", "breakfast", "lunch", "dinner", "activity_1", "activity_2"}:
        return False, "Invalid slot."
    if item_type not in {"hotel", "restaurant", "poi"}:
        return False, "Invalid item type."
    if not replace_with:
        return False, "No replacement was chosen."

    day_plan = _get_day_plan(plan, day)
    if not day_plan:
        return False, f"Day {day} not found in itinerary."

    current_item = _get_current_slot_item(day_plan, slot)
    current_name = (current_item.get("name") or "").strip()

    if current_name and replace_with == current_name:
        return False, "Replacement must be different from the current item."

    sections = plan.get("sections") or {}
    places = sections.get("places") or {}
    items = places.get("items") or []

    wanted_type = _canonical_item_type(item_type)

    allowed_names = {
        (item.get("name") or "").strip()
        for item in items
        if _canonical_item_type(item.get("type")) == wanted_type and item.get("name")
    }

    if replace_with not in allowed_names:
        return False, "Replacement is not grounded in allowed places."

    return True, ""


def _apply_specific_edit_to_plan(plan: dict, proposed_edit: dict) -> dict:
    """
    Apply a validated specific edit to a trip plan.

    Updates the requested lodging, meal, or activity slot in the itinerary
    and records a warning noting that the chat edit was applied.

    Args:
        plan: Current trip plan dictionary.
        proposed_edit: Validated edit dictionary containing the day, slot,
            item type, and replacement name.

    Returns:
        A copied and updated trip plan dictionary.
    """
    updated = dict(plan)
    itinerary = [dict(day) for day in (updated.get("curated_itinerary") or [])]

    day = proposed_edit["day"]
    slot = proposed_edit["slot"]
    item_type = _canonical_item_type(proposed_edit["item_type"])
    replace_with = proposed_edit["replace_with"]

    for idx, day_plan in enumerate(itinerary):
        if day_plan.get("day") != day:
            continue

        day_copy = dict(day_plan)

        if slot == "lodging":
            day_copy["lodging"] = {"name": replace_with, "type": item_type}

        elif slot in {"breakfast", "lunch", "dinner"}:
            meals = dict(day_copy.get("meals") or {})
            meals[slot] = {"name": replace_with, "type": item_type}
            day_copy["meals"] = meals

        elif slot in {"activity_1", "activity_2"}:
            acts = list(day_copy.get("activities") or [])
            target_index = 0 if slot == "activity_1" else 1
            while len(acts) <= target_index:
                acts.append({"name": "", "type": "poi"})
            acts[target_index] = {"name": replace_with, "type": item_type}
            day_copy["activities"] = acts

        itinerary[idx] = day_copy
        break

    updated["curated_itinerary"] = itinerary
    updated["itinerary"] = itinerary

    warnings = list(updated.get("warnings") or [])
    warnings.append(f"Chat edit applied: day {day} {slot} -> {replace_with}")
    updated["warnings"] = warnings

    return updated


# App routes
@app.route("/", methods=["GET"])
def home():
    """Redirect root to travel request page."""
    return redirect(url_for("request_trip"))


@app.route("/request", methods=["GET", "POST"])
def request_trip():
    """
    Display the trip request form or create a new trip request.

    For GET requests, renders the request form. For POST requests, validates
    the submitted trip information, creates a WayfinderSubmission, seeds the
    initial agent tasks, and redirects to the dashboard.

    Returns:
        The rendered request page or a redirect response.
    """
    if request.method == "POST":
        traveler_name = (request.form.get("traveler_name") or "").strip()
        email = (request.form.get("email") or "").strip().lower() or None
        origin = (request.form.get("origin") or "").strip() or None
        desired_destination = (request.form.get("desired_destination") or "").strip() or None
        travel_dates = (request.form.get("travel_dates") or "").strip() or None
        budget = (request.form.get("budget") or "").strip() or None
        preferences = (request.form.get("preferences") or "").strip() or None
        raw_request = (request.form.get("raw_request") or "").strip()

        if not traveler_name or not raw_request:
            flash("Please include your name and trip description.", "danger")
            return redirect(url_for("request_trip"))

        # Create submission
        submission = WayfinderSubmission(
            traveler_name=traveler_name,
            email=email,
            origin=origin,
            desired_destination=desired_destination,
            travel_dates=travel_dates,
            budget=budget,
            preferences=preferences,
            raw_request=raw_request,
            status="pending",
        )
        db.session.add(submission)
        db.session.commit()

        starter_tasks = ["weather", "places", "transit", "alerts"]
        for t in starter_tasks:
            db.session.add(
                AgentTask(
                    submission_id=submission.id,
                    task_type=t,
                    status="pending",
                    input_json=None,
                    attempts=0,
                    max_attempts=3,
                )
            )

        # Add supervisor_update so the plan starts forming immediately
        db.session.add(
            AgentTask(
                submission_id=submission.id,
                task_type="supervisor_update",
                status="pending",
                input_json=json.dumps({"reason": "new_submission"}),
                attempts=0,
                max_attempts=3,
            )
        )

        db.session.commit()

        flash("Trip request submitted! View the dashboard for updates.", "success")
        return redirect(url_for("dashboard"))

    return render_template("request.html")


@app.route("/dashboard", methods=["GET"])
def dashboard():
    """Render the Wayfinder dashboard."""
    return render_template("wayfinder_dashboard.html")


@app.route("/api/weather", methods=["GET"])
def weather():
    """
    Return current and daily weather data for the latest trip destination.

    Uses the latest WayfinderSubmission destination, geocodes it with
    Open-Meteo, and fetches a seven-day forecast. Falls back to New York
    if no destination is available or geocoding fails.

    Returns:
        A JSON response containing the resolved location, current weather,
        and daily forecast data.
    """
    import requests as req

    latest = WayfinderSubmission.query.order_by(
        WayfinderSubmission.created_at.desc()
    ).first()
    destination = latest.desired_destination if latest and latest.desired_destination else None

    if destination:
        geo = req.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": destination, "count": 1}, timeout=10
        ).json()
        if geo.get("results"):
            r = geo["results"][0]
            lat, lon = r["latitude"], r["longitude"]
            resolved = destination
        else:
            # Geocoding failed, fall back to NYC
            lat, lon, resolved = 40.7128, -74.0060, "New York"
    else:
        lat, lon, resolved = 40.7128, -74.0060, "New York"

    weather_data = req.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat, "longitude": lon,
            "current": "temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
            "forecast_days": 7,
            "timezone": "auto",
        }, timeout=10
    ).json()

    return jsonify({
        "location": resolved,
        "current": weather_data.get("current", {}),
        "daily": weather_data.get("daily", {}),
    })

@app.route("/api/chat", methods=["POST"])
def chat():
    """
    Handle chat messages and itinerary edit requests.

    Loads the relevant trip submission and plan, detects whether the user is
    asking a general question, requesting a full trip rebuild, or applying a
    specific itinerary edit. Saves chat interactions as PlanEdit records.

    Returns:
        A JSON response containing the assistant reply and any edit metadata.
    """
    from agents.chat_agent import chat_with_plan

    data = request.get_json() or {}
    messages = data.get("messages", []) or []
    plan_context = data.get("plan_context", "") or ""
    submission_id = data.get("submission_id")

    apply_changes = bool(data.get("apply_changes", False))
    edit = data.get("edit") or {}

    apply_specific_edit = bool(data.get("apply_specific_edit", False))
    proposed_edit = data.get("proposed_edit") or {}

    if not submission_id:
        latest = WayfinderSubmission.query.order_by(WayfinderSubmission.created_at.desc()).first()
        if not latest:
            return jsonify({"reply": "No trip found yet. Please submit a trip request first."})
        submission_id = latest.id

    submission = WayfinderSubmission.query.get(submission_id)
    if not submission:
        return jsonify({"reply": f"Submission {submission_id} not found."}), 404

    user_last = None
    for m in reversed(messages):
        if m.get("role") == "user":
            user_last = (m.get("content") or "").strip()
            break
    user_last = user_last or "User sent an empty message."

    trip_plan_row = TripPlan.query.filter_by(submission_id=submission.id).first()

    plan_dict = None
    if trip_plan_row and trip_plan_row.plan_json:
        plan_dict = _safe_json_loads(trip_plan_row.plan_json)
    if not plan_dict and plan_context:
        plan_dict = _safe_json_loads(plan_context)

    plan_dict = _normalize_plan(plan_dict)

    if apply_changes:
        cleaned_destination = _clean_destination_text(edit.get("desired_destination"))

        new = WayfinderSubmission(
            traveler_name=edit.get("traveler_name") or submission.traveler_name,
            email=edit.get("email") or submission.email,

            origin=edit.get("origin") or submission.origin,
            desired_destination=cleaned_destination or submission.desired_destination,
            travel_dates=edit.get("travel_dates") or submission.travel_dates,
            budget=edit.get("budget") or submission.budget,

            preferences=edit.get("preferences") or submission.preferences,

            raw_request=(
                (edit.get("raw_request") or submission.raw_request or "")
                + f"\n\n[Chat edit confirmed] {user_last}"
            ),

            status="pending",
            agent_result=None,
        )
        db.session.add(new)
        db.session.commit()

        pe = PlanEdit(
            submission_id=submission.id,
            source="chat",
            status="applied",
            user_message=user_last,
            assistant_reply="Confirmed. I’m updating the trip and rebuilding the plan.",
            edit_json=json.dumps({**edit, "new_submission_id": new.id}) if edit else json.dumps({"new_submission_id": new.id}),
        )
        db.session.add(pe)
        db.session.commit()

        for t in ["weather", "places", "transit", "alerts", "supervisor_update"]:
            db.session.add(
                AgentTask(
                    submission_id=new.id,
                    task_type=t,
                    status="pending",
                    input_json=None,
                    attempts=0,
                    max_attempts=3,
                )
            )
        db.session.commit()

        return jsonify({
            "reply": "Confirmed. I’m updating the trip and rebuilding the plan.",
            "apply_changes": True,
            "plan_edit_id": pe.id,
            "new_submission_id": new.id,
            "queued_pipeline": True,
        })

    if apply_specific_edit and plan_dict and proposed_edit:
        ok, error_msg = _validate_proposed_edit(plan_dict, proposed_edit)
        if not ok:
            return jsonify({
                "reply": f"I couldn't apply that change automatically: {error_msg}",
                "apply_changes": False,
                "applied_specific_edit": False,
                "queued_supervisor_update": False,
            })

        updated_plan = _apply_specific_edit_to_plan(plan_dict, proposed_edit)

        if trip_plan_row:
            trip_plan_row.plan_json = json.dumps(updated_plan, ensure_ascii=False)
            if updated_plan.get("summary"):
                trip_plan_row.summary = updated_plan.get("summary") or trip_plan_row.summary
        else:
            trip_plan_row = TripPlan(
                submission_id=submission.id,
                plan_json=json.dumps(updated_plan, ensure_ascii=False),
                summary=None,
            )
            db.session.add(trip_plan_row)

        pe = PlanEdit(
            submission_id=submission.id,
            source="chat",
            status="applied",
            user_message=user_last,
            assistant_reply=(
                f"Done — day {proposed_edit['day']} {proposed_edit['slot']} "
                f"has been changed to {proposed_edit['replace_with']}."
            ),
            edit_json=json.dumps(proposed_edit),
        )
        db.session.add(pe)
        db.session.commit()

        return jsonify({
            "reply": pe.assistant_reply,
            "apply_changes": False,
            "applied_specific_edit": True,
            "plan_edit_id": pe.id,
            "queued_supervisor_update": False,
        })

    specific_edit_request = _detect_specific_edit_request(user_last)

    if plan_dict and specific_edit_request:
        compact_context = _build_specific_edit_context(plan_dict, specific_edit_request)

        chat_result = chat_with_plan(
            messages=messages,
            plan_context=json.dumps(compact_context, ensure_ascii=False),
            structured_edit=True,
        )

        reply = chat_result.get("reply") or "I found an itinerary update."
        proposed_edit = chat_result.get("proposed_edit")

        pe = PlanEdit(
            submission_id=submission.id,
            source="chat",
            status="pending",
            user_message=user_last,
            assistant_reply=reply,
            edit_json=json.dumps(proposed_edit) if proposed_edit else None,
        )
        db.session.add(pe)
        db.session.commit()

        if proposed_edit:
            ok, error_msg = _validate_proposed_edit(plan_dict, proposed_edit)
            if not ok:
                pe.status = "failed"
                pe.assistant_reply = f"{reply} I couldn't validate that change automatically: {error_msg}"
                db.session.commit()

                return jsonify({
                    "reply": pe.assistant_reply,
                    "apply_changes": False,
                    "applied_specific_edit": False,
                    "plan_edit_id": pe.id,
                    "queued_supervisor_update": False,
                    "proposed_edit": None,
                })

            return jsonify({
                "reply": reply,
                "apply_changes": False,
                "applied_specific_edit": False,
                "plan_edit_id": pe.id,
                "queued_supervisor_update": False,
                "proposed_edit": proposed_edit,
            })

        return jsonify({
            "reply": reply,
            "apply_changes": False,
            "applied_specific_edit": False,
            "plan_edit_id": pe.id,
            "queued_supervisor_update": False,
            "proposed_edit": None,
        })

    if plan_dict:
        compact_context = _build_general_chat_context(plan_dict)
        final_plan_context = json.dumps(compact_context, ensure_ascii=False)
    else:
        final_plan_context = ""

    chat_result = chat_with_plan(
        messages=messages,
        plan_context=final_plan_context,
        structured_edit=False,
    )
    reply = chat_result.get("reply") or "I can help with your trip."

    pe = PlanEdit(
        submission_id=submission.id,
        source="chat",
        status="pending",
        user_message=user_last,
        assistant_reply=reply,
        edit_json=json.dumps(edit) if edit else None,
    )
    db.session.add(pe)
    db.session.commit()

    return jsonify({
        "reply": reply,
        "apply_changes": False,
        "queued_supervisor_update": True,
        "plan_edit_id": pe.id,
    })


@app.route("/api/latest", methods=["GET"])
def api_latest():
    """
     Return the latest trip submission and related planning data.

     Includes the latest submission details, agent tasks, current trip plan,
     and saved tool results for dashboard polling.

     Returns:
         A JSON response containing the latest trip state, or None if no
         submission exists yet.
     """
    latest = WayfinderSubmission.query.order_by(WayfinderSubmission.created_at.desc()).first()
    if not latest:
        return jsonify({"ok": True, "latest": None})

    tasks = AgentTask.query.filter_by(submission_id=latest.id).order_by(AgentTask.created_at.asc()).all()
    plan = TripPlan.query.filter_by(submission_id=latest.id).first()
    results = ToolResult.query.filter_by(submission_id=latest.id).order_by(ToolResult.created_at.asc()).all()

    return jsonify(
        {
            "ok": True,
            "latest": {
                "id": latest.id,
                "created_at": latest.created_at.isoformat(),
                "traveler_name": latest.traveler_name,
                "email": latest.email,
                "origin": latest.origin,
                "desired_destination": latest.desired_destination,
                "travel_dates": latest.travel_dates,
                "budget": latest.budget,
                "preferences": latest.preferences,
                "raw_request": latest.raw_request,
                "status": latest.status,
                "agent_result": latest.agent_result,
                "tasks": [
                    {"id": t.id, "task_type": t.task_type, "status": t.status}
                    for t in tasks
                ],
                "plan": None if not plan else {
                    "summary": plan.summary,
                    "plan_json": plan.plan_json,
                    "updated_at": plan.updated_at.isoformat(),
                },
                "tool_results": [
                    {"id": r.id, "tool_name": r.tool_name, "result_json": r.result_json}
                    for r in results
                ],
            },
        }
    )

@app.route("/api/transit", methods=["GET"])
def transit():
    """
    Return transit route options for a requested origin and destination.

    Reads origin, destination, and mode from query parameters and passes them
    to the transit search tool.

    Returns:
        A JSON response containing transit routes, or an error response if
        origin or destination is missing.
    """
    from tools.transit_tool import search
    origin = request.args.get("origin", "")
    destination = request.args.get("destination", "")
    mode = request.args.get("mode", "BUS")
    if not origin or not destination:
        return jsonify({"error": "origin and destination are required", "routes": []})
    return jsonify(search(origin, destination, mode))

if __name__ == "__main__":
    app.run(debug=True)