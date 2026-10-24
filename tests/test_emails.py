from datetime import timedelta

from app.extensions import db
from app.models import Application, EmailLog, Match, Message, utcnow
from app.notify import email_unread_messages

from .conftest import login


def _released_match(client) -> Match:
    login(client, "staff.admin@example.org")
    pending = db.session.query(Application).filter_by(status="submitted").one()
    client.post(f"/staff/applications/{pending.id}", data={"decision": "accepted"})
    client.post("/staff/matching/propose-all")
    match = db.session.query(Match).filter_by(status="proposed").first()
    client.post(f"/staff/matches/{match.id}/approve")
    assert match.status == "released"
    return match


def _approved_match(client) -> Match:
    match = _released_match(client)
    login(client, match.mentee.email)
    client.post(f"/matches/{match.id}/confirmation", data={"response": "confirm"})
    assert match.status == "approved"
    return match


def test_released_match_asks_only_the_mentee_to_confirm(client):
    match = _released_match(client)
    sent = db.session.query(EmailLog).filter_by(key=f"match-release:{match.id}").one()
    assert sent.to_email == match.mentee.email
    assert sent.subject == f"Please confirm your match with {match.mentor.name}"
    assert f"/matches/{match.id}/confirmation" in sent.body


def test_match_confirmed_emails_both_people(client):
    match = _approved_match(client)
    sent = db.session.query(EmailLog).filter_by(key=f"match:{match.id}").all()
    assert {e.to_email for e in sent} == {match.mentee.email, match.mentor.email}
    to_mentee = next(e for e in sent if e.user_id == match.mentee_id)
    assert to_mentee.subject == f"You've been matched with {match.mentor.name}!"
    assert f"{match.mentor.name} is your mentor" in to_mentee.body
    assert f"/messages/{match.id}" in to_mentee.body


def test_new_message_email_once_per_hour_and_only_if_unread(client):
    match = _approved_match(client)
    key = f"messages:{match.id}"
    client.post(f"/messages/{match.id}", data={"body": "Hi!"})  # emailed right away
    email = db.session.query(EmailLog).filter_by(key=key).one()
    assert email.to_email == match.mentor.email
    assert email.subject == f"You have new messages from {match.mentee.name}!"
    assert "a new message" in email.body

    client.post(f"/messages/{match.id}", data={"body": "Are you free Tuesday?"})
    client.post(f"/messages/{match.id}", data={"body": "One more"})
    assert db.session.query(EmailLog).filter_by(key=key).count() == 1  # inside the 1h cooldown
    assert not email_unread_messages(match.id, match.mentee_id)
    email.created_at = utcnow() - timedelta(minutes=61)
    db.session.commit()

    login(client, match.mentor.email)
    client.get(f"/messages/{match.id}")  # mentor reads the thread
    assert not email_unread_messages(match.id, match.mentee_id)  # nothing unread, no email

    login(client, match.mentee.email)
    client.post(f"/messages/{match.id}", data={"body": "Ping"})  # cooldown over: emailed again
    assert db.session.query(EmailLog).filter_by(key=key).count() == 2
    assert db.session.query(Message).count() == 4
