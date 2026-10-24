"""Program tools: modules (sessions with prework/postwork), attendance check-ins, messaging, meetings, feedback.

Modules are stored in the `event` table.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import notify, storage
from .extensions import db
from .models import (Agreement, AgreementSignature, Attendance, Event, Feedback, Match, Meeting, Message,
                     Submission, User, utcnow)

bp = Blueprint("program", __name__)


def unread_message_count(user_id: int) -> int:
    return (db.session.query(Message)
            .join(Match, Match.id == Message.match_id)
            .filter(
                Match.status == "approved",
                (Match.mentee_id == user_id) | (Match.mentor_id == user_id),
                Message.sender_id != user_id,
                Message.read_at.is_(None),
            ).count())


@bp.app_context_processor
def _message_notifications():
    count = 0
    if current_user.is_authenticated and current_user.role in ("mentee", "mentor"):
        count = unread_message_count(current_user.id)
    return {"message_unread_count": count}


# --- helpers shared with the dashboard and reminders ---------------------------

def unsigned_agreements(user: User) -> list[Agreement]:
    signed = {a for (a,) in db.session.query(AgreementSignature.agreement_id).filter_by(user_id=user.id)}
    return [a for a in db.session.query(Agreement)
            .filter(Agreement.is_active, Agreement.audience.in_(("all", user.role)))
            if a.id not in signed]


def upcoming_modules(limit: int = 5) -> list[Event]:
    return (db.session.query(Event).filter(Event.starts_at >= utcnow() - timedelta(hours=12))
            .order_by(Event.starts_at).limit(limit).all())


def meetings_for(user: User, upcoming_only: bool = False) -> list[Meeting]:
    """Meetings in the user's approved matches."""
    q = (db.session.query(Meeting).join(Match, Meeting.match_id == Match.id)
         .filter(Match.status == "approved", (Match.mentee_id == user.id) | (Match.mentor_id == user.id)))
    if upcoming_only:
        q = q.filter(Meeting.starts_at >= utcnow() - timedelta(hours=1))
    return q.order_by(Meeting.starts_at).all()


def todo_for(user: User) -> list[tuple[Event, str]]:
    """Module prework/postwork a mentee still owes, with a due date in the future or recently past."""
    if user.role != "mentee":
        return []
    done = {(s.event_id, s.kind) for s in db.session.query(Submission).filter_by(user_id=user.id)}
    now, out = utcnow(), []
    for e in db.session.query(Event).order_by(Event.starts_at):
        for kind in Submission.KINDS:
            prompt, due = getattr(e, f"{kind}_prompt"), getattr(e, f"{kind}_due")
            if (prompt and due and e.is_open(kind) and (e.id, kind) not in done
                    and due > now - timedelta(days=7)):
                out.append((e, kind))
    return out


def mentees_of(mentor: User) -> list[User]:
    """The mentor's mentees in approved matches."""
    return [m.mentee for m in db.session.query(Match).filter_by(mentor_id=mentor.id, status="approved")]


def _approved_match(match_id: int) -> Match:
    m = db.get_or_404(Match, match_id)
    if m.status != "approved" or not (m.includes(current_user) or current_user.is_staff):
        abort(404)
    return m


# --- modules -------------------------------------------------------------------

@bp.get("/modules")
@login_required
def modules():
    rows = db.session.query(Event).order_by(Event.starts_at).all()
    subs = {(s.event_id, s.kind): s for s in db.session.query(Submission).filter_by(user_id=current_user.id)}
    # Mentors: how many of their mentees have submitted each item.
    mentees = mentees_of(current_user) if current_user.role == "mentor" else []
    counts: dict[tuple[int, str], int] = {}
    for s in db.session.query(Submission).filter(Submission.user_id.in_([u.id for u in mentees])):
        counts[(s.event_id, s.kind)] = counts.get((s.event_id, s.kind), 0) + 1
    return render_template("program/modules.html", modules=rows, subs=subs, mentees=mentees, counts=counts)


