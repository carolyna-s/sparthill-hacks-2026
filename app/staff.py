"""Staff dashboard: applicant review, participant dashboards, match approval, modules, and
aggregate reporting."""

from __future__ import annotations

import secrets
from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user
from sqlalchemy import func

from . import matching, program
from .auth import role_required
from .extensions import db
from .intake import Personality_Questions_Data, missing_fields
from .models import (Application, Attendance, Event, Feedback, Match, MatchExclusion, MatchFeedback,
                     Message, Submission, User, utcnow)

bp = Blueprint("staff", __name__, url_prefix="/staff")

# Labels for MatchFeedback.REASONS["deny"], in the order staff see them.
DENY_REASONS = {
    "interests_or_pathway": "Different interests or pathway",
    "experience_gap": "Experience gap is wrong",
    "language_or_communication": "Language or communication",
    "fit_concern": "Personality or fit concern",
    "mentor_overloaded": "Mentor is overloaded",
    "conflict_of_interest": "Conflict of interest",
    "other": "Other",
}


@bp.before_request
@role_required("staff", "backend")
def _staff_only():
    return None


@bp.context_processor
def _reason_labels():
    return {"deny_reasons": DENY_REASONS}


def denials_for(match_ids) -> dict[int, list[MatchFeedback]]:
    rows = (db.session.query(MatchFeedback)
            .filter(MatchFeedback.kind == "deny", MatchFeedback.match_id.in_(list(match_ids)))
            .order_by(MatchFeedback.created_at))
    out: dict[int, list[MatchFeedback]] = {}
    for f in rows:
        out.setdefault(f.match_id, []).append(f)
    return out


@bp.get("/")
def overview():
    by_status = dict(db.session.query(Application.status, func.count(Application.id))
                     .group_by(Application.status).all())
    return render_template("staff/overview.html", by_status=by_status, report=report_data(),
                           proposed=db.session.query(Match).filter_by(status="proposed").count())


# --- applicant review ------------------------------------------------------------

@bp.get("/applications")
def applications():
    status = request.args.get("status", "submitted")
    role = request.args.get("role")
    q = db.session.query(Application).join(User, User.id == Application.user_id).filter(Application.status == status)
    if role:
        q = q.filter(User.role == role)
    return render_template("staff/applications.html", rows=q.order_by(Application.submitted_at).all(),
                           status=status, role=role)


@bp.route("/applications/<int:app_id>", methods=["GET", "POST"])
def application(app_id: int):
    a = db.get_or_404(Application, app_id)
    if request.method == "POST":
        decision = request.form.get("decision")
        if decision not in ("accepted", "rejected"):
            abort(400)
        before = a.status
        a.status, a.reviewed_by_id, a.reviewed_at = decision, current_user.id, utcnow()
        a.staff_notes = request.form.get("staff_notes", "")
        db.session.commit()
        _offer_undo(f"{a.user.name}: {decision}.", url_for("staff.undo_application", app_id=a.id),
                    status=before)
        return redirect(url_for("staff.applications", status=before))
    return render_template("staff/application.html", a=a,
                           Personality_Questions_Data=Personality_Questions_Data[a.user.role])


@bp.post("/applications/<int:app_id>/undo")
def undo_application(app_id: int):
    """Put an application back to the status it had before the last decision."""
    a = db.get_or_404(Application, app_id)
    status = request.form.get("status")
    if status not in ("draft", "submitted", "accepted", "rejected"):
        abort(400)
    if status != "accepted" and a.status == "accepted" and db.session.query(Match).filter(
            (Match.mentee_id == a.user_id) | (Match.mentor_id == a.user_id),
            Match.status.in_(("proposed", "approved"))).first():
        flash(f"{a.user.name} is already in a match. Cancel or end it before undoing the acceptance.", "error")
    else:
        a.status = status
        db.session.commit()
        flash(f"Undone: {a.user.name} is {status} again.", "ok")
    return redirect(url_for("staff.application", app_id=a.id))


# --- participant dashboards --------------------------------------------------------

