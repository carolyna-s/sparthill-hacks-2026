"""Calendar feed, Google Calendar links and email invites (app/ics.py)."""

from datetime import datetime, timedelta

from app import ics
from app.extensions import db
from app.models import EmailLog, Event, Meeting, User, utcnow

from .conftest import login
from .test_emails import _approved_match


def _confirmed_meeting(client):
    match = _approved_match(client)  # logged in as the mentee
    when = (utcnow() + timedelta(days=3)).replace(hour=15, minute=0, second=0, microsecond=0)
    client.post(f"/messages/{match.id}/meetings", data={"starts_at": when.isoformat(), "duration": 45})
    mt = db.session.query(Meeting).filter_by(match_id=match.id).one()
    login(client, match.mentor.email)
    client.post(f"/meetings/{mt.id}/accept")
    return match, mt


def test_feed_needs_the_right_token(client):
    mentee = db.session.query(User).filter_by(email="jordan.kim@example.org").one()
    ok = client.get(f"/calendar/{mentee.id}/{ics.feed_token(mentee)}.ics")
    assert ok.status_code == 200 and ok.mimetype == "text/calendar"
    body = ok.get_data(as_text=True)
    assert "SUMMARY:Updating your Resume" in body and "SUMMARY:Pre-work due: Updating your Resume" in body
    assert client.get(f"/calendar/{mentee.id}/{'0' * 32}.ics").status_code == 404

    mentor = db.session.query(User).filter_by(email="priya.raman@example.org").one()
    body = client.get(f"/calendar/{mentor.id}/{ics.feed_token(mentor)}.ics").get_data(as_text=True)
    assert "SUMMARY:Updating your Resume" in body and "due:" not in body  # due dates are mentee-only


def test_times_convert_from_program_timezone_to_utc(app):
    e = db.session.query(Event).filter_by(title="Networking & LinkedIn").one()
    e.prework_due = datetime(2026, 11, 1, 17)  # PST (DST ended that morning) = UTC-8
    body = ics.calendar([ics.due_item(e, "prework")])
    assert "DTSTART:20261102T010000Z" in body
    assert all(len(line.encode()) <= 75 for line in body.split("\r\n"))
    assert "dates=20261102T010000Z%2F20261102T010000Z" in ics.google_link(ics.due_item(e, "prework"))


def test_confirmed_meeting_emails_both_an_invite_and_cancel_takes_it_back(client):
    match, mt = _confirmed_meeting(client)
    sent = db.session.query(EmailLog).filter_by(key=f"meeting-confirm:{mt.id}").all()
    assert {e.to_email for e in sent} == {match.mentee.email, match.mentor.email}
    assert "45 min" in sent[0].body

    client.post(f"/meetings/{mt.id}/cancel")
    cancelled = db.session.query(EmailLog).filter_by(key=f"meeting-cancel:{mt.id}").all()
    assert {e.to_email for e in cancelled} == {match.mentee.email, match.mentor.email}
    assert db.session.get(Meeting, mt.id) is None


def test_new_session_emails_accepted_people(client):
    login(client, "staff.admin@example.org")
    client.post("/staff/modules/new", data={"title": "Mock Interviews", "starts_at": "2026-11-18T18:00",
                                            "location": "Zoom"})
    event = db.session.query(Event).filter_by(title="Mock Interviews").one()
    sent = {e.to_email for e in db.session.query(EmailLog).filter_by(key=f"session:{event.id}")}
    assert "jordan.kim@example.org" in sent and "priya.raman@example.org" in sent
    assert "staff.admin@example.org" not in sent


def test_smtp_invite_is_an_inline_calendar_part(app, monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def starttls(self, context): pass
        def login(self, *a): pass
        def send_message(self, msg): sent.append(msg)

    import app.notify as notify
    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    app.config["EMAIL_BACKEND"] = "smtp"
    user = db.session.query(User).filter_by(email="jordan.kim@example.org").one()
    event = db.session.query(Event).first()
    notify.send_email(user.email, "Invite", "Body\n", user=user, ics=ics.invite(ics.session_item(event), user))
    parts = {p.get_content_type(): p for p in sent[0].walk()}
    assert parts["text/calendar"].get_param("method") == "REQUEST"
    assert "ATTENDEE;CN=Jordan Kim" in parts["text/calendar"].get_content()
    assert "application/ics" in parts
