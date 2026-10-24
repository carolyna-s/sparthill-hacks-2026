"""Automated reminders.

`send_due_reminders()` is idempotent: each reminder has a key, and ReminderLog stops the
same key going to the same person twice (every attempt, sent or failed, is also in EmailLog). Run it as often as you like — locally with
`flask send-reminders`, on AWS via EventBridge Scheduler → POST /internal/cron/reminders.
"""

from __future__ import annotations

from datetime import timedelta

from flask import current_app

from .extensions import db
from .models import Match, Message, ReminderLog, User, utcnow
from .notify import send_email
from .program import todo_for, unsigned_agreements


def due_reminders() -> list[tuple[User, str, str, str]]:
    """(user, key, subject, body) for everything currently worth a reminder."""
    cfg = current_app.config
    now = utcnow()
    soon = now + timedelta(hours=cfg["DUE_SOON_HOURS"])
    out = []
    for user in db.session.query(User).filter(User.role.in_(("mentee", "mentor"))):
        for a in unsigned_agreements(user):
            out.append((user, f"agreement:{a.id}", f"Please sign: {a.title}",
                        f"Sign it at {cfg['BASE_URL']}/agreements"))
        if not (user.application and user.application.status == "accepted"):
            continue
        for event, kind in todo_for(user):
            due = getattr(event, f"{kind}_due")
            if now <= due <= soon:
                out.append((user, f"{kind}:{event.id}", f"{kind.capitalize()} due soon: {event.title}",
                            f"Due {due:%b %d %H:%M}. Submit at {cfg['BASE_URL']}/modules/{event.id}"))

    cutoff = now - timedelta(hours=cfg["UNREAD_MESSAGE_HOURS"])
    unread = (db.session.query(Message).join(Match, Match.id == Message.match_id)
              .filter(Message.read_at.is_(None), Message.sent_at <= cutoff, Match.status == "approved"))
    for msg in unread:
        match = db.session.get(Match, msg.match_id)
        recipient = match.other(msg.sender)
        out.append((recipient, f"message:{msg.id}", f"Unread message from {msg.sender.name}",
                    f"Reply at {cfg['BASE_URL']}/messages/{match.id}"))
    return out


def send_due_reminders() -> int:
    sent_keys = {(r.user_id, r.key) for r in db.session.query(ReminderLog)}
    sent = 0
    for user, key, subject, body in due_reminders():
        if (user.id, key) in sent_keys:
            continue
        if not send_email(user.email, subject, f"Hi {user.name},\n\n{body}\n", user=user, key=key):
            continue  # not marked as sent, so the next run retries it
        db.session.add(ReminderLog(user_id=user.id, key=key))
        sent_keys.add((user.id, key))
        sent += 1
    db.session.commit()
    return sent