def dashboard_for(user: User) -> dict:
    """What a mentee or mentor sees on their own dashboard, for staff."""
    matches = (db.session.query(Match)
               .filter((Match.mentee_id == user.id) | (Match.mentor_id == user.id))
               .order_by(Match.proposed_at.desc()).all())
    return {"user": user, "application": user.application, "missing": missing_fields(user),
            "unsigned": program.unsigned_agreements(user), "matches": matches,
            "active": [m for m in matches if m.status in ("proposed", "approved")],
            "todo": program.todo_for(user)}


@bp.get("/people")
def people():
    role = request.args.get("role") if request.args.get("role") in ("mentee", "mentor") else None
    q = request.args.get("q", "").strip()
    query = db.session.query(User).filter(User.role.in_((role,) if role else ("mentee", "mentor")))
    if q:
        query = query.filter(User.name.ilike(f"%{q}%") | User.email.ilike(f"%{q}%"))
    rows = [dashboard_for(u) for u in query.order_by(User.role, User.name)]
    return render_template("staff/people.html", rows=rows, role=role, q=q)


@bp.get("/people/<int:user_id>")
def person(user_id: int):
    user = db.get_or_404(User, user_id)
    if user.role not in ("mentee", "mentor"):
        abort(404)
    d = dashboard_for(user)
    attended = (db.session.query(Event, Attendance.checked_in_at)
                .join(Attendance, Attendance.event_id == Event.id)
                .filter(Attendance.user_id == user.id).order_by(Event.starts_at.desc()).all())
    return render_template("staff/person.html", d=d, attended=attended,
                           denials=denials_for(m.id for m in d["matches"]))


# --- matching ----------------------------------------------------------------------

def _back(default: str) -> str:
    """Where to go after an action: the page it was taken from, if that's a page of ours."""
    target = request.form.get("next", "")
    return target if target.startswith("/") and not target.startswith("//") else default


def _offer_undo(text: str, action: str, **fields) -> None:
    """Show `text` on the next page with an Undo button that POSTs `fields` to `action`."""
    session["undo"] = {"text": text, "action": action, "fields": fields}


@bp.get("/matching")
def matching_page():
    unmatched = (db.session.query(User).filter(User.id.in_(matching.unmatched_mentee_ids()))
                 .order_by(User.name).all())
    rankings = {u.id: matching.ranking_for(u.id) for u in unmatched}
    mentors = {u.id: u for u in db.session.query(User).filter_by(role="mentor")}
    proposed = db.session.query(Match).filter_by(status="proposed").order_by(Match.score.desc()).all()
    approved = db.session.query(Match).filter_by(status="approved").order_by(Match.decided_at.desc()).all()
    rejected = (db.session.query(MatchFeedback).filter_by(kind="deny")
                .order_by(MatchFeedback.created_at.desc()).limit(20).all())
    messaged = {mid for (mid,) in db.session.query(Message.match_id).distinct()}
    return render_template("staff/matching.html", unmatched=unmatched, rankings=rankings, mentors=mentors,
                           proposed=proposed, approved=approved, rejected=rejected,
                           messaged=messaged)


@bp.get("/matches/<int:match_id>")
def match_review(match_id: int):
    """The full overview of a pair. ?action=approve or ?action=reject turns it into that
    decision's confirmation step."""
    m = db.get_or_404(Match, match_id)
    action = request.args.get("action") if m.status == "proposed" else None
    mentees_of_mentor = (db.session.query(Match)
                         .filter(Match.mentor_id == m.mentor_id, Match.id != m.id,
                                 Match.status.in_(("proposed", "approved"))).all())
    return render_template("staff/match.html", m=m,
                           action=action if action in ("approve", "reject") else None,
                           questions=Personality_Questions_Data, mentees_of_mentor=mentees_of_mentor,
                           denials=denials_for([m.id]).get(m.id, []))


