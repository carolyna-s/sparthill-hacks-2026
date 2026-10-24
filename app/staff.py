"""Staff dashboard: applicants, participant dashboards, match approval, modules, and
aggregate reporting."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user
from sqlalchemy import func

from . import matching, notify, program
from .audit import record_change
from .auth import role_required
from .extensions import db
from .intake import Personality_Questions_Data, missing_fields
from .models import (Application, Attendance, Cohort, Event, Feedback, Match, MatchExclusion,
                     MatchFeedback, MatchOverrideRequest, Submission, User, utcnow)

bp = Blueprint("staff", __name__, url_prefix="/staff")

# Review order for proposals: flagged pairs (NULL score: no shared time slot) first, since they
# need a staff decision, then best score first. Explicit because SQLite and Postgres put NULLs
# at opposite ends by default.
QUEUE_ORDER = (Match.score.desc().nulls_first(), Match.id.asc())

# Labels for MatchFeedback.REASONS["deny"], in the order staff see them.
DENY_REASONS = {
    "interests_or_pathway": "Different interests or pathway",
    "experience_gap": "Experience gap is wrong",
    "language_or_communication": "Language or communication",
    "fit_concern": "Personality or fit concern",
    "mentor_overloaded": "Mentor is overloaded",
    "conflict_of_interest": "Conflict of interest",
    "other": "Other",
    "mentee_rejection": "Mentee Rejection",
    "mentee_withdrawn": "Mentee Withdrawn",
    "mentor_rejection": "Mentor Rejection",
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
            .filter(MatchFeedback.kind.in_(("deny", "withdraw")),
                    MatchFeedback.match_id.in_(list(match_ids)))
            .order_by(MatchFeedback.created_at))
    out: dict[int, list[MatchFeedback]] = {}
    for f in rows:
        out.setdefault(f.match_id, []).append(f)
    return out


@bp.get("/")
def overview():
    applicant_count = (db.session.query(Application)
                       .filter(Application.status != "draft").count())
    people = (db.session.query(User).filter(User.role.in_(("mentee", "mentor")))
              .order_by(User.name).all())
    pairs = (db.session.query(Match).filter_by(status="approved")
             .join(User, User.id == Match.mentee_id).order_by(User.name).all())
    return render_template("staff/overview.html", applicant_count=applicant_count, report=report_data(),
                           mentors=[u for u in people if u.role == "mentor"],
                           mentees=[u for u in people if u.role == "mentee"], pairs=pairs,
                           proposed=db.session.query(Match).filter_by(status="proposed").count())


# --- applicants ------------------------------------------------------------------

@bp.get("/applications")
def applications():
    users = (db.session.query(User)
             .join(Application, Application.user_id == User.id)
             .filter(User.role.in_(("mentee", "mentor")), Application.status == "accepted")
             .order_by(User.name).all())
    rows = [dashboard_for(user) for user in users]
    return render_template("staff/applications.html", rows=rows, q=request.args.get("q", "").strip())


@bp.get("/applications/<int:app_id>")
def application(app_id: int):
    a = db.get_or_404(Application, app_id)
    return render_template("staff/application.html", a=a,
                           Personality_Questions_Data=Personality_Questions_Data[a.user.role])


# --- participant dashboards --------------------------------------------------------

def dashboard_for(user: User) -> dict:
    """What a mentee or mentor sees on their own dashboard, for staff."""
    matches = (db.session.query(Match)
               .filter((Match.mentee_id == user.id) | (Match.mentor_id == user.id))
               .order_by(Match.proposed_at.desc()).all())
    return {"user": user, "application": user.application, "missing": missing_fields(user),
            "unsigned": program.unsigned_agreements(user), "matches": matches,
            "active": [m for m in matches if m.status in ("proposed", "released", "approved")],
            "todo": program.todo_for(user)}


@bp.get("/people")
def people():
    return redirect(url_for("staff.applications", **request.args))


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
    accepted_mentors = matching.accepted_profiles("mentor")
    mentors = {}
    if accepted_mentors:
        mentors = {u.id: u for u in db.session.query(User).filter(User.id.in_(accepted_mentors))}
    proposed = db.session.query(Match).filter_by(status="proposed").order_by(*QUEUE_ORDER).all()
    awaiting_confirmation = (db.session.query(Match).filter_by(status="released")
                             .order_by(Match.released_at.desc()).all())
    approved = db.session.query(Match).filter_by(status="approved").order_by(Match.decided_at.desc()).all()
    rejected = (db.session.query(MatchFeedback).filter(MatchFeedback.kind.in_(("deny", "withdraw")))
                .order_by(MatchFeedback.created_at.desc()).limit(20).all())
    mentor_loads = dict(
        db.session.query(Match.mentor_id, func.count(Match.id))
        .filter(Match.status.in_(("proposed", "released", "approved")))
        .group_by(Match.mentor_id).all()
    )
    override_mentee_id = request.args.get("override_mentee", type=int)
    return render_template("staff/matching.html", unmatched=unmatched, rankings=rankings, mentors=mentors,
                           proposed=proposed, awaiting_confirmation=awaiting_confirmation,
                           approved=approved, rejected=rejected,
                           mentor_loads=mentor_loads, mentor_capacity=matching.MENTEES_PER_MENTOR,
                           open_mentor_count=sum(
                               mentor_loads.get(mentor_id, 0) < matching.MENTEES_PER_MENTOR
                               for mentor_id in mentors
                           ),
                           override_mentee_id=override_mentee_id)


@bp.get("/matches/<int:match_id>")
def match_review(match_id: int):
    """The full overview of a pair. ?action=approve or ?action=reject turns it into that
    decision's confirmation step."""
    m = db.get_or_404(Match, match_id)
    action = request.args.get("action") if m.status == "proposed" else None
    mentees_of_mentor = (db.session.query(Match)
                         .filter(Match.mentor_id == m.mentor_id, Match.id != m.id,
                                 Match.status.in_(("proposed", "released", "approved"))).all())
    return render_template("staff/match.html", m=m,
                           action=action if action in ("approve", "reject") else None,
                           queue=request.args.get("queue") == "1",
                           questions=Personality_Questions_Data, mentees_of_mentor=mentees_of_mentor,
                           denials=denials_for([m.id]).get(m.id, []))


