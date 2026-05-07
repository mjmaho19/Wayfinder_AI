# Copyright Michael Mahoney March 2026

from __future__ import annotations

import os
from typing import Any

import requests


RESEND_API_KEY = os.getenv("RESEND_API_KEY")
EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
EMAIL_FROM = os.getenv("EMAIL_FROM", "Wayfinder <onboarding@resend.dev>")
RESEND_SEND_URL = "https://api.resend.com/emails"


def _validate_config() -> tuple[bool, str | None]:
    """
    Validate the email notification configuration.

    Checks whether email sending is enabled and whether the required Resend
    settings are available.

    Returns:
        A tuple containing a boolean success value and an optional error
        message. If validation succeeds, the error message is None.
    """

    if not EMAIL_ENABLED:
        return False, "EMAIL_ENABLED is false"

    if not RESEND_API_KEY:
        return False, "RESEND_API_KEY is not configured"

    if not EMAIL_FROM:
        return False, "EMAIL_FROM is not configured"

    return True, None


def send_email(
    to_email: str,
    subject: str,
    html: str,
    text: str | None = None,
    reply_to: str | None = None,
) -> dict[str, Any]:
    """
    Send an email through the Resend API.

    Validates the email configuration, builds the Resend request payload,
    sends the email, and returns a structured status dictionary describing
    whether the message was sent, skipped, or failed.

    Args:
        to_email: Recipient email address.
        subject: Email subject line.
        html: HTML body content for the email.
        text: Optional plain-text body content for the email.
        reply_to: Optional reply-to email address.

    Returns:
        A dictionary containing the send status, recipient, subject, and
        provider response details when available.
    """
    ok, error = _validate_config()
    if not ok:
        return {
            "status": "skipped",
            "error": error,
            "to": to_email,
            "subject": subject,
        }

    if not to_email:
        return {
            "status": "failed",
            "error": "Missing destination email address",
            "to": to_email,
            "subject": subject,
        }

    payload: dict[str, Any] = {
        "from": EMAIL_FROM,
        "to": [to_email],
        "subject": subject,
        "html": html,
    }

    if text is not None:
        payload["text"] = text

    if reply_to:
        payload["reply_to"] = reply_to

    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            RESEND_SEND_URL,
            json=payload,
            headers=headers,
            timeout=15,
        )

        data = response.json() if response.content else {}

        if response.status_code >= 400:
            return {
                "status": "failed",
                "error": data.get("message") or f"Resend error {response.status_code}",
                "to": to_email,
                "subject": subject,
                "provider_response": data,
            }

        return {
            "status": "sent",
            "provider": "resend",
            "email_id": data.get("id"),
            "to": to_email,
            "subject": subject,
        }

    except requests.RequestException as exc:
        return {
            "status": "failed",
            "error": f"Email request failed: {exc}",
            "to": to_email,
            "subject": subject,
        }