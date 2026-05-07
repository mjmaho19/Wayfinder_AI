# Copyright Michael Mahoney March 2026

from __future__ import annotations

from html import escape
from typing import Any

from notifications.notify import send_email


def _build_subject(destination: str, alerts: list[dict[str, Any]]) -> str:
    """
    Build the email subject line for a travel alert message.

    Uses a stronger alert subject when any alert has high or medium severity.
    Otherwise, returns a general Wayfinder update subject.

    Args:
        destination: Destination connected to the alerts.
        alerts: List of alert dictionaries.

    Returns:
        A subject line string for the email.
    """
    severe = [a for a in alerts if a.get("severity") in {"high", "medium"}]
    if severe:
        return f"Wayfinder travel alert for {destination}"
    return f"Wayfinder update for {destination}"


def _build_text_body(destination: str, traveler_name: str, alerts: list[dict[str, Any]]) -> str:
    """
    Build the plain-text body for a travel alert email.

    Formats up to five alerts with severity, title, summary, source,
    published date, and article URL when available.

    Args:
        destination: Destination connected to the alerts.
        traveler_name: Name of the traveler receiving the email.
        alerts: List of alert dictionaries.

    Returns:
        A plain-text email body string.
    """

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
    """
    Build the HTML body for a travel alert email.

    Formats up to five alerts as an HTML list and escapes dynamic content
    before inserting it into the message.

    Args:
        destination: Destination connected to the alerts.
        traveler_name: Name of the traveler receiving the email.
        alerts: List of alert dictionaries.

    Returns:
        An HTML email body string.
    """
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
    """
    Send a travel alert email for a trip submission.

    Reads the destination, traveler name, email address, and alerts from the
    submission and task input. Skips sending if no recipient email or alerts
    are available. Otherwise, builds the email subject and body, sends the
    message, and returns the email result.

    Args:
        submission: Submission object containing trip and traveler details.
        task_input: Optional task data containing an email address and alerts.

    Returns:
        A dictionary describing the email alert task result, including whether
        it was skipped or sent.
    """
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