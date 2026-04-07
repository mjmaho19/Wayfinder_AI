# Copyright Michael Mahoney March 2026

from __future__ import annotations

from html import escape
from typing import Any

from notifications.notify import send_email


def _build_subject(destination: str, alerts: list[dict[str, Any]]) -> str:
    severe = [a for a in alerts if a.get("severity") in {"high", "medium"}]
    if severe:
        return f"Wayfinder travel alert for {destination}"
    return f"Wayfinder update for {destination}"


def _build_text_body(destination: str, traveler_name: str, alerts: list[dict[str, Any]]) -> str:
    lines = [
        f"Hello {traveler_name or 'traveler'},",
        "",
        f"Wayfinder found travel-related alerts for {destination}.",
        "",
    ]

    for idx, alert in enumerate(alerts[:5], start=1):
        lines.append(
            f"{idx}. [{str(alert.get('severity', 'unknown')).upper()}] "
            f"{alert.get('title', 'Untitled alert')}"
        )
        if alert.get("summary"):
            lines.append(f"   {alert['summary']}")
        if alert.get("source"):
            lines.append(f"   Source: {alert['source']}")
        if alert.get("published"):
            lines.append(f"   Published: {alert['published']}")
        if alert.get("url"):
            lines.append(f"   {alert['url']}")
        lines.append("")

    lines.append("Open your Wayfinder dashboard for more details.")
    return "\n".join(lines)


def _build_html_body(destination: str, traveler_name: str, alerts: list[dict[str, Any]]) -> str:
    items = []

    for alert in alerts[:5]:
        title = escape(alert.get("title", "Untitled alert"))
        summary = escape(alert.get("summary", "") or "")
        severity = escape(str(alert.get("severity", "unknown")).upper())
        source = escape(alert.get("source", "") or "")
        published = escape(alert.get("published", "") or "")
        url = escape(alert.get("url", "") or "")

        block = f"""
        <li style="margin-bottom:16px;">
          <div><strong>[{severity}] {title}</strong></div>
          {f"<div>{summary}</div>" if summary else ""}
          {f"<div><small>Source: {source}</small></div>" if source else ""}
          {f"<div><small>Published: {published}</small></div>" if published else ""}
          {f'<div><a href="{url}">Read article</a></div>' if url else ""}
        </li>
        """
        items.append(block)

    items_html = "\n".join(items)

    return f"""
    <html>
      <body>
        <p>Hello {escape(traveler_name or "traveler")},</p>
        <p>Wayfinder found travel-related alerts for <strong>{escape(destination)}</strong>.</p>
        <ul>
          {items_html}
        </ul>
        <p>Open your Wayfinder dashboard for more details.</p>
      </body>
    </html>
    """


def run(submission: Any, task_input: dict[str, Any] | None) -> dict[str, Any]:
    task_input = task_input or {}

    destination = getattr(submission, "desired_destination", "") or ""
    traveler_name = getattr(submission, "traveler_name", "") or "traveler"
    to_email = task_input.get("email") or getattr(submission, "email", None)
    alerts = task_input.get("alerts", []) or []

    if not to_email:
        return {
            "type": "email_alert",
            "status": "skipped",
            "reason": "No email address available",
        }

    if not alerts:
        return {
            "type": "email_alert",
            "status": "skipped",
            "reason": "No alerts provided",
        }

    subject = _build_subject(destination, alerts)
    text_body = _build_text_body(destination, traveler_name, alerts)
    html_body = _build_html_body(destination, traveler_name, alerts)

    email_result = send_email(
        to_email=to_email,
        subject=subject,
        html=html_body,
        text=text_body,
    )

    return {
        "type": "email_alert",
        "destination": destination,
        "alerts_sent": len(alerts[:5]),
        "email": email_result,
    }