@bp.get("/modules/<int:event_id>")
@login_required
def module(event_id: int):
    e = db.get_or_404(Event, event_id)
    subs = {s.kind: s for s in db.session.query(Submission).filter_by(event_id=e.id, user_id=current_user.id)}
    attended = db.session.query(Attendance).filter_by(event_id=e.id, user_id=current_user.id).first()
    mentees = mentees_of(current_user) if current_user.role == "mentor" else []
    mentee_subs = {(s.user_id, s.kind): s for s in db.session.query(Submission)
                   .filter(Submission.event_id == e.id, Submission.user_id.in_([u.id for u in mentees]))}
    return render_template("program/module.html", e=e, subs=subs, attended=attended,
                           mentees=mentees, mentee_subs=mentee_subs)


@bp.post("/modules/<int:event_id>/submit/<kind>")
@login_required
def submit(event_id: int, kind: str):
    e = db.get_or_404(Event, event_id)
    if kind not in Submission.KINDS or not getattr(e, f"{kind}_prompt"):
        abort(404)
    if current_user.role != "mentee":  # mentors see what's assigned and their mentees' work, but don't submit
        abort(403)
    if not e.is_open(kind):
        flash("Post-work opens after the session.", "error")
        return redirect(url_for("program.module", event_id=e.id))
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
    return redirect(url_for("program.module", event_id=e.id))


@bp.get("/submissions/<int:submission_id>/file")
@login_required
def submission_file(submission_id: int):
    sub = db.get_or_404(Submission, submission_id)
    allowed = (sub.user_id == current_user.id or current_user.is_staff
               or sub.user_id in {u.id for u in mentees_of(current_user)})
    if not sub.file_key or not allowed:
        abort(404)
    return storage.serve(sub.file_key, sub.file_name or "upload")


@bp.post("/modules/<int:event_id>/checkin")
@login_required
def checkin(event_id: int):
    e = db.get_or_404(Event, event_id)
    if request.form.get("code", "").strip().upper() != e.checkin_code.upper():
        flash("That check-in code doesn't match.", "error")
    elif not db.session.query(Attendance).filter_by(event_id=e.id, user_id=current_user.id).first():
        db.session.add(Attendance(event_id=e.id, user_id=current_user.id))
        db.session.commit()
        flash("Checked in.", "ok")
    return redirect(url_for("program.module", event_id=e.id))


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
# Messaging opens only once a mentee and mentor are in an approved match. Until then the
# Messages tab is shown locked and leads to a notice saying what they're waiting for.

def _approved_matches(user: User) -> list[Match]:
    return (db.session.query(Match)
            .filter(Match.status == "approved", (Match.mentee_id == user.id) | (Match.mentor_id == user.id))
            .all())


@bp.app_context_processor
def _messages_nav():
    locked = (current_user.is_authenticated and current_user.role in ("mentee", "mentor")
              and not _approved_matches(current_user))
    return {"messages_locked": locked}


def _messages_locked(match: Match | None = None):
    """The notice shown instead of messages: the pending match (if any) says what's left."""
    if match is None:
        match = (db.session.query(Match)
                 .filter(Match.status.in_(("proposed", "released")),
                         (Match.mentee_id == current_user.id) | (Match.mentor_id == current_user.id))
                 .order_by(Match.proposed_at.desc()).first())
    return render_template("program/messages_locked.html", pending=match)


@bp.get("/messages/")
@login_required
def inbox():
    rows = _approved_matches(current_user)
    if not rows:
        return _messages_locked()
    if len(rows) == 1:
        return redirect(url_for("program.messages", match_id=rows[0].id))
    # Several: list the threads.
    threads = []
    for m in rows:
        last = db.session.query(Message).filter_by(match_id=m.id).order_by(Message.sent_at.desc()).first()
        unread = (db.session.query(Message)
                  .filter(Message.match_id == m.id, Message.sender_id != current_user.id, Message.read_at.is_(None))
                  .count())
        threads.append((m, last, unread))
    threads.sort(key=lambda t: t[1].sent_at if t[1] else datetime.min, reverse=True)
    awaiting = (db.session.query(Match)
                .filter(Match.status == "released",
                        (Match.mentee_id == current_user.id) | (Match.mentor_id == current_user.id)).count())
    return render_template("program/inbox.html", threads=threads, awaiting=awaiting)


