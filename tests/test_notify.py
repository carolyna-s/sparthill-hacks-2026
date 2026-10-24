"""Every outbound email lands in EmailLog; a failed SES send isn't marked as reminded."""

import boto3

from app.extensions import db
from app.models import EmailLog, ReminderLog
from app.reminders import send_due_reminders


def test_console_emails_are_logged(app):
    sent = send_due_reminders()
    rows = db.session.query(EmailLog).all()
    assert len(rows) == sent > 0
    assert all(r.status == "logged" and r.backend == "console" and r.user_id and r.key for r in rows)


def test_failed_ses_send_is_logged_and_retried(app, monkeypatch):
    class FailingSES:
        def send_email(self, **kwargs):
            raise RuntimeError("address rejected")

    monkeypatch.setattr(boto3, "client", lambda *a, **kw: FailingSES())
    app.config["EMAIL_BACKEND"] = "ses"
    assert send_due_reminders() == 0
    failed = db.session.query(EmailLog).all()
    assert failed and all(r.status == "failed" and "address rejected" in r.error for r in failed)
    assert db.session.query(ReminderLog).count() == 0

    app.config["EMAIL_BACKEND"] = "console"
    assert send_due_reminders() == len(failed)  # the next run retries them
