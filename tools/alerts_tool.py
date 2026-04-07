# Copyright Michael Mahoney February 2026

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
NEWS_URL = "https://newsapi.org/v2/everything"

DEFAULT_LOOKBACK_DAYS = int(os.getenv("ALERTS_LOOKBACK_DAYS", "7"))
DEFAULT_PAGE_SIZE = int(os.getenv("ALERTS_PAGE_SIZE", "10"))

SEVERITY_KEYWORDS = {
    "high": [
        "war",
        "armed conflict",
        "missile",
        "terror",
        "terrorist",
        "bombing",
        "evacuation",
        "state of emergency",
        "violent unrest",
        "riot",
        "kidnapping",
        "hostage",
        "coup",
        "martial law",
    ],
    "medium": [
        "protest",
        "strike",
        "demonstration",
        "airport disruption",
        "flight cancellation",
        "flood",
        "wildfire",
        "hurricane",
        "storm warning",
        "earthquake",
        "road closure",
        "curfew",
        "civil unrest",
    ],
    "low": [
        "delay",
        "travel advisory",
        "congestion",
        "weather",
        "closure",
    ],
}

CATEGORY_KEYWORDS = {
    "security": [
        "war",
        "armed conflict",
        "terror",
        "terrorist",
        "bombing",
        "riot",
        "violence",
        "violent unrest",
        "kidnapping",
        "hostage",
        "coup",
        "martial law",
    ],
    "civil_unrest": [
        "protest",
        "strike",
        "demonstration",
        "civil unrest",
        "curfew",
    ],
    "transport": [
        "airport",
        "flight",
        "airline",
        "rail",
        "train",
        "subway",
        "road closure",
        "traffic",
        "port",
    ],
    "weather": [
        "storm",
        "hurricane",
        "wildfire",
        "flood",
        "earthquake",
        "blizzard",
        "heatwave",
    ],
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _build_query(destination: str) -> str:
    return (
        f'"{destination}" AND '
        "("
        '"travel" OR airport OR airline OR flight OR road OR rail OR transit OR '
        "strike OR protest OR war OR unrest OR violence OR curfew OR "
        "storm OR flood OR wildfire OR earthquake OR evacuation OR advisory"
        ")"
    )


def _infer_severity(text: str) -> str:
    text_lower = text.lower()

    for keyword in SEVERITY_KEYWORDS["high"]:
        if keyword in text_lower:
            return "high"

    for keyword in SEVERITY_KEYWORDS["medium"]:
        if keyword in text_lower:
            return "medium"

    return "low"


def _infer_category(text: str) -> str:
    text_lower = text.lower()

    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_lower:
                return category

    return "general"


def _is_relevant(article_text: str, destination: str) -> bool:
    text_lower = article_text.lower()
    destination_lower = destination.lower()

    if destination_lower in text_lower:
        return True

    # fallback: allow airport/travel disruption articles even if exact destination
    # appears only in title/summary weakly or not at all
    travel_terms = [
        "airport",
        "flight",
        "airline",
        "travel advisory",
        "protest",
        "strike",
        "road closure",
        "evacuation",
        "curfew",
        "war",
        "unrest",
    ]
    return any(term in text_lower for term in travel_terms)


def _make_alert_id(title: str, source: str, published: str) -> str:
    raw = f"{title}|{source}|{published}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def run(submission: Any, task_input: dict[str, Any] | None) -> dict[str, Any]:
    task_input = task_input or {}

    if not NEWS_API_KEY:
        return {
            "type": "travel_alerts",
            "destination": getattr(submission, "desired_destination", None),
            "alerts": [],
            "error": "NEWS_API_KEY is not configured",
        }

    destination = _safe_text(getattr(submission, "desired_destination", ""))
    if not destination:
        return {
            "type": "travel_alerts",
            "destination": destination,
            "alerts": [],
            "error": "No destination available on submission",
        }

    lookback_days = int(task_input.get("lookback_days", DEFAULT_LOOKBACK_DAYS))
    page_size = int(task_input.get("page_size", DEFAULT_PAGE_SIZE))
    min_severity = _safe_text(task_input.get("min_severity", "")).lower()

    from_date = (_utc_now() - timedelta(days=lookback_days)).date().isoformat()

    params = {
        "q": _build_query(destination),
        "language": "en",
        "sortBy": "publishedAt",
        "from": from_date,
        "pageSize": page_size,
        "searchIn": "title,description",
    }

    headers = {
        "X-Api-Key": NEWS_API_KEY,
    }

    try:
        response = requests.get(
            NEWS_URL,
            params=params,
            headers=headers,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return {
            "type": "travel_alerts",
            "destination": destination,
            "alerts": [],
            "error": f"news api request failed: {exc}",
        }

    if data.get("status") != "ok":
        return {
            "type": "travel_alerts",
            "destination": destination,
            "alerts": [],
            "error": data.get("message", "news api returned non-ok status"),
        }

    alerts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for article in data.get("articles", []):
        title = _safe_text(article.get("title"))
        description = _safe_text(article.get("description"))
        url = _safe_text(article.get("url"))
        published = _safe_text(article.get("publishedAt"))
        source = _safe_text((article.get("source") or {}).get("name"))

        combined_text = " ".join([title, description])

        if not combined_text:
            continue

        if not _is_relevant(combined_text, destination):
            continue

        severity = _infer_severity(combined_text)
        category = _infer_category(combined_text)

        if min_severity:
            order = {"low": 1, "medium": 2, "high": 3}
            if order.get(severity, 0) < order.get(min_severity, 0):
                continue

        alert_id = _make_alert_id(title, source, published)
        if alert_id in seen_ids:
            continue
        seen_ids.add(alert_id)

        alerts.append(
            {
                "alert_id": alert_id,
                "title": title,
                "summary": description,
                "source": source,
                "url": url,
                "published": published,
                "severity": severity,
                "category": category,
            }
        )

    high_count = sum(1 for a in alerts if a["severity"] == "high")
    medium_count = sum(1 for a in alerts if a["severity"] == "medium")

    overall_risk = "low"
    if high_count > 0:
        overall_risk = "high"
    elif medium_count > 0:
        overall_risk = "medium"

    return {
        "type": "travel_alerts",
        "destination": destination,
        "overall_risk": overall_risk,
        "queried_from": from_date,
        "alerts_found": len(alerts),
        "alerts": alerts,
    }