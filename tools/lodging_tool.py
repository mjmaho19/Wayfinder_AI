# Copyright Michael Mahoney February 2026
from __future__ import annotations

from typing import Any


def run(submission, task_input: dict | None = None) -> dict[str, Any]:
    destination = submission.desired_destination or "Unknown destination"
    budget = submission.budget or "unspecified"
    return {
        "category": "lodging",
        "destination": destination,
        "budget": budget,
        "hotels": [
            {"name": "Example Hotel", "price_per_night": 180, "rating": 4.4, "distance_mi": 1.0},
            {"name": "Example Suites", "price_per_night": 230, "rating": 4.6, "distance_mi": 1.8},
        ],
        "task_input": task_input or {},
        "source": "stub",
    }