@bp.post("/matching/propose-all")
def propose_all():
    created = matching.propose_all()
    left = len(matching.unmatched_mentee_ids())
    if created:
        _offer_undo(f"Proposed {len(created)} matches." + (f" {left} mentees couldn't be matched (no compatible "
                                                           "mentor with an open slot)." if left else ""),
                    url_for("staff.cancel_proposals"), ids=[m.id for m in created])
    else:
        flash("Nothing to propose: every accepted mentee already has a match or no mentor is free.", "ok")
    return redirect(url_for("staff.matching_page"))


@bp.post("/matching/cancel")
def cancel_proposals():
    """Undo proposals: delete them so the mentees are unmatched again."""
    q = db.session.query(Match).filter_by(status="proposed")
    if not request.form.get("all"):
        q = q.filter(Match.id.in_(request.form.getlist("ids", type=int)))
    cancelled = 0
    for m in q.all():
        db.session.delete(m)
        cancelled += 1
    db.session.commit()
    flash(f"Cancelled {cancelled} proposal(s).", "ok")
    return redirect(_back(url_for("staff.matching_page")))


@bp.post("/matching/propose")
def propose_one():
    mentee_id, mentor_id = int(request.form["mentee_id"]), int(request.form["mentor_id"])
    if mentee_id not in matching.unmatched_mentee_ids():
        abort(409)
    choice = next((c for c in matching.ranking_for(mentee_id, limit=None) if c.mentor_id == mentor_id), None)
    if choice is None:
        abort(409)  # mentor not accepted or already matched
    m = Match(mentee_id=mentee_id, mentor_id=mentor_id, score=choice.score, score_breakdown=choice.breakdown,
              rematch_round=matching.rematch_round(mentee_id))
    db.session.add(m)
    db.session.commit()
    _offer_undo(f"Added {m.mentee.name} → {m.mentor.name} to the proposals. Approve or reject it above.",
                url_for("staff.cancel_proposals"), ids=[m.id])
    return redirect(url_for("staff.matching_page"))


# decision: (status it applies to, status it leads to). The last three undo the first three.
DECISIONS = {"approve": ("proposed", "approved"), "reject": ("proposed", "rejected"),
             "end": ("approved", "ended"),
             "unapprove": ("approved", "proposed"), "unreject": ("rejected", "proposed"),
             "reopen": ("ended", "approved")}
UNDO = {"approve": "unapprove", "reject": "unreject", "end": "reopen"}


def _undo_blocker(m: Match, decision: str) -> str | None:
    """Why this undo can't happen right now, if it can't."""
    if decision == "unapprove" and db.session.query(Message).filter_by(match_id=m.id).first():
        return "They've already started messaging, so the approval can't be undone. End the match instead."
    if decision in ("unreject", "reopen"):
        other = (db.session.query(Match)
                 .filter(Match.mentee_id == m.mentee_id, Match.id != m.id,
                         Match.status.in_(("proposed", "approved"))).first())
        if other:
            return (f"{m.mentee.name} already has another match ({other.mentor.name}, {other.status}). "
                    "Cancel or end that one first.")
        if matching.open_slots().get(m.mentor_id, 0) <= 0:
            return f"{m.mentor.name} already has a mentee (mentorship is one-to-one)."
    return None


