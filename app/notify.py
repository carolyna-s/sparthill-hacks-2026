"""Outbound email: logged to the console locally, sent through Amazon SES in production."""

from __future__ import annotations

import logging

from flask import current_app

log = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> None:
    cfg = current_app.config
    if cfg["EMAIL_BACKEND"] == "ses":
        import boto3

        boto3.client("ses", region_name=cfg["AWS_REGION"]).send_email(
            Source=cfg["MAIL_FROM"],
            Destination={"ToAddresses": [to]},
            Message={"Subject": {"Data": subject}, "Body": {"Text": {"Data": body}}},
        )
    else:
        log.info("EMAIL to=%s subject=%s\n%s", to, subject, body)
