# Copyright Michael Mahoney, Edgar Falfan April 2026

"""
events_tool.py — Ticketmaster event fetcher for Wayfinder.

Queries the Ticketmaster Discovery API for local events at the traveler's
destination within their travel date window. Parses each event into a
structured dict including name, date, time, venue, genre, price range,
and ticket URL.

Requires the TICKETMASTER_API_KEY environment variable to be set.

Worker entry point: run(submission, task_input).
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

TICKETMASTER_API_KEY = os.getenv("TICKETMASTER_API_KEY")
DISCOVERY_URL = "https://app.ticketmaster.com/discovery/v2/events.json"


def _parse_dates(travel_dates: str) -> tuple[str | None, str | None]:
    """
    Parse a travel date range string into ISO 8601 timestamps.

    Accepts formats like ``"2026-06-01 to 2026-06-07"`` or ranges using an
    em dash (``"–"``), which is normalized to ``" to "`` before splitting.
    Start date is suffixed with ``T00:00:00Z`` and end date with
    ``T23:59:59Z`` to cover the full day in UTC.

    Args:
        travel_dates: A date range string from the submission. May use
            ``" to "`` or ``"–"`` as the separator.

    Returns:
        A tuple of ``(start_datetime, end_datetime)`` ISO 8601 strings.
        Either value may be ``None`` if the input is empty, malformed,
        or missing the corresponding date part.
    """
    if not travel_dates:
        return None, None
    try:
        parts = [p.strip() for p in travel_dates.replace("–", " to ").split(" to ")]
        start = parts[0] + "T00:00:00Z" if parts[0] else None
        end   = parts[1] + "T23:59:59Z" if len(parts) > 1 and parts[1] else None
        return start, end
    except Exception:
        return None, None


def run(submission: Any, task_input: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Fetch local events for the traveler's destination and travel dates.

    Parses the travel date range into ISO 8601 timestamps, queries the
    Ticketmaster Discovery API filtered by city and date window, and
    normalizes each returned event into a structured dictionary. Returns
    early with an error payload if the API key is missing or no destination
    is provided.

    Args:
        submission: WayfinderSubmission model instance. Uses the
            ``desired_destination`` and ``travel_dates`` attributes.
        task_input: Dictionary of task-specific input from the worker.
            Not currently used but accepted for interface consistency.

    Returns:
        A dictionary containing ``type`` (always ``"events"``),
        ``destination``, ``travel_dates``, ``events_found`` (integer count),
        and ``events`` (list of dicts with ``name``, ``date``, ``time``,
        ``venue``, ``segment``, ``genre``, ``price``, and ``url``).
        On failure, includes an ``error`` key and an empty ``events`` list.
    """
    destination = getattr(submission, "desired_destination", None) or ""
    travel_dates = getattr(submission, "travel_dates", None) or ""

    if not TICKETMASTER_API_KEY:
        return {
            "type": "events",
            "destination": destination,
            "events": [],
            "error": "TICKETMASTER_API_KEY is not configured",
        }

    if not destination:
        return {
            "type": "events",
            "destination": destination,
            "events": [],
            "error": "No destination provided",
        }

    start_dt, end_dt = _parse_dates(travel_dates)

    params = {
        "apikey": TICKETMASTER_API_KEY,
        "city": destination,
        "countryCode": "MX",
        "size": 10,
        "sort": "date,asc",
        "locale": "*",
    }

    if start_dt:
        params["startDateTime"] = start_dt
    if end_dt:
        params["endDateTime"] = end_dt

    logger.info(f"[EventsTool] Fetching events for: {destination} | {travel_dates}")

    try:
        response = requests.get(DISCOVERY_URL, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.error(f"[EventsTool] Request failed: {exc}")
        return {
            "type": "events",
            "destination": destination,
            "events": [],
            "error": str(exc),
        }

    raw_events = (data.get("_embedded") or {}).get("events") or []
    events = []

    for e in raw_events:
        name = e.get("name", "Unnamed Event")

        # Date
        dates = e.get("dates", {})
        start = dates.get("start", {})
        date_str = start.get("localDate", "")
        time_str = start.get("localTime", "")

        # Venue
        venues = (e.get("_embedded") or {}).get("venues") or []
        venue_name = venues[0].get("name", "") if venues else ""

        # Category
        classifications = e.get("classifications") or []
        segment = ""
        genre = ""
        if classifications:
            c = classifications[0]
            segment = (c.get("segment") or {}).get("name", "")
            genre = (c.get("genre") or {}).get("name", "")

        # URL
        url = e.get("url", "")

        # Price range
        price_ranges = e.get("priceRanges") or []
        price = ""
        if price_ranges:
            pr = price_ranges[0]
            mn = pr.get("min")
            mx = pr.get("max")
            currency = pr.get("currency", "USD")
            if mn and mx:
                price = f"{currency} ${mn:.0f} – ${mx:.0f}"
            elif mn:
                price = f"From ${mn:.0f}"

        events.append({
            "name": name,
            "date": date_str,
            "time": time_str,
            "venue": venue_name,
            "segment": segment,
            "genre": genre,
            "price": price,
            "url": url,
        })

    return {
        "type": "events",
        "destination": destination,
        "travel_dates": travel_dates,
        "events_found": len(events),
        "events": events,
    }