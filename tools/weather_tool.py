# Copyright Michael Mahoney, Edgar Falfan February 2026

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
    return WMO_CODES.get(code, f"Unknown (code {code})")


def run(submission, task_input: dict) -> dict:
    """
    Weather tool using Open-Meteo (no API key required).
    Returns human-readable temperature, condition, and wind speed.
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