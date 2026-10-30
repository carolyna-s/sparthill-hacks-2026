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

        send_raw_email = send_email  # emails with a calendar invite

    monkeypatch.setattr(boto3, "client", lambda *a, **kw: FailingSES())
    app.config["EMAIL_BACKEND"] = "ses"
    assert send_due_reminders() == 0
    failed = db.session.query(EmailLog).all()
    assert failed and all(r.status == "failed" and "address rejected" in r.error for r in failed)
    assert db.session.query(ReminderLog).count() == 0

    app.config["EMAIL_BACKEND"] = "console"
    assert send_due_reminders() == len(failed)  # the next run retries them


def test_smtp_backend_sends_and_logs(app, monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            assert (host, port) == ("smtp.gmail.com", 587)
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def starttls(self, context): pass
        def login(self, user, password): assert (user, password) == ("me@gmail.com", "app-pw")
        def send_message(self, msg): sent.append(msg)

    import app.notify as notify
    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    app.config.update(EMAIL_BACKEND="smtp", SMTP_USERNAME="me@gmail.com", SMTP_PASSWORD="app-pw")
    assert notify.send_email("you@example.org", "Hello", "Body\n", key="test:1")
    assert sent[0]["To"] == "you@example.org" and sent[0]["Subject"] == "Hello"
    row = db.session.query(EmailLog).filter_by(key="test:1").one()
    assert (row.backend, row.status) == ("smtp", "sent")
