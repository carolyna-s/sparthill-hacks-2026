"""Automated reminders.

`send_due_reminders()` is idempotent: each reminder has a key, and ReminderLog stops the
same key going to the same person twice (every attempt, sent or failed, is also in EmailLog). Run it as often as you like — locally with
`flask send-reminders`, on Cloud Run via Cloud Scheduler → POST /internal/cron/reminders.
"""

from __future__ import annotations

from datetime import timedelta

from flask import current_app

from . import ics
from .extensions import db
from .models import Match, Meeting, Message, ReminderLog, User, utcnow
from .notify import send_email
from .program import todo_for, unsigned_agreements


def due_reminders() -> list[tuple[User, str, str, str, str | None]]:
    """(user, key, subject, body, calendar invite or None) for everything currently worth a reminder."""
    cfg = current_app.config
    now = utcnow()
    soon = now + timedelta(hours=cfg["DUE_SOON_HOURS"])
    out = []
    for user in db.session.query(User).filter(User.role.in_(("mentee", "mentor"))):
        for a in unsigned_agreements(user):
            out.append((user, f"agreement:{a.id}", f"Please sign: {a.title}",
                        f"Sign it at {cfg['BASE_URL']}/agreements", None))
        if not (user.application and user.application.status == "accepted"):
            continue
        for event, kind in todo_for(user):
            due = getattr(event, f"{kind}_due")
            if now <= due <= soon:
                out.append((user, f"{kind}:{event.id}", f"{kind.capitalize()} due soon: {event.title}",
                            f"Due {due:%b %d %H:%M}. Submit at {cfg['BASE_URL']}/modules/{event.id}",
                            ics.invite(ics.due_item(event, kind), user)))

    cutoff = now - timedelta(hours=cfg["UNREAD_MESSAGE_HOURS"])
    unread = (db.session.query(Message).join(Match, Match.id == Message.match_id)
              .filter(Message.read_at.is_(None), Message.sent_at <= cutoff, Match.status == "approved"))
    for msg in unread:
        match = db.session.get(Match, msg.match_id)
        recipient = match.other(msg.sender)
        out.append((recipient, f"message:{msg.id}", f"Unread message from {msg.sender.name}",
                    f"Reply at {cfg['BASE_URL']}/messages/{match.id}", None))

    upcoming = (db.session.query(Meeting).join(Match, Match.id == Meeting.match_id)
                .filter(Meeting.status == "confirmed", Meeting.starts_at > now,
                        Meeting.starts_at <= now + timedelta(hours=cfg["MEETING_REMINDER_HOURS"]),
                        Match.status == "approved"))
    for mt in upcoming:
        for user in (mt.match.mentee, mt.match.mentor):
            other = mt.match.other(user)
            out.append((user, f"meeting:{mt.id}", f"Reminder: meeting with {other.name} tomorrow",
                        f"You have a meeting with {other.name} on {mt.starts_at:%a, %b %d at %I:%M %p}."
                        + (f" {mt.note}" if mt.note else "")
                        + f"\n\nSee the thread at {cfg['BASE_URL']}/messages/{mt.match_id}",
                        ics.invite(ics.meeting_item(mt, user), user)))
    return out


def send_due_reminders() -> int:
    sent_keys = {(r.user_id, r.key) for r in db.session.query(ReminderLog)}
    sent = 0
    for user, key, subject, body, invite in due_reminders():
        if (user.id, key) in sent_keys:
            continue
        if not send_email(user.email, subject, f"Hi {user.name},\n\n{body}\n", user=user, key=key, ics=invite):
            continue  # not marked as sent, so the next run retries it
        db.session.add(ReminderLog(user_id=user.id, key=key))
        sent_keys.add((user.id, key))
        sent += 1
    db.session.commit()
    return sent