@bp.post("/matches/<int:match_id>/<decision>")
def decide_match(match_id: int, decision: str):
    m = db.get_or_404(Match, match_id)
    if decision not in DECISIONS:
        abort(400)
    back = _back(url_for("staff.matching_page"))
    if m.status != DECISIONS[decision][0]:
        flash(f"This match is already {m.status}, so that can't be done anymore.", "error")
        return redirect(back)
    blocker = _undo_blocker(m, decision)
    if blocker:
        flash(blocker, "error")
        return redirect(back)
    pair = f"{m.mentee.name} → {m.mentor.name}"
    if decision in ("unapprove", "unreject"):
        if decision == "unreject":
            # The rejection is taken back, so it shouldn't teach the matching anything or block the pair.
            denials = db.session.query(MatchFeedback).filter_by(match_id=m.id, kind="deny")
            ids = [f.id for f in denials]
            db.session.query(MatchExclusion).filter(MatchExclusion.feedback_id.in_(ids)).delete()
            denials.delete()
        m.status, m.decided_by_id, m.decided_at = "proposed", None, None
        db.session.commit()
        flash(f"Undone: {pair} is back in the proposals.", "ok")
        return redirect(back)
    if decision == "reject":
        # A rejection needs a reason (the matching loop learns from it); "other" needs it written out.
        reason, comment = request.form.get("reason"), request.form.get("comment", "").strip()
        if reason not in MatchFeedback.REASONS["deny"] or (reason == "other" and not comment):
            flash("To reject a match, pick a reason" + (" and describe it." if reason == "other" else "."), "error")
            return redirect(url_for("staff.match_review", match_id=m.id, action="reject"))
        feedback = MatchFeedback(match_id=m.id, author_id=current_user.id, kind="deny",
                                 reason=reason, comment=comment)
        db.session.add(feedback)
        db.session.flush()
        if (m.mentee_id, m.mentor_id) not in matching.excluded_pairs():
            db.session.add(MatchExclusion(mentee_id=m.mentee_id, mentor_id=m.mentor_id,
                                          cohort_id=m.cohort_id, feedback_id=feedback.id))
    m.status, m.decided_by_id, m.decided_at = DECISIONS[decision][1], current_user.id, utcnow()
    db.session.commit()
    done = {"approve": f"Approved {pair}.", "end": f"Ended {pair}.",
            "reject": f"Rejected {pair}. They won't be proposed together again.",
            "reopen": f"Reopened {pair}."}[decision]
    if decision in UNDO:
        _offer_undo(done, url_for("staff.decide_match", match_id=m.id, decision=UNDO[decision]), next=back)
    else:
        flash(done, "ok")
    return redirect(back)


# --- modules -----------------------------------------------------------------------

def _dt(name: str) -> datetime | None:
    value = request.form.get(name)
    return datetime.fromisoformat(value) if value else None


@bp.route("/modules/new", methods=["GET", "POST"])
def new_event():
    if request.method == "POST":
        db.session.add(Event(
            title=request.form["title"], description=request.form.get("description", ""),
            starts_at=_dt("starts_at"), location=request.form.get("location", ""),
            checkin_code=secrets.token_hex(3).upper(),
            prework_prompt=request.form.get("prework_prompt", ""), prework_due=_dt("prework_due"),
            postwork_prompt=request.form.get("postwork_prompt", ""), postwork_due=_dt("postwork_due"),
        ))
        db.session.commit()
        flash("Module created.", "ok")
        return redirect(url_for("program.modules"))
    return render_template("staff/event_form.html")


# --- reporting ---------------------------------------------------------------------

def report_data() -> dict:
    participants = db.session.query(User).filter(User.role.in_(("mentee", "mentor"))).count()
    events = db.session.query(Event).order_by(Event.starts_at).all()
    attendance = dict(db.session.query(Attendance.event_id, func.count(Attendance.id))
                      .group_by(Attendance.event_id).all())
    subs = {(e, k): n for e, k, n in db.session.query(Submission.event_id, Submission.kind,
                                                      func.count(Submission.id))
            .group_by(Submission.event_id, Submission.kind)}
    event_rating = dict(db.session.query(Feedback.event_id, func.avg(Feedback.rating))
                        .filter(Feedback.event_id.isnot(None)).group_by(Feedback.event_id).all())
    match_rating = db.session.query(func.avg(Feedback.rating)).filter(Feedback.match_id.isnot(None)).scalar()
    active_matches = db.session.query(Match).filter_by(status="approved").count()
    messaging_matches = db.session.query(func.count(func.distinct(Message.match_id))).scalar()
    return {
        "participants": participants,
        "active_matches": active_matches,
        "messaging_rate": (messaging_matches / active_matches) if active_matches else None,
        "avg_match_rating": match_rating,
        "events": [{
            "event": e,
            "attended": attendance.get(e.id, 0),
            "prework": subs.get((e.id, "prework"), 0),
            "postwork": subs.get((e.id, "postwork"), 0),
            "rating": event_rating.get(e.id),
        } for e in events],
    }


@bp.get("/reports")
def reports():
    return render_template("staff/reports.html", report=report_data())
