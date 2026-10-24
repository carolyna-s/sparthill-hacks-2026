"""Outbound email: logged to the console locally, sent through Amazon SES in production.

Every email gets an EmailLog row (added to the session; the caller commits), so staff can see
what went out and what failed.
"""

from __future__ import annotations

import logging

from flask import current_app

from .extensions import db
from .models import EmailLog, User

log = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str, *, user: User | None = None,
               key: str | None = None) -> bool:
    """Send (or log) one email. Returns False if SES refused it; the error is in EmailLog."""
    cfg = current_app.config
    backend = cfg["EMAIL_BACKEND"]
    entry = EmailLog(user_id=user.id if user else None, to_email=to, subject=subject[:255],
                     body=body, key=key, backend=backend, status="logged")
    if backend == "ses":
        import boto3

        try:
            boto3.client("ses", region_name=cfg["AWS_REGION"]).send_email(
                Source=cfg["MAIL_FROM"],
                Destination={"ToAddresses": [to]},
                Message={"Subject": {"Data": subject}, "Body": {"Text": {"Data": body}}},
            )
            entry.status = "sent"
        except Exception as e:  # one bad address shouldn't stop a reminder run
            log.exception("SES send to %s failed", to)
            entry.status, entry.error = "failed", str(e)
    else:
        log.info("EMAIL to=%s subject=%s\n%s", to, subject, body)
    db.session.add(entry)
    return entry.status != "failed"
