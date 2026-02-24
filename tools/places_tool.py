# Copyright Michael Mahoney February 2026
from __future__ import annotations

from typing import Any
import os
import math
import requests


GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
PLACES_TEXTSEARCH_URL = "https://places.googleapis.com/v1/places:searchText"


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # simple distance for UI; not exact routing distance
    r = 3958.7613  # miles
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _geocode_center(destination: str) -> dict[str, Any] | None:
    # lightweight geocode using Google Geocoding API (optional)
    # If you don’t want this yet, return None and we won’t compute distances.
    key = GOOGLE_PLACES_API_KEY
    if not key:
        return None
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    r = requests.get(url, params={"address": destination, "key": key}, timeout=15)
    r.raise_for_status()
    j = r.json()
    if j.get("status") != "OK":
        return None
    loc = j["results"][0]["geometry"]["location"]
    return {"lat": float(loc["lat"]), "lng": float(loc["lng"])}


def _search_text(query: str, center: dict[str, float] | None, max_results: int = 6) -> list[dict[str, Any]]:
    if not GOOGLE_PLACES_API_KEY:
        raise RuntimeError("GOOGLE_PLACES_API_KEY is not set")

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
        # FieldMask is REQUIRED for Places API v1
        "X-Goog-FieldMask": ",".join(
            [
                "places.displayName",
                "places.location",
                "places.rating",
                "places.formattedAddress",
                "places.primaryType",
                "places.types",
            ]
        ),
    }

    body: dict[str, Any] = {
        "textQuery": query,
        "pageSize": max_results,
    }

    # bias around destination center
    if center:
        body["locationBias"] = {
            "circle": {
                "center": {"latitude": center["lat"], "longitude": center["lng"]},
                "radius": 8000.0,  # meters ~ 5mi
            }
        }

    resp = requests.post(PLACES_TEXTSEARCH_URL, headers=headers, json=body, timeout=20)
    resp.raise_for_status()
    payload = resp.json()
    return payload.get("places", []) or []


def _to_item(p: dict[str, Any], item_type: str, center: dict[str, float] | None) -> dict[str, Any]:
    name = (p.get("displayName") or {}).get("text") or "Unknown"
    rating = p.get("rating")

    loc = p.get("location") or {}
    lat = loc.get("latitude")
    lng = loc.get("longitude")

    dist_mi = None
    if center and isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
        dist_mi = round(_haversine_miles(center["lat"], center["lng"], float(lat), float(lng)), 1)

    icon_map = {
        "restaurant": "🍽️",
        "shop": "🛍️",
        "hotel": "🏨",
        "bathroom": "🚻",
        "poi": "📍",
    }

    return {
        "name": name,
        "type": item_type,
        "rating": float(rating) if isinstance(rating, (int, float)) else None,
        "distance_mi": dist_mi,
        "icon": icon_map.get(item_type, "📍"),
        # optional: keep coordinates for pins (your dashboard supports x/y, but we can add lat/lng later)
        "lat": float(lat) if isinstance(lat, (int, float)) else None,
        "lng": float(lng) if isinstance(lng, (int, float)) else None,
    }


def run(submission, task_input: dict | None = None) -> dict[str, Any]:
    destination = submission.desired_destination or "Unknown destination"

    # Try to get a center point (optional). If this fails, we still proceed without distance.
    center = None
    try:
        center = _geocode_center(destination)
    except Exception:
        center = None

    # Queries per category
    queries = [
        ("restaurant", f"best restaurants in {destination}"),
        ("shop", f"shopping in {destination}"),
        ("hotel", f"hotels in {destination}"),
        ("bathroom", f"public restroom in {destination}"),
        ("poi", f"top attractions in {destination}"),
    ]

    items: list[dict[str, Any]] = []

    for item_type, q in queries:
        try:
            places = _search_text(q, center=center, max_results=5)
            for p in places:
                items.append(_to_item(p, item_type=item_type, center=center))
        except Exception as e:
            # Important: return a visible “error card”, but keep the tool alive.
            items.append(
                {
                    "name": f"Error fetching {item_type}",
                    "type": item_type,
                    "rating": None,
                    "distance_mi": None,
                    "icon": "⚠️",
                    "error": str(e),
                }
            )

    return {
        "category": "places",
        "destination": destination,
        "center": center,
        "items": items,
        "task_input": task_input or {},
        "source": "google_places_v1",
    }