def _next_queued_proposal(match: Match) -> Match | None:
    """Find the next pending row in the same stable order used by Matching (QUEUE_ORDER)."""
    if match.score is None:
        after = Match.score.isnot(None) | (Match.score.is_(None) & (Match.id > match.id))
    else:
        after = (Match.score < match.score) | ((Match.score == match.score) & (Match.id > match.id))
    pending = db.session.query(Match).filter_by(status="proposed").order_by(*QUEUE_ORDER)
    return pending.filter(after).first() or pending.first()


def _queue_destination(match: Match) -> str:
    following = _next_queued_proposal(match)
    if following:
        return url_for("staff.match_review", match_id=following.id, queue=1)
    flash("All proposed matches have been reviewed.", "ok")
    return url_for("staff.matching_page")


def _release_match(match: Match) -> None:
    now = utcnow()
    cohort = db.session.get(Cohort, match.cohort_id) if match.cohort_id else None
    match.status = "released"
    match.released_at = now
    match.confirm_by = now + timedelta(days=cohort.confirm_days if cohort else 7)


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


@bp.post("/matching/override/start")
def start_manual_override():
    mentee_id = request.form.get("mentee_id", type=int)
    if mentee_id not in matching.unmatched_mentee_ids():
        flash("That mentee is no longer eligible for a manual match.", "error")
        return redirect(url_for("staff.matching_page"))
    return redirect(url_for("staff.matching_page", override_mentee=mentee_id))


