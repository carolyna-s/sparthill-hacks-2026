"""Calendar files (RFC 5545) and Google Calendar links for sessions, due dates and meetings.

Times in the database are naive wall-clock times in PROGRAM_TIMEZONE (what people typed into
datetime-local inputs), so everything is converted to UTC here.

Two ways onto someone's calendar, neither needing a Google API key:
- a private per-user feed (`/calendar/<id>/<token>.ics`) Google Calendar subscribes to and refreshes
  every few hours; and
- invites attached to emails (METHOD:REQUEST, or METHOD:CANCEL to take one off), which Gmail shows
  with Yes / No / Maybe. Each item has a stable UID, so a reminder updates the same calendar entry.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from flask import current_app

from .models import Event, Meeting, Submission, User, utcnow

SESSION_MINUTES = 60  # sessions have a start time only


@dataclass
class Item:
    uid: str
    title: str
    starts_at: datetime  # naive, program timezone
    ends_at: datetime
    description: str = ""
    location: str = ""
    url: str = ""


def _base() -> str:
    return current_app.config["BASE_URL"].rstrip("/")


def session_item(e: Event) -> Item:
    url = f"{_base()}/modules/{e.id}"
    return Item(f"session-{e.id}", e.title, e.starts_at, e.starts_at + timedelta(minutes=SESSION_MINUTES),
                e.description or "", e.location or "", url)


def due_item(e: Event, kind: str) -> Item:
    due, url = getattr(e, f"{kind}_due"), f"{_base()}/modules/{e.id}"
    label = kind.replace("work", "-work").capitalize()
    return Item(f"{kind}-{e.id}", f"{label} due: {e.title}", due, due,
                getattr(e, f"{kind}_prompt") or "", "", url)


def meeting_item(mt: Meeting, user: User) -> Item:
    other = mt.match.other(user)
    return Item(f"meeting-{mt.id}", f"Mentorship meeting with {other.name}", mt.starts_at, mt.ends_at,
                mt.note or "", "", f"{_base()}/messages/{mt.match_id}")


def items_for(user: User) -> list[Item]:
    """Everything on the user's in-app calendar: sessions, their due dates (mentees), confirmed meetings."""
    from .extensions import db
    from .program import meetings_for

    out = []
    for e in db.session.query(Event).order_by(Event.starts_at):
        out.append(session_item(e))
        if user.role == "mentee":
            out += [due_item(e, k) for k in Submission.KINDS if getattr(e, f"{k}_prompt") and getattr(e, f"{k}_due")]
    return out + [meeting_item(mt, user) for mt in meetings_for(user)]


# --- formatting -----------------------------------------------------------------

def _utc(dt: datetime) -> datetime:
    tz = ZoneInfo(current_app.config["PROGRAM_TIMEZONE"])
    return dt.replace(tzinfo=tz).astimezone(timezone.utc)


def _stamp(dt: datetime) -> str:
    return _utc(dt).strftime("%Y%m%dT%H%M%SZ")


def _text(value: str) -> str:
    return (value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _fold(line: str) -> str:
    """Lines longer than 75 octets continue on the next line after a space."""
    raw, out = line.encode(), []
    while len(raw) > 75:
        cut = 75 if not out else 74
        while (raw[cut] & 0xC0) == 0x80:  # don't split a UTF-8 character
            cut -= 1
        out.append(raw[:cut].decode())
        raw = raw[cut:]
    out.append(raw.decode())
    return "\r\n ".join(out)


def calendar(items: list[Item], *, method: str | None = None, attendee: User | None = None,
             name: str | None = None) -> str:
    """A VCALENDAR. With method="REQUEST"/"CANCEL" and an attendee it's an email invite."""
    now = utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Spartan Mentorship Program//EN", "CALSCALE:GREGORIAN"]
    if method:
        lines.append(f"METHOD:{method}")
    if name:
        lines += [f"X-WR-CALNAME:{_text(name)}", "REFRESH-INTERVAL;VALUE=DURATION:PT4H"]
    host = current_app.config["BASE_URL"].split("//")[-1].split("/")[0].split(":")[0]
    for it in items:
        description = "\n\n".join(x for x in (it.description, it.url) if x)
        lines += ["BEGIN:VEVENT", f"UID:{it.uid}@{host}", f"DTSTAMP:{now}",
                  f"DTSTART:{_stamp(it.starts_at)}", f"DTEND:{_stamp(it.ends_at)}",
                  f"SUMMARY:{_text(it.title)}"]
        if description:
            lines.append(f"DESCRIPTION:{_text(description)}")
        if it.location:
            lines.append(f"LOCATION:{_text(it.location)}")
        if it.url:
            lines.append(f"URL:{it.url}")
        if method:
            lines += [f"SEQUENCE:{1 if method == 'CANCEL' else 0}",
                      f"STATUS:{'CANCELLED' if method == 'CANCEL' else 'CONFIRMED'}",
                      f"ORGANIZER;CN=Spartan Mentorship Program:mailto:{current_app.config['MAIL_FROM']}"]
            if attendee:
                lines.append(f"ATTENDEE;CN={_text(attendee.name)};ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;"
                             f"RSVP=TRUE:mailto:{attendee.email}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def invite(item: Item, user: User, *, cancel: bool = False) -> str:
    return calendar([item], method="CANCEL" if cancel else "REQUEST", attendee=user)


def google_link(item: Item) -> str:
    """Opens Google Calendar's "new event" page filled in with the item."""
    dates = f"{_stamp(item.starts_at)}/{_stamp(item.ends_at)}"
    details = "\n\n".join(x for x in (item.description, item.url) if x)
    return "https://calendar.google.com/calendar/render?" + urlencode(
        {"action": "TEMPLATE", "text": item.title, "dates": dates, "details": details, "location": item.location})


# --- per-user feed ---------------------------------------------------------------

def feed_token(user: User) -> str:
    key = current_app.config["SECRET_KEY"].encode()
    return hmac.new(key, f"calendar-feed:{user.id}".encode(), hashlib.sha256).hexdigest()[:32]


def feed_url(user: User) -> str:
    return f"{_base()}/calendar/{user.id}/{feed_token(user)}.ics"


def google_subscribe_url(user: User) -> str:
    """Google Calendar's "add calendar from URL" page, pre-filled with the user's feed."""
    webcal = "webcal://" + feed_url(user).split("://", 1)[1]
    return "https://calendar.google.com/calendar/r?cid=" + quote(webcal, safe="")
