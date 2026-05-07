# Copyright Michael Mahoney February 2026
from __future__ import annotations

from typing import Any
import os
import math
import requests


GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
PLACES_TEXTSEARCH_URL = "https://places.googleapis.com/v1/places:searchText"


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the straight-line distance between two latitude and longitude points.

    Uses the haversine formula to estimate distance in miles. This is useful
    for displaying approximate distance from the destination center, but it
    is not the same as driving, walking, or transit distance.

    Args:
        lat1: Latitude of the first point.
        lon1: Longitude of the first point.
        lat2: Latitude of the second point.
        lon2: Longitude of the second point.

    Returns:
        Approximate distance between the two points in miles.
    """
    # simple distance for UI; not exact routing distance
    r = 3958.7613  # miles
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _geocode_center(destination: str) -> dict[str, Any] | None:
    """
    Geocode a destination into a latitude and longitude center point.

    Uses the Google Geocoding API to find the approximate center of the
    destination. If the API key is missing or the destination cannot be
    geocoded, returns None.

    Args:
        destination: Destination name, city, region, or address.

    Returns:
        A dictionary containing "lat" and "lng" values, or None if no center
        point is available.
    """
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
    """
    Search Google Places using a text query.

    Sends a Places API v1 text search request, optionally biased around the
    destination center point, and requests only the fields needed by the
    planner and dashboard.

    Args:
        query: Search phrase to send to Google Places.
        center: Optional latitude and longitude dictionary used to bias
            results near the destination.
        max_results: Maximum number of places to request.

    Returns:
        A list of raw Google Places result dictionaries.

    Raises:
        RuntimeError: If GOOGLE_PLACES_API_KEY is not configured.
        requests.HTTPError: If the Google Places request fails.
    """
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
                "places.priceLevel",
                "places.userRatingCount",
                "places.editorialSummary",
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
    """
    Convert a raw Google Places result into a normalized place item.

    Extracts display name, rating, review count, price level, editorial
    summary, place type, address, location, distance from center, and icon.

    Args:
        p: Raw Google Places result dictionary.
        item_type: Wayfinder category for the place, such as "restaurant",
            "shop", "hotel", "bathroom", or "poi".
        center: Optional destination center point used to calculate distance.

    Returns:
        A normalized place item dictionary for storage and display.
    """
    name = (p.get("displayName") or {}).get("text") or "Unknown"
    rating = p.get("rating")
    user_rating_count = p.get("userRatingCount")
    price_level = p.get("priceLevel")  # enum string like PRICE_LEVEL_MODERATE
    editorial = (p.get("editorialSummary") or {}).get("text")

    # NEW: classification fields (so supervisor can detect cuisine / hotel type better)
    primary_type = p.get("primaryType")
    types = p.get("types") or []
    address = p.get("formattedAddress")

    loc = p.get("location") or {}
    lat = loc.get("latitude")
    lng = loc.get("longitude")

    dist_mi = None
    if center and isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
        dist_mi = round(_haversine_miles(center["lat"], center["lng"], float(lat), float(lng)), 1)

    icon_map = {"restaurant":"🍽️","shop":"🛍️","hotel":"🏨","bathroom":"🚻","poi":"📍"}

    return {
        "name": name,
        "type": item_type,
        "rating": float(rating) if isinstance(rating, (int, float)) else None,
        "user_rating_count": int(user_rating_count) if isinstance(user_rating_count, int) else None,
        "price_level": price_level,
        "editorial_summary": editorial,

        # NEW:
        "primary_type": primary_type,
        "types": types[:10] if isinstance(types, list) else [],
        "address": address,

        "distance_mi": dist_mi,
        "icon": icon_map.get(item_type, "📍"),
        "lat": float(lat) if isinstance(lat, (int, float)) else None,
        "lng": float(lng) if isinstance(lng, (int, float)) else None,
    }


def run(submission, task_input: dict | None = None) -> dict[str, Any]:
    """
    Fetch destination place recommendations from Google Places.

    Searches for restaurants, shopping, hotels, public restrooms, and top
    attractions near the submission destination. Each result is normalized
    into a Wayfinder place item. If one category fails, an error item is added
    while the rest of the tool continues running.

    Args:
        submission: Submission object containing the desired destination.
        task_input: Optional task input dictionary saved with the tool result.

    Returns:
        A dictionary containing the places category, destination, center point,
        normalized place items, task input, and source name.
    """
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
            places = _search_text(q, center=center, max_results=20)
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