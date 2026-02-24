# Copyright Michael Mahoney February 2026

from __future__ import annotations

import requests


def run(submission, task_input: dict) -> dict:
    """
    Real weather tool using Open-Meteo.
    No API key required.
    """

    # Default location if none provided
    location = submission.desired_destination or "San Francisco"

    # Very simple geocode (Open-Meteo free)
    geo = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": location, "count": 1},
        timeout=10,
    ).json()

    if not geo.get("results"):
        return {"error": f"Could not geocode location: {location}"}

    lat = geo["results"][0]["latitude"]
    lon = geo["results"][0]["longitude"]

    weather = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,weather_code,wind_speed_10m",
        },
        timeout=10,
    ).json()

    return {
        "location": location,
        "latitude": lat,
        "longitude": lon,
        "current": weather.get("current", {}),
    }