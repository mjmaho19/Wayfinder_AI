# Copyright Michael Mahoney, Edgar Falfan April 2026

from __future__ import annotations

import logging
import os
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)

_client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1",
)

SYSTEM_PROMPT = """
You are a knowledgeable travel cultural guide.

Given a destination, return ONLY valid JSON (no markdown, no fences) in this exact shape:

{
  "destination": "City, Country",
  "facts": [
    { "emoji": "🏛️", "title": "Short title", "body": "2-3 sentence fact." },
    { "emoji": "🍜", "title": "Short title", "body": "2-3 sentence fact." },
    { "emoji": "🎭", "title": "Short title", "body": "2-3 sentence fact." },
    { "emoji": "🗣️", "title": "Short title", "body": "2-3 sentence fact." },
    { "emoji": "💡", "title": "Short title", "body": "2-3 sentence fact." },
    { "emoji": "🧳", "title": "Short title", "body": "2-3 sentence fact." }
  ],
  "quick_tips": [
    "Short practical tip for travelers.",
    "Short practical tip for travelers.",
    "Short practical tip for travelers."
  ]
}

Cover a mix of: history, food culture, local customs, language, fun facts, and traveler etiquette.
Keep each body to 2-3 sentences max. Be specific to the destination — no generic travel advice.
Return ONLY the JSON object. No extra text.
""".strip()


def run(submission: Any, task_input: dict[str, Any] | None = None) -> dict[str, Any]:
    destination = getattr(submission, "desired_destination", None) or ""

    if not destination:
        return {
            "type": "culture",
            "destination": destination,
            "facts": [],
            "quick_tips": [],
            "error": "No destination provided",
        }

    logger.info(f"[CultureTool] Fetching cultural facts for: {destination}")

    try:
        response = _client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=800,
            temperature=0.4,
            timeout=30,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Destination: {destination}"},
            ],
        )
        raw = response.choices[0].message.content or ""

        # Strip fences if model adds them anyway
        clean = raw.strip()
        if clean.startswith("```"):
            parts = clean.split("```")
            clean = parts[1] if len(parts) > 1 else clean
            if clean.startswith("json"):
                clean = clean[4:]
            clean = clean.strip()

        import json
        parsed = json.loads(clean)

        return {
            "type": "culture",
            "destination": parsed.get("destination", destination),
            "facts": parsed.get("facts", []),
            "quick_tips": parsed.get("quick_tips", []),
        }

    except Exception as exc:
        logger.error(f"[CultureTool] Error: {exc}")
        return {
            "type": "culture",
            "destination": destination,
            "facts": [],
            "quick_tips": [],
            "error": str(exc),
        }
