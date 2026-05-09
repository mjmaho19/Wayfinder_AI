# Copyright Michael Mahoney, Edgar Falfan March 2026

# Transit Tool — Google Routes API
# Returns bus and train routes between two locations.
#
# Called by the worker (task_type='transit') and directly
# by the /api/transit Flask route for the dashboard block.

"""
transit_tool.py — Google Routes API transit fetcher for Wayfinder.

Looks up bus or rail transit routes between an origin and destination using
the Google Routes API. Geocodes plain-text place names to lat/lng coordinates
via the Google Geocoding API, then queries the Routes API for available
transit options and parses each route into structured step-by-step details.

Worker entry point: run(submission, task_input).
Direct search entry point: search(origin, destination, mode).
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

ROUTES_API_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
API_KEY = os.getenv("ROUTES_API_KEY", "")
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
GOOGLE_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")  # reuse the same key

def _geocode(place: str) -> dict | None:
    """
    Convert a place name or full address to lat/lng coordinates.

    Uses the Google Geocoding API with the key stored in the
    ``GOOGLE_PLACES_API_KEY`` environment variable.

    Args:
        place: A place name or address string to geocode
            (e.g. ``"Chicago, IL"`` or ``"1600 Amphitheatre Pkwy"``).

    Returns:
        A dictionary with ``latitude`` and ``longitude`` float values if
        geocoding succeeds, or ``None`` if the API key is missing, the
        location cannot be resolved, or a network error occurs.
    """
    if not GOOGLE_API_KEY:
        logger.warning("[TransitTool] GOOGLE_PLACES_API_KEY not set, geocoding will fail")
        return None
    try:
        res = requests.get(
            GOOGLE_GEOCODE_URL,
            params={"address": place, "key": GOOGLE_API_KEY},
            timeout=10,
        ).json()
        if res.get("status") == "OK":
            loc = res["results"][0]["geometry"]["location"]
            return {"latitude": loc["lat"], "longitude": loc["lng"]}
        logger.warning(f"[TransitTool] Geocode status: {res.get('status')} for '{place}'")
    except Exception as e:
        logger.error(f"[TransitTool] Geocode error for '{place}': {e}")
    return None


def _fetch_routes(origin_coords: dict, dest_coords: dict, mode: str) -> list[dict]:
    """
    Request transit routes from the Google Routes API.

    Sends a POST request for TRANSIT travel between two lat/lng coordinate
    pairs and parses each returned route into a structured summary with
    per-step transit details (line, agency, stops, times).

    Args:
        origin_coords: Dictionary with ``latitude`` and ``longitude`` floats
            for the departure point.
        dest_coords: Dictionary with ``latitude`` and ``longitude`` floats
            for the arrival point.
        mode: Transit mode filter — ``"BUS"`` or ``"RAIL"``.

    Returns:
        A list of route dictionaries, each containing ``duration_min``,
        ``duration_label``, ``distance_mi``, and ``steps``. Each step
        includes ``line``, ``agency``, ``vehicle``, ``departure_stop``,
        ``arrival_stop``, ``departure_time``, ``arrival_time``, and
        ``num_stops``. Returns an empty list if the API key is missing
        or the request fails.
    """
    if not API_KEY:
        logger.warning("[TransitTool] ROUTES_API_KEY not set")
        return []

    body = {
        "origin": {
            "location": {
                "latLng": {
                    "latitude": origin_coords["latitude"],
                    "longitude": origin_coords["longitude"],
                }
            }
        },
        "destination": {
            "location": {
                "latLng": {
                    "latitude": dest_coords["latitude"],
                    "longitude": dest_coords["longitude"],
                }
            }
        },
        "travelMode": "TRANSIT",
        "transitPreferences": {
            "allowedTravelModes": [mode],
        },
        "computeAlternativeRoutes": True,
        "languageCode": "en-US",
        "units": "IMPERIAL",
    }

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": (
            "routes.duration,"
            "routes.distanceMeters,"
            "routes.legs.steps.transitDetails,"
            "routes.legs.steps.distanceMeters,"
            "routes.legs.steps.staticDuration"
        ),
    }

    try:
        res = requests.post(ROUTES_API_URL, json=body, headers=headers, timeout=15)
        res.raise_for_status()
        data = res.json()
    except Exception as e:
        logger.error(f"[TransitTool] Routes API error ({mode}): {e}")
        return []

    routes = []
    for route in data.get("routes", []):
        steps = []
        for leg in route.get("legs", []):
            for step in leg.get("steps", []):
                td = step.get("transitDetails", {})
                if not td:
                    continue
                line = td.get("transitLine", {})
                agency = ""
                agencies = line.get("agencies", [])
                if agencies:
                    agency = agencies[0].get("name", "")

                steps.append({
                    "line": line.get("nameShort") or line.get("name", ""),
                    "agency": agency,
                    "vehicle": line.get("vehicle", {}).get("type", mode),
                    "departure_stop": td.get("stopDetails", {}).get("departureStop", {}).get("name", ""),
                    "arrival_stop": td.get("stopDetails", {}).get("arrivalStop", {}).get("name", ""),
                    "departure_time": td.get("localizedValues", {}).get("departureTime", {}).get("time", {}).get("text", ""),
                    "arrival_time": td.get("localizedValues", {}).get("arrivalTime", {}).get("time", {}).get("text", ""),
                    "num_stops": td.get("stopCount", 0),
                })

        duration_sec = int(route.get("duration", "0s").replace("s", "") or 0)
        duration_min = duration_sec // 60
        distance_m = route.get("distanceMeters", 0)
        distance_mi = round(distance_m * 0.000621371, 1)

        routes.append({
            "duration_min": duration_min,
            "duration_label": f"{duration_min // 60}h {duration_min % 60}m" if duration_min >= 60 else f"{duration_min}m",
            "distance_mi": distance_mi,
            "steps": steps,
        })

    return routes


def search(origin: str, destination: str, mode: str = "BUS") -> dict[str, Any]:
    """
    Search for transit routes between two places by name.

    Geocodes both the origin and destination strings, then fetches
    available routes for the specified transit mode. Invalid mode values
    default to ``"BUS"``.

    Args:
        origin: City name or address string for the departure location.
        destination: City name or address string for the arrival location.
        mode: Transit mode — ``"BUS"`` or ``"RAIL"`` (case-insensitive).
            Defaults to ``"BUS"``.

    Returns:
        A dictionary containing ``origin``, ``destination``, ``mode``,
        ``routes`` (list of route dicts from ``_fetch_routes``), and
        ``count`` (number of routes found). Returns a dictionary with an
        ``error`` key and an empty ``routes`` list if either location
        cannot be geocoded.
    """
    mode = mode.upper()
    if mode not in ("BUS", "RAIL"):
        mode = "BUS"

    origin_coords = _geocode(origin)
    dest_coords = _geocode(destination)

    if not origin_coords:
        return {"error": f"Could not find location: {origin}", "routes": []}
    if not dest_coords:
        return {"error": f"Could not find location: {destination}", "routes": []}

    routes = _fetch_routes(origin_coords, dest_coords, mode)

    return {
        "origin": origin,
        "destination": destination,
        "mode": mode,
        "routes": routes,
        "count": len(routes),
    }


def run(submission, task_input: dict | None = None) -> dict[str, Any]:
    """
    Worker entry point for the transit task.

    Extracts the origin and destination from the submission and performs
    a default bus route search via ``search()``. Called by ``run_worker.py``
    when processing a task of type ``'transit'``.

    Args:
        submission: WayfinderSubmission model instance. Uses the ``origin``
            and ``desired_destination`` attributes as the two endpoints.
        task_input: Dictionary of task-specific input from the worker.
            Not currently used but accepted for interface consistency.

    Returns:
        A route result dictionary as returned by ``search()``, containing
        ``origin``, ``destination``, ``mode``, ``routes``, and ``count``.
    """
    origin = submission.origin or "Unknown origin"
    dest = submission.desired_destination or "Unknown destination"
    return search(origin, dest, mode="BUS")