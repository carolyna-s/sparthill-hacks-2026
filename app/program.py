"""Program tools: events with prework/postwork, attendance check-ins, messaging, feedback."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import storage
from .extensions import db
from .models import (Agreement, AgreementSignature, Attendance, Event, Feedback, Match, Message,
                     Submission, User, utcnow)

bp = Blueprint("program", __name__)


# --- helpers shared with the dashboard and reminders ---------------------------

def unsigned_agreements(user: User) -> list[Agreement]:
    signed = {a for (a,) in db.session.query(AgreementSignature.agreement_id).filter_by(user_id=user.id)}
    return [a for a in db.session.query(Agreement)
            .filter(Agreement.is_active, Agreement.audience.in_(("all", user.role)))
            if a.id not in signed]


def upcoming_events(limit: int = 5) -> list[Event]:
    return (db.session.query(Event).filter(Event.starts_at >= utcnow() - timedelta(hours=12))
            .order_by(Event.starts_at).limit(limit).all())


def todo_for(user: User) -> list[tuple[Event, str]]:
    """Prework/postwork the user still owes, with a due date in the future or recently past."""
    done = {(s.event_id, s.kind) for s in db.session.query(Submission).filter_by(user_id=user.id)}
    now, out = utcnow(), []
    for e in db.session.query(Event).order_by(Event.starts_at):
        for kind in Submission.KINDS:
            prompt, due = getattr(e, f"{kind}_prompt"), getattr(e, f"{kind}_due")
            if prompt and due and (e.id, kind) not in done and due > now - timedelta(days=7):
                out.append((e, kind))
    return out


def _approved_match(match_id: int) -> Match:
    m = db.get_or_404(Match, match_id)
    if m.status != "approved" or not (m.includes(current_user) or current_user.is_staff):
        abort(404)
    return m


# --- events --------------------------------------------------------------------

@bp.get("/events")
@login_required
def events():
    rows = db.session.query(Event).order_by(Event.starts_at).all()
    return render_template("program/events.html", events=rows)


@bp.get("/events/<int:event_id>")
@login_required
def event(event_id: int):
    e = db.get_or_404(Event, event_id)
    subs = {s.kind: s for s in db.session.query(Submission).filter_by(event_id=e.id, user_id=current_user.id)}
    attended = db.session.query(Attendance).filter_by(event_id=e.id, user_id=current_user.id).first()
    fb = db.session.query(Feedback).filter_by(event_id=e.id, user_id=current_user.id).first()
    return render_template("program/event.html", e=e, subs=subs, attended=attended, feedback=fb)


@bp.post("/events/<int:event_id>/submit/<kind>")
@login_required
def submit(event_id: int, kind: str):
    e = db.get_or_404(Event, event_id)
    if kind not in Submission.KINDS or not getattr(e, f"{kind}_prompt"):
        abort(404)
    sub = (db.session.query(Submission).filter_by(event_id=e.id, user_id=current_user.id, kind=kind).first()
           or Submission(event_id=e.id, user_id=current_user.id, kind=kind))
    sub.body = request.form.get("body", "").strip()
    upload = request.files.get("file")
    if upload and upload.filename:
        sub.file_key = storage.save(upload, f"submissions/{e.id}/{current_user.id}")
        sub.file_name = upload.filename
    sub.submitted_at = utcnow()
    db.session.add(sub)
    db.session.commit()
    flash(f"{kind.capitalize()} submitted.", "ok")
    return redirect(url_for("program.event", event_id=e.id))


@bp.get("/submissions/<int:submission_id>/file")
@login_required
def submission_file(submission_id: int):
    sub = db.get_or_404(Submission, submission_id)
    if not sub.file_key or not (sub.user_id == current_user.id or current_user.is_staff):
        abort(404)
    return storage.serve(sub.file_key, sub.file_name or "upload")


@bp.post("/events/<int:event_id>/checkin")
@login_required
def checkin(event_id: int):
    e = db.get_or_404(Event, event_id)
    if request.form.get("code", "").strip().upper() != e.checkin_code.upper():
        flash("That check-in code doesn't match.", "error")
    elif not db.session.query(Attendance).filter_by(event_id=e.id, user_id=current_user.id).first():
        db.session.add(Attendance(event_id=e.id, user_id=current_user.id))
        db.session.commit()
        flash("Checked in.", "ok")
    return redirect(url_for("program.event", event_id=e.id))


@bp.post("/feedback")
@login_required
def feedback():
    rating = int(request.form.get("rating", 0))
    if not 1 <= rating <= 5:
        abort(400)
    event_id = request.form.get("event_id", type=int)
    match_id = request.form.get("match_id", type=int)
    if match_id:
        _approved_match(match_id)
    elif not (event_id and db.session.get(Event, event_id)):
        abort(400)
    db.session.add(Feedback(user_id=current_user.id, event_id=event_id, match_id=match_id, rating=rating,
                            comment=request.form.get("comment", "").strip()))
    db.session.commit()
    flash("Thanks for the feedback.", "ok")
    return redirect(request.referrer or url_for("main.dashboard"))


# --- messaging -----------------------------------------------------------------

@bp.get("/matches")
@login_required
def matches():
    rows = (db.session.query(Match)
            .filter(Match.status == "approved",
                    (Match.mentee_id == current_user.id) | (Match.mentor_id == current_user.id)).all())
    return render_template("program/matches.html", matches=rows)


@bp.route("/messages/<int:match_id>", methods=["GET", "POST"])
@login_required
def messages(match_id: int):
    m = _approved_match(match_id)
    if request.method == "POST":
        if not m.includes(current_user):
            abort(403)
        body = request.form.get("body", "").strip()
        if body:
            db.session.add(Message(match_id=m.id, sender_id=current_user.id, body=body))
            db.session.commit()
        return redirect(url_for("program.messages", match_id=m.id))
    if m.includes(current_user):  # staff viewing a thread doesn't mark it read
        (db.session.query(Message)
         .filter(Message.match_id == m.id, Message.sender_id != current_user.id, Message.read_at.is_(None))
         .update({"read_at": utcnow()}))
        db.session.commit()
    thread = db.session.query(Message).filter_by(match_id=m.id).order_by(Message.sent_at).all()
    return render_template("program/messages.html", m=m, thread=thread)