@bp.post("/matching/override")
def manual_override():
    mentee_id = request.form.get("mentee_id", type=int)
    mentor_id = request.form.get("mentor_id", type=int)
    if mentee_id is None or mentor_id is None:
        abort(400)
    if mentee_id not in matching.unmatched_mentee_ids():
        flash("That mentee is no longer unmatched and cannot be overridden.", "error")
        return redirect(url_for("staff.matching_page"))

    accepted_mentors = matching.accepted_profiles("mentor")
    mentor = db.session.get(User, mentor_id)
    if not mentor or mentor.id not in accepted_mentors:
        flash("Choose an active mentor with an accepted application.", "error")
        return redirect(url_for("staff.matching_page"))
    mentor_load = (db.session.query(Match).filter_by(mentor_id=mentor.id)
                   .filter(Match.status.in_(("proposed", "released", "approved"))).count())
    if mentor_load >= matching.MENTEES_PER_MENTOR:
        existing_request = (db.session.query(MatchOverrideRequest)
                            .filter_by(mentee_id=mentee_id, status="pending").first())
        if existing_request:
            flash("An admin approval ticket is already pending for this mentee.", "error")
            return redirect(url_for("staff.matching_page"))
        override_request = MatchOverrideRequest(
            mentee_id=mentee_id,
            mentor_id=mentor.id,
            requested_by_id=current_user.id,
        )
        db.session.add(override_request)
        record_change(
            "manual_match_override_requested",
            f"Requested backend approval to match {db.session.get(User, mentee_id).name} "
            f"with at-capacity mentor {mentor.name} ({mentor_load}/{matching.MENTEES_PER_MENTOR}).",
            target_user_id=mentee_id,
        )
        db.session.commit()
        flash(f"{mentor.name} is at capacity ({mentor_load}/{matching.MENTEES_PER_MENTOR}). "
              "An override request was sent to the backend admin.", "ok")
        return redirect(url_for("staff.matching_page"))

    mentee = db.session.get(User, mentee_id)
    match = Match(
        mentee_id=mentee.id,
        mentor_id=mentor.id,
        status="released",
        score=0,
        score_breakdown={"manual_override": True},
        rematch_round=matching.rematch_round(mentee.id),
        decided_by_id=current_user.id,
        decided_at=utcnow(),
    )
    _release_match(match)
    db.session.add(match)
    record_change("manual_match_override",
                  f"Manually matched {mentee.name} with {mentor.name}, bypassing matchmaker ranking.",
                  target_user_id=mentee.id)
    db.session.commit()
    notify.notify_match_released(match)
    flash(f"Manual match created: {mentee.name} → {mentor.name}.", "ok")
    return redirect(url_for("staff.matching_page"))


# decision: (status it applies to, status it leads to). The last two undo reject and end.
# Staff approval releases the match to the mentee for confirmation.
DECISIONS = {"approve": ("proposed", "released"), "reject": ("proposed", "rejected"),
             "end": ("approved", "ended"),
             "unreject": ("rejected", "proposed"), "reopen": ("ended", "approved")}
UNDO = {"reject": "unreject", "end": "reopen"}


def _undo_blocker(m: Match, decision: str) -> str | None:
    """Why this undo can't happen right now, if it can't."""
    if decision in ("unreject", "reopen"):
        other = (db.session.query(Match)
                 .filter(Match.mentee_id == m.mentee_id, Match.id != m.id,
                         Match.status.in_(("proposed", "released", "approved"))).first())
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
            return redirect(url_for("staff.match_review", match_id=m.id, action="reject",
                                    **({"queue": 1} if request.form.get("queue") == "1" else {})))
        feedback = MatchFeedback(match_id=m.id, author_id=current_user.id, kind="deny",
                                 reason=reason, comment=comment)
        db.session.add(feedback)
        db.session.flush()
        if not db.session.query(MatchExclusion).filter_by(mentee_id=m.mentee_id, mentor_id=m.mentor_id).first():
            db.session.add(MatchExclusion(mentee_id=m.mentee_id, mentor_id=m.mentor_id,
                                          cohort_id=m.cohort_id, feedback_id=feedback.id))
    m.status, m.decided_by_id, m.decided_at = DECISIONS[decision][1], current_user.id, utcnow()
    if decision == "approve":
        _release_match(m)
    db.session.commit()
    if decision == "approve":
        notify.notify_match_released(m)
    done = {"approve": f"Sent {pair} to the mentee for confirmation.", "end": f"Ended {pair}.",
            "reject": f"Rejected {pair}. They won't be proposed together again.",
            "reopen": f"Reopened {pair}."}[decision]
    queued_review = request.form.get("queue") == "1" and decision in ("approve", "reject")
    if queued_review:
        destination = _queue_destination(m)
    else:
        destination = back
    if decision in UNDO:
        _offer_undo(done, url_for("staff.decide_match", match_id=m.id, decision=UNDO[decision]),
                    next=destination)
    else:
        flash(done, "ok")
    return redirect(destination)


