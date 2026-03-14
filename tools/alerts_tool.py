# Copyright Michael Mahoney February 2026

import os
import requests

NEWS_API_KEY = os.getenv("NEWS_API_KEY")

NEWS_URL = "https://newsapi.org/v2/everything"

# roads closed, geoolitical, flights delayed, major weather events, violence,


def run(submission, task_input):
    destination = submission.desired_destination

    params = {
        "q": f"{destination} travel OR airport OR strike OR protest",
        "language": "en",
        "sortBy": "publishedAt",
        "apiKey": NEWS_API_KEY,
        "pageSize": 5,
    }

    r = requests.get(NEWS_URL, params=params, timeout=10)

    if r.status_code != 200:
        return {"alerts": [], "error": "news api failed"}

    data = r.json()

    alerts = []

    for article in data.get("articles", []):
        alerts.append(
            {
                "title": article["title"],
                "source": article["source"]["name"],
                "url": article["url"],
                "published": article["publishedAt"],
            }
        )

    return {
        "type": "travel_alerts",
        "destination": destination,
        "alerts": alerts,
    }