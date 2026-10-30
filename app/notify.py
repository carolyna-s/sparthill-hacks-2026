"""Outbound email by EMAIL_BACKEND: console (log only), smtp (e.g. Gmail), or ses (Amazon SES).

Every email gets an EmailLog row (added to the session; the caller commits), so staff can see
what went out and what failed.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage

import certifi
from flask import current_app, render_template

from . import ics
from .extensions import db
from .models import Application, EmailLog, Event, Match, Meeting, Message, User, utcnow

log = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str, *, user: User | None = None,
               key: str | None = None, ics: str | None = None) -> bool:
    """Send (or log) one email, with an optional calendar invite (app/ics.py). Returns False if
    sending failed; the error is in EmailLog."""
    cfg = current_app.config
    backend = cfg["EMAIL_BACKEND"]
    entry = EmailLog(user_id=user.id if user else None, to_email=to, subject=subject[:255],
                     body=body, key=key, backend=backend, status="logged")
    if backend in ("smtp", "ses"):
        try:
            (_send_smtp if backend == "smtp" else _send_ses)(cfg, to, subject, body, ics)
            entry.status = "sent"
        except Exception as e:  # one bad address shouldn't stop a reminder run
            log.exception("%s send to %s failed", backend.upper(), to)
            entry.status, entry.error = "failed", str(e)
    else:
        log.info("EMAIL to=%s subject=%s%s\n%s", to, subject, " [+ calendar invite]" if ics else "", body)
    db.session.add(entry)
    return entry.status != "failed"


def _message(cfg, to: str, subject: str, body: str, ics: str | None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = cfg["MAIL_FROM"], to, subject
    msg.set_content(body)
    if ics:
        # Inline text/calendar is what makes Gmail/Outlook show the invite card; the attachment
        # is for clients that only offer "open invite.ics".
        method = next(line[7:] for line in ics.splitlines() if line.startswith("METHOD:"))
        msg.add_alternative(ics, subtype="calendar", params={"method": method})
        msg.add_attachment(ics.encode(), maintype="application", subtype="ics", filename="invite.ics")
    return msg


def _send_smtp(cfg, to: str, subject: str, body: str, ics: str | None = None) -> None:
    """Any SMTP server with STARTTLS, e.g. Gmail with an app password."""
    msg = _message(cfg, to, subject, body, ics)
    # certifi's CA bundle: python.org macOS builds ship without system certificates.
    tls = ssl.create_default_context(cafile=certifi.where())
    with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=20) as smtp:
        smtp.starttls(context=tls)
        smtp.login(cfg["SMTP_USERNAME"], cfg["SMTP_PASSWORD"])
        smtp.send_message(msg)


def _send_ses(cfg, to: str, subject: str, body: str, ics: str | None = None) -> None:
    import boto3

    client = boto3.client("ses", region_name=cfg["AWS_REGION"])
    if ics:
        client.send_raw_email(Source=cfg["MAIL_FROM"], Destinations=[to],
                              RawMessage={"Data": _message(cfg, to, subject, body, ics).as_bytes()})
        return
    client.send_email(
        Source=cfg["MAIL_FROM"],
        Destination={"ToAddresses": [to]},
        Message={"Subject": {"Data": subject}, "Body": {"Text": {"Data": body}}},
    )


def send_template(user: User, template: str, *, key: str | None = None, ics: str | None = None,
                  **context) -> bool:
    """Render templates/email/<template>.txt (first line is the subject) and send it to user.email."""
    text = render_template(f"email/{template}.txt", user=user, base_url=current_app.config["BASE_URL"], **context)
    subject, _, body = text.partition("\n")
    return send_email(user.email, subject.strip(), body.strip() + "\n", user=user, key=key, ics=ics)


def notify_match_created(match: Match) -> None:
    """Tell both people their match is confirmed. Call after the match is committed as approved."""
    for user in (match.mentee, match.mentor):
        send_template(user, "match_created", key=f"match:{match.id}", match=match, other=match.other(user))
    db.session.commit()


def notify_match_released(match: Match) -> None:
    """Ask whoever still has to confirm a released match to do so. Call after it's committed."""
    needs_mentor = bool((match.score_breakdown or {}).get("admin_approved_over_capacity"))
    for user, confirmed in ((match.mentee, match.mentee_confirmed_at),
                            (match.mentor, match.mentor_confirmed_at if needs_mentor else True)):
        if not confirmed:
            send_template(user, "match_released", key=f"match-release:{match.id}", match=match,
                          other=match.other(user))
    db.session.commit()


# --- calendar emails (each carries an invite; see app/ics.py) ---------------------

def notify_meeting(mt: Meeting, *, cancelled: bool = False) -> None:
    """Email both people an invite for a just-confirmed meeting, or a cancellation for one that was
    confirmed. Call with the meeting still loaded (before a delete is committed)."""
    for user in (mt.match.mentee, mt.match.mentor):
        send_template(user, "meeting_cancelled" if cancelled else "meeting_confirmed",
                      key=f"meeting-{'cancel' if cancelled else 'confirm'}:{mt.id}",
                      ics=ics.invite(ics.meeting_item(mt, user), user, cancel=cancelled),
                      meeting=mt, other=mt.match.other(user))
    db.session.commit()


def notify_session_created(event: Event) -> None:
    """Email every accepted mentee and mentor an invite to a new module session."""
    people = (db.session.query(User).join(Application, Application.user_id == User.id)
              .filter(User.role.in_(("mentee", "mentor")), User.is_active, Application.status == "accepted"))
    item = ics.session_item(event)
    for user in people:
        send_template(user, "session_created", key=f"session:{event.id}", ics=ics.invite(item, user), event=event)
    db.session.commit()


# --- new-message emails ----------------------------------------------------------
# Sent right after a message is posted (no background timers), at most one per thread per
# MESSAGE_EMAIL_COOLDOWN_MINUTES so a conversation doesn't flood the inbox. Messages sent during
# the cooldown are covered by the 24h unread reminder (app/reminders.py).

def email_unread_messages(match_id: int, sender_id: int) -> bool:
    """Email the other person in the match about sender's unread messages. True if one was sent."""
    match = db.session.get(Match, match_id)
    sender = db.session.get(User, sender_id)
    if match is None or sender is None or match.status != "approved":
        return False
    recipient = match.other(sender)
    unread = (db.session.query(Message)
              .filter(Message.match_id == match_id, Message.sender_id == sender_id, Message.read_at.is_(None))
              .count())
    if not unread:
        return False
    key = f"messages:{match_id}"
    since = utcnow() - timedelta(minutes=current_app.config["MESSAGE_EMAIL_COOLDOWN_MINUTES"])
    recent = (db.session.query(EmailLog)
              .filter(EmailLog.user_id == recipient.id, EmailLog.key == key, EmailLog.status != "failed",
                      EmailLog.created_at >= since)
              .first())
    if recent:
        return False
    ok = send_template(recipient, "new_messages", key=key, sender=sender, match=match, unread=unread)
    db.session.commit()
    return ok
