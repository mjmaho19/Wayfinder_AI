# Copyright Michael Mahoney, Edgar Falfan February 2026

"""
weather_tool.py — Open-Meteo weather fetcher for Wayfinder.

Retrieves current weather conditions for a traveler's destination using
the Open-Meteo API (no API key required). Geocodes the destination name
to coordinates, then fetches temperature, wind speed, humidity, and a
human-readable condition label derived from WMO weather codes.

Entry point for the worker pipeline: run(submission, task_input).
"""

from __future__ import annotations

import requests


# WMO Weather Code descriptions
# https://open-meteo.com/en/docs#weathervariables
WMO_CODES = {
    0:  "Clear Sky",
    1:  "Mainly Clear",
    2:  "Partly Cloudy",
    3:  "Overcast",
    45: "Foggy",
    48: "Icy Fog",
    51: "Light Drizzle",
    53: "Moderate Drizzle",
    55: "Heavy Drizzle",
    61: "Light Rain",
    63: "Moderate Rain",
    65: "Heavy Rain",
    71: "Light Snow",
    73: "Moderate Snow",
    75: "Heavy Snow",
    77: "Snow Grains",
    80: "Light Showers",
    81: "Moderate Showers",
    82: "Heavy Showers",
    85: "Snow Showers",
    86: "Heavy Snow Showers",
    95: "Thunderstorm",
    96: "Thunderstorm with Hail",
    99: "Thunderstorm with Heavy Hail",
}


def _condition(code: int) -> str:
    """
    Translate a WMO weather code into a human-readable condition string.

    Args:
        code: Integer WMO weather interpretation code returned by Open-Meteo.

    Returns:
        A descriptive condition string (e.g. "Partly Cloudy"), or a fallback
        string with the raw code if it is not in the lookup table.
    """
    return WMO_CODES.get(code, f"Unknown (code {code})")


def run(submission, task_input: dict) -> dict:
    """
    Fetch current weather for the traveler's destination.

    Geocodes the destination from the submission using the Open-Meteo
    geocoding API, then retrieves current conditions including temperature,
    apparent temperature, wind speed, humidity, and a WMO-based condition
    label. No API key is required.

    Args:
        submission: WayfinderSubmission model instance. Uses the
            ``desired_destination`` attribute as the target location.
        task_input: Dictionary of task-specific input from the worker.
            Not currently used but accepted for interface consistency.

    Returns:
        A dictionary with weather data including ``location``, ``country``,
        ``latitude``, ``longitude``, ``temperature``, ``feels_like``,
        ``condition``, ``weather_code``, ``wind_speed``, ``humidity``,
        and ``raw`` (the unprocessed Open-Meteo current-weather object).
        On failure, returns a dictionary with an ``error`` key and
        the ``location`` string.
    """

    location = submission.desired_destination or "San Francisco"

    # Geocode the destination
    try:
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1},
            timeout=10,
        ).json()
    except Exception as e:
        return {"error": f"Geocoding request failed: {e}", "location": location}

    if not geo.get("results"):
        return {"error": f"Could not find location: {location}", "location": location}

    result = geo["results"][0]
    lat = result["latitude"]
    lon = result["longitude"]
    resolved_name = result.get("name", location)
    country = result.get("country", "")

    # Fetch current weather
    try:
        weather = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m",
                "temperature_unit": "celsius",
                "wind_speed_unit": "kmh",
            },
            timeout=10,
        ).json()
    except Exception as e:
        return {"error": f"Weather request failed: {e}", "location": location}

    current = weather.get("current", {})
    code = current.get("weather_code", 0)

    return {
        "location": resolved_name,
        "country": country,
        "latitude": lat,
        "longitude": lon,
        "temperature": f"{current.get('temperature_2m', '—')}°C",
        "feels_like": f"{current.get('apparent_temperature', '—')}°C",
        "condition": _condition(code),
        "weather_code": code,
        "wind_speed": f"{current.get('wind_speed_10m', '—')} km/h",
        "humidity": f"{current.get('relative_humidity_2m', '—')}%",
        "raw": current,
    }