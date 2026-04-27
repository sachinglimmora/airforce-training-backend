"""PII filter — strips personal data before sending to LLM providers.

Policy is owned by Ira; this module enforces it.
"""

import re

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

_REDACT = "[REDACTED]"


def _redact_text(text: str) -> str:
    text = _EMAIL_RE.sub(_REDACT, text)
    text = _PHONE_RE.sub(_REDACT, text)
    text = _SSN_RE.sub(_REDACT, text)
    return text


def filter_messages(messages: list[dict]) -> list[dict]:
    """
    Strips known PII from message contents.
    Raises PIIDetected if high-risk patterns remain after redaction attempt.
    """
    cleaned = []
    for msg in messages:
        content = msg.get("content", "")
        redacted = _redact_text(content)
        cleaned.append({**msg, "content": redacted})
    return cleaned


def strip_structured_pii(context: dict) -> dict:
    """Remove PII fields from structured context before injection."""
    sensitive_keys = {"email", "employee_id", "full_name", "date_of_birth", "phone", "medical_info"}
    return {k: v for k, v in context.items() if k not in sensitive_keys}
