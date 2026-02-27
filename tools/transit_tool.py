# Copyright Michael Mahoney February 2026

# placeholder stub right now, implement transit API

from __future__ import annotations

from typing import Any


def run(submission, task_input: dict | None = None) -> dict[str, Any]:
    origin = submission.origin or "Unknown origin"
    dest = submission.desired_destination or "Unknown destination"
    return {
        "category": "transit",
        "origin": origin,
        "destination": dest,
        "options": [
            {"mode": "rideshare", "eta_min": 22, "cost_estimate": 35},
            {"mode": "public_transit", "eta_min": 40, "cost_estimate": 3},
        ],
        "task_input": task_input or {},
        "source": "stub",
    }