@bp.route("/messages/<int:match_id>", methods=["GET", "POST"])
@login_required
def messages(match_id: int):
    pending = db.session.get(Match, match_id)
    if pending and pending.includes(current_user) and pending.status in ("proposed", "released"):
        return _messages_locked(pending)
    m = _approved_match(match_id)
    if request.method == "POST":
        if not m.includes(current_user):
            abort(403)
        body = request.form.get("body", "").strip()
        if body:
            db.session.add(Message(match_id=m.id, sender_id=current_user.id, body=body))
            db.session.commit()
            notify.email_unread_messages(m.id, current_user.id)
        return redirect(url_for("program.messages", match_id=m.id))
    if m.includes(current_user):  # staff viewing a thread doesn't mark it read
        (db.session.query(Message)
         .filter(Message.match_id == m.id, Message.sender_id != current_user.id, Message.read_at.is_(None))
         .update({"read_at": utcnow()}))
        db.session.commit()
    thread = db.session.query(Message).filter_by(match_id=m.id).order_by(Message.sent_at.desc()).all()
    meetings = (db.session.query(Meeting).filter(Meeting.match_id == m.id, Meeting.starts_at >= utcnow() - timedelta(hours=1))
                .order_by(Meeting.starts_at).all())
    return render_template("program/messages.html", m=m, thread=thread, meetings=meetings, now=utcnow())


@bp.get("/messages/<int:match_id>/updates")
@login_required
def message_updates(match_id: int):
    m = _approved_match(match_id)
    if m.includes(current_user):
        (db.session.query(Message)
         .filter(Message.match_id == m.id, Message.sender_id != current_user.id, Message.read_at.is_(None))
         .update({"read_at": utcnow()}))
        db.session.commit()
    thread = db.session.query(Message).filter_by(match_id=m.id).order_by(Message.sent_at.desc()).all()
    html = render_template("program/_message_list.html", m=m, thread=thread)
    count = unread_message_count(current_user.id) if current_user.role in ("mentee", "mentor") else 0
    response = jsonify(messages_html=html, unread_count=count)
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/messages/unread-count")
@login_required
def unread_count():
    count = unread_message_count(current_user.id) if current_user.role in ("mentee", "mentor") else 0
    response = jsonify(unread_count=count)
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.post("/messages/<int:match_id>/meetings")
@login_required
def schedule_meeting(match_id: int):
    """The mentor picks a date and time; it lands on both calendars and is announced in the thread."""
    m = _approved_match(match_id)
    if current_user.id != m.mentor_id:
        abort(403)
    try:
        starts_at = datetime.fromisoformat(request.form.get("starts_at", ""))
    except ValueError:
        flash("Pick a date and time for the meeting.", "error")
        return redirect(url_for("program.messages", match_id=m.id))
    note = request.form.get("note", "").strip()[:200]
    db.session.add(Meeting(match_id=m.id, starts_at=starts_at, note=note, created_by_id=current_user.id))
    db.session.add(Message(match_id=m.id, sender_id=current_user.id,
                           body=f"📅 Scheduled a meeting for {starts_at:%a, %b %d at %I:%M %p}." + (f" {note}" if note else "")))
    db.session.commit()
    notify.email_unread_messages(m.id, current_user.id)
    flash("Meeting scheduled.", "ok")
    return redirect(url_for("program.messages", match_id=m.id))


@bp.post("/meetings/<int:meeting_id>/cancel")
@login_required
def cancel_meeting(meeting_id: int):
    mt = db.get_or_404(Meeting, meeting_id)
    if current_user.id != mt.match.mentor_id:
        abort(403)
    db.session.add(Message(match_id=mt.match_id, sender_id=current_user.id,
                           body=f"Cancelled the meeting on {mt.starts_at:%a, %b %d at %I:%M %p}."))
    db.session.delete(mt)
    db.session.commit()
    notify.email_unread_messages(mt.match_id, current_user.id)
    flash("Meeting cancelled.", "ok")
    return redirect(url_for("program.messages", match_id=mt.match_id))
