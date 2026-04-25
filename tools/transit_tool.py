# Copyright Michael Mahoney, Edgar Falfan March 2026

# Transit Tool — Google Routes API
# Returns bus and train routes between two locations.
#
# Called by the worker (task_type='transit') and directly
# by the /api/transit Flask route for the dashboard block.

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
    """Convert a place name or full address to lat/lng using Google Geocoding API."""
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
    Call Google Routes API for transit routes.
    mode: 'BUS' or 'RAIL'
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
    Search for transit routes between two places.

    origin      : city or address string
    destination : city or address string
    mode        : 'BUS' or 'RAIL'
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
    Worker entry point — called by run_worker.py for task_type='transit'.
    Uses the submission's origin and destination for a default bus search.
    """
    origin = submission.origin or "Unknown origin"
    dest = submission.desired_destination or "Unknown destination"
    return search(origin, dest, mode="BUS")