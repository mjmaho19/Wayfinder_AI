# Copyright Michael Mahoney

"""
plan_utils.py — Shared planning utilities for the Wayfinder supervisor pipeline.

Provides helper functions used by the AI supervisor and worker to prepare,
validate, and index trip planning data. Responsibilities include:

- Stripping markdown fences from raw model output
- Slimming tool results and current plans before sending to the model
- Canonicalizing place type strings for consistent categorization
- Sorting place candidates by rating, popularity, and distance
- Validating itinerary grounding against real places tool results
- Indexing and extracting tool payloads from raw worker result rows
"""

from __future__ import annotations

import json


def _safe_json_loads(value):
    """
    Attempt to parse a value as JSON, returning None on any failure.

    Passes through dictionaries unchanged. Returns None for non-string
    inputs, empty strings, and any value that raises a JSON parse error.

    Args:
        value: The value to parse. May be a dict, string, or any other type.

    Returns:
        A parsed Python object if ``value`` is a valid JSON string, the
        original dict if ``value`` is already a dict, or ``None`` otherwise.
    """
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def _canonical_item_type(value: str | None) -> str:
    """
    Normalize a raw place type string into a canonical category.

    Maps the many specific type strings returned by the Places API
    (e.g. ``"italian_restaurant"``, ``"resort_hotel"``) into one of
    the broader categories used internally: ``"hotel"``, ``"restaurant"``,
    ``"poi"``, ``"shop"``, or ``"bathroom"``. Unrecognized types are
    returned as-is after lowercasing and stripping whitespace.

    Args:
        value: A raw place type string, or ``None``.

    Returns:
        A canonical category string. Returns the cleaned input unchanged
        if it does not match any known category.
    """
    t = (value or "").strip().lower()

    if t in {"hotel", "hostel", "motel", "inn", "lodging", "resort_hotel"}:
        return "hotel"

    if t in {
        "restaurant", "italian_restaurant", "american_restaurant", "seafood_restaurant",
        "steak_house", "pizza_restaurant", "brunch_restaurant", "fine_dining_restaurant",
        "cafe", "bar_and_grill"
    }:
        return "restaurant"

    if t in {
        "poi", "museum", "art_museum", "history_museum", "city_park", "park",
        "botanical_garden", "market", "tourist_attraction", "aquarium",
        "historical_landmark", "historical_place", "garden"
    }:
        return "poi"

    if t in {"shop", "shopping_mall", "gift_shop", "store"}:
        return "shop"

    if t in {"bathroom", "public_bathroom"}:
        return "bathroom"

    return t


def _sort_place_candidates(item: dict) -> tuple:
    """
    Produce a sort key for ranking place candidates.

    Ranks places by rating (descending), user rating count (descending),
    and distance in miles (ascending), matching the supervisor's preference
    rules. Missing or non-numeric values fall back to neutral defaults so
    that incomplete records sort toward the bottom without raising errors.

    Args:
        item: A place dictionary that may contain ``rating``,
            ``user_rating_count``, and ``distance_mi`` keys.

    Returns:
        A tuple ``(-rating, -count, distance)`` suitable for use as a
        ``key`` argument to ``sorted()``.
    """
    rating = item.get("rating")
    count = item.get("user_rating_count")
    dist = item.get("distance_mi")

    rating_key = float(rating) if isinstance(rating, (int, float)) else -1.0
    count_key = int(count) if isinstance(count, int) else 0
    dist_key = float(dist) if isinstance(dist, (int, float)) else 9999.0

    return (-rating_key, -count_key, dist_key)


def _strip_fences(raw: str) -> str:
    """Remove markdown code fences Groq sometimes wraps around JSON."""
    clean = (raw or "").strip()
    if clean.startswith("```"):
        parts = clean.split("```")
        content = parts[1] if len(parts) > 1 else clean
        if content.startswith("json"):
            content = content[4:]
        return content.strip()
    return clean


def _get_tool_payload(result: dict):
    """
    Extract the usable payload from a tool result dictionary.

    Checks for a pre-parsed ``payload`` key first, then falls back to
    parsing the ``result_json`` string. If parsing fails, returns a
    truncated raw snippet under a ``_raw`` key so callers always receive
    a dictionary.

    Args:
        result: A tool result dictionary from the worker, which may contain
            a ``payload`` dict or a ``result_json`` string.

    Returns:
        The extracted payload as a dictionary. Returns an empty dictionary
        if neither key is present or both are empty.
    """
    payload = result.get("payload")
    if payload is not None:
        return payload

    raw_json = result.get("result_json")
    if isinstance(raw_json, str):
        parsed = _safe_json_loads(raw_json)
        if parsed is not None:
            return parsed
        return {"_raw": raw_json[:500]}

    return {}


def _slim_current_plan(current_plan: dict | None) -> dict | None:
    """
    Reduce the current plan to only the fields the supervisor needs.

    Strips large or rendering-only data (such as ``sections``) before
    the plan is included in the supervisor's context window, keeping
    token usage low without losing planning-relevant information.

    Args:
        current_plan: The full saved plan dictionary, which may be a raw
            plan dict or a wrapper dict with a nested ``plan`` key.
            Pass ``None`` if no plan exists yet.

    Returns:
        A slimmed dictionary containing only ``trip``, ``preference_profile``,
        ``curated_itinerary``, ``highlights``, ``warnings``,
        ``estimated_cost``, and ``meta``. Returns ``None`` if
        ``current_plan`` is not a dictionary.
    """
    if not isinstance(current_plan, dict):
        return None

    plan = current_plan.get("plan") if isinstance(current_plan.get("plan"), dict) else current_plan

    return {
        "trip": plan.get("trip"),
        "preference_profile": plan.get("preference_profile"),
        "curated_itinerary": plan.get("curated_itinerary"),
        "highlights": plan.get("highlights"),
        "warnings": plan.get("warnings"),
        "estimated_cost": plan.get("estimated_cost"),
        "meta": plan.get("meta"),
    }