# --- modules -----------------------------------------------------------------------

def _dt(name: str) -> datetime | None:
    value = request.form.get(name)
    return datetime.fromisoformat(value) if value else None


@bp.route("/modules/new", methods=["GET", "POST"])
def new_event():
    if request.method == "POST":
        event = Event(
            title=request.form["title"], description=request.form.get("description", ""),
            starts_at=_dt("starts_at"), location=request.form.get("location", ""),
            checkin_code=secrets.token_hex(3).upper(),
            prework_prompt=request.form.get("prework_prompt", ""), prework_due=_dt("prework_due"),
            postwork_prompt=request.form.get("postwork_prompt", ""), postwork_due=_dt("postwork_due"),
        )
        db.session.add(event)
        record_change("module_created", f"Created module: {event.title}.")
        db.session.commit()
        flash("Module created.", "ok")
        return redirect(url_for("program.modules"))
    return render_template("staff/event_form.html")


# --- reporting ---------------------------------------------------------------------

def report_data() -> dict:
    roles = dict(db.session.query(User.role, func.count(User.id))
                 .filter(User.role.in_(("mentee", "mentor"))).group_by(User.role).all())
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
    return {
        "participants": roles.get("mentor", 0) + roles.get("mentee", 0),
        "mentors": roles.get("mentor", 0),
        "mentees": roles.get("mentee", 0),
        "active_matches": active_matches,
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


@bp.get("/reports/modules/<int:event_id>")
def event_attendance(event_id: int):
    event = db.get_or_404(Event, event_id)
    participants = (db.session.query(User)
                    .filter(User.role.in_(("mentee", "mentor")), User.created_at <= event.starts_at)
                    .order_by(User.name).all())
    participant_ids = [user.id for user in participants]
    attendance_by_user = dict(
        db.session.query(Attendance.user_id, Attendance.checked_in_at)
        .filter(Attendance.event_id == event.id, Attendance.user_id.in_(participant_ids)).all()
    ) if participant_ids else {}
    submission_by_user = {
        (user_id, kind)
        for user_id, kind in db.session.query(Submission.user_id, Submission.kind)
        .filter(Submission.event_id == event.id, Submission.user_id.in_(participant_ids))
    }
    if not participant_ids:
        submission_by_user = set()
    rating = db.session.query(func.avg(Feedback.rating)).filter_by(event_id=event.id).scalar()
    total = len(participants)
    attended_count = len(attendance_by_user)
    return render_template(
        "staff/event_attendance.html",
        event=event,
        attended=[user for user in participants if user.id in attendance_by_user],
        absent=[user for user in participants if user.id not in attendance_by_user],
        attendance_by_user=attendance_by_user,
        submission_by_user=submission_by_user,
        participant_count=total,
        attended_count=attended_count,
        attendance_rate=attended_count / total * 100 if total else None,
        prework_count=sum((user.id, "prework") in submission_by_user for user in participants),
        postwork_count=sum((user.id, "postwork") in submission_by_user for user in participants),
        average_rating=rating,
    )