def _slim_tool_results(tool_results: list[dict]) -> list[dict]:
    """
    Trim tool result payloads to a compact form for the supervisor prompt.

    Applies per-tool slimming logic to reduce token usage. For places
    results, canonicalizes item types, sorts candidates by rating and
    distance, and caps each category at a predefined limit. For weather
    and transit results, retains only the fields the supervisor actually
    uses. All other tool results are passed through unchanged.

    Args:
        tool_results: List of raw tool result dictionaries from the worker,
            each containing a ``tool_name`` key and either a ``payload``
            dict or a ``result_json`` string.

    Returns:
        A new list of slimmed tool result dictionaries in the same order,
        with oversized payloads reduced to their most relevant fields.
    """
    slimmed = []
    limits = {"restaurant": 20, "hotel": 8, "poi": 8, "shop": 4, "bathroom": 3, "other": 3}

    for r in tool_results:
        tool_name = r.get("tool_name", "")
        payload = _get_tool_payload(r)
        if not isinstance(payload, dict):
            payload = {}

        if tool_name == "places":
            items = payload.get("items", []) or []

            by_type: dict[str, list] = {}
            for item in items:
                if not isinstance(item, dict):
                    continue
                t = _canonical_item_type(item.get("type") or "other")
                by_type.setdefault(t, []).append(item)

            slim_items = []
            for t, group in by_type.items():
                lim = limits.get(t, limits["other"])
                group_sorted = sorted(group, key=_sort_place_candidates)[:lim]
                for item in group_sorted:
                    slim_items.append({
                        "name": item.get("name"),
                        "type": t,
                        "rating": item.get("rating"),
                        "distance_mi": item.get("distance_mi"),
                        "user_rating_count": item.get("user_rating_count"),
                        "price_level": item.get("price_level"),
                        "primary_type": item.get("primary_type"),
                        "address": item.get("address"),
                        "editorial_summary": item.get("editorial_summary"),
                    })

            slimmed.append({
                "tool_name": tool_name,
                "payload": {
                    "destination": payload.get("destination"),
                    "items": slim_items,
                }
            })

        elif tool_name == "weather":
            slimmed.append({
                "tool_name": tool_name,
                "payload": {
                    "location": payload.get("location"),
                    "current": payload.get("current", {}),
                }
            })

        elif tool_name == "transit":
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


def _validate_grounding(plan: dict, tool_results: list[dict]) -> None:
    """
    Ensure all named itinerary selections exist in places tool results.
    If not, blank them and add a warning.
    """
    if not isinstance(plan, dict):
        return

    curated = plan.get("curated_itinerary")
    if not isinstance(curated, list):
        return

    places_payload = None
    for r in tool_results:
        if r.get("tool_name") != "places":
            continue

        payload = _get_tool_payload(r)
        if isinstance(payload, dict):
            places_payload = payload
            break

    if not isinstance(places_payload, dict):
        return

    items = places_payload.get("items", []) or []
    allowed_names = {
        item.get("name", "").strip()
        for item in items
        if isinstance(item, dict) and item.get("name")
    }

    warnings = plan.setdefault("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
        plan["warnings"] = warnings

    def _check_place(obj: dict, field_label: str, day_num: int) -> None:
        if not isinstance(obj, dict):
            return
        name = (obj.get("name") or "").strip()
        if name and name not in allowed_names:
            obj["name"] = ""
            warning = f"Ungrounded {field_label} removed on day {day_num}"
            if warning not in warnings:
                warnings.append(warning)

    for entry in curated:
        if not isinstance(entry, dict):
            continue

        day_num = entry.get("day", "?")

        lodging = entry.get("lodging")
        _check_place(lodging, "lodging", day_num)

        meals = entry.get("meals")
        if isinstance(meals, dict):
            _check_place(meals.get("breakfast"), "breakfast", day_num)
            _check_place(meals.get("lunch"), "lunch", day_num)
            _check_place(meals.get("dinner"), "dinner", day_num)

        activities = entry.get("activities")
        if isinstance(activities, list):
            for i, activity in enumerate(activities, start=1):
                _check_place(activity, f"activity {i}", day_num)


def _index_results(tool_results: list[dict]) -> dict:
    """
    Build a lookup dictionary mapping tool names to their payloads.

    Iterates over a list of tool result dictionaries and indexes each
    by its ``tool_name`` key. Results without a tool name are skipped.
    Used by the supervisor fallback to quickly check which tools have
    already returned data.

    Args:
        tool_results: List of tool result dictionaries, each expected to
            have a ``tool_name`` string and a parseable payload.

    Returns:
        A dictionary mapping each tool name string to its extracted
        payload dict. If the same tool name appears more than once,
        the last entry wins.
    """
    out = {}
    for r in tool_results:
        name = (r.get("tool_name") or "").strip()
        if not name:
            continue
        out[name] = _get_tool_payload(r)
    return out