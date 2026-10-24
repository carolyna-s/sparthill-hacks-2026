"""Admin (backend role) pages: account metrics, user controls, and audit logs."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, or_

from . import matching
from .audit import record_change
from .auth import change_password, role_required
from .extensions import db
from .models import (AgreementSignature, Answer, Application, Attendance, AuditLog, ConfigSuggestion, Event,
                     Feedback, Match, MatchExclusion, MatchFeedback, MatchOverrideRequest, MatchingConfig,
                     Meeting, Message, ReminderLog, ROLES, Submission, User, utcnow)
from .staff import DENY_REASONS

bp = Blueprint("admin", __name__, url_prefix="/admin")

ROLE_LABELS = {"mentee": "Mentee", "mentor": "Mentor", "staff": "Staff", "backend": "Admin"}


@bp.before_request
@role_required("backend")
def _admin_only():
    return None


@bp.context_processor
def _labels():
    return {"role_labels": ROLE_LABELS}


def _since(days: int):
    return utcnow() - timedelta(days=days)


def accounts_by_role() -> list[dict]:
    """Per role: total accounts, deactivated, logged in within 7 / 30 days, never logged in."""
    week, month = _since(7), _since(30)
    rows = {r: dict(role=r, total=0, inactive=0, week=0, month=0, never=0) for r in ROLES}
    for role, active, last_login in db.session.query(User.role, User.is_active, User.last_login_at):
        row = rows[role]
        row["total"] += 1
        row["inactive"] += not active
        row["never"] += last_login is None
        row["week"] += bool(last_login and last_login >= week)
        row["month"] += bool(last_login and last_login >= month)
    return list(rows.values())


# --- dashboard ----------------------------------------------------------------------

@bp.get("/")
def dashboard():
    week = _since(7)
    users = db.session.query(User)
    staff = users.filter(User.role.in_(("staff", "backend"))).order_by(User.is_active.desc(), User.name).all()
    override_requests = []
    for ticket in (db.session.query(MatchOverrideRequest).filter_by(status="pending")
                   .order_by(MatchOverrideRequest.created_at).all()):
        load = (db.session.query(Match).filter_by(mentor_id=ticket.mentor_id)
                .filter(Match.status.in_(("proposed", "released", "approved"))).count())
        override_requests.append({"ticket": ticket, "load": load})
    return render_template(
        "admin/dashboard.html", by_role=accounts_by_role(), staff=staff,
        override_requests=override_requests,
        totals={"accounts": users.count(),
                "active_week": users.filter(User.last_seen_at >= week).count(),
                "new_week": users.filter(User.created_at >= week).count(),
                "inactive": users.filter(User.is_active.is_(False)).count()},
        recent=users.filter(User.last_seen_at.isnot(None)).order_by(User.last_seen_at.desc()).limit(8).all(),
        signups=users.filter(User.created_at >= week).order_by(User.created_at.desc()).all())


@bp.post("/matching-override-requests/<int:request_id>/<decision>")
def decide_matching_override(request_id: int, decision: str):
    if decision not in ("approve", "deny"):
        abort(400)
    override_request = db.get_or_404(MatchOverrideRequest, request_id)
    if override_request.status != "pending":
        flash("This override request has already been decided.", "error")
        return redirect(url_for("admin.dashboard"))

    mentee, mentor = override_request.mentee, override_request.mentor
    if decision == "approve":
        accepted_mentees = matching.accepted_profiles("mentee")
        accepted_mentors = matching.accepted_profiles("mentor")
        already_matched = db.session.query(Match.id).filter(
            Match.mentee_id == override_request.mentee_id,
            Match.status.in_(("proposed", "released", "approved")),
        ).first()
        if (mentee.id not in accepted_mentees or mentor.id not in accepted_mentors or already_matched):
            override_request.status = "denied"
            override_request.decided_by_id = current_user.id
            override_request.decided_at = utcnow()
            record_change(
                "manual_match_override_denied",
                f"Denied override request #{override_request.id}; mentee or mentor is no longer eligible.",
                target_user_id=mentee.id,
            )
            db.session.commit()
            flash("The request was denied because the mentee or mentor is no longer eligible.", "error")
            return redirect(url_for("admin.dashboard"))
        now = utcnow()
        match = Match(
            mentee_id=mentee.id,
            mentor_id=mentor.id,
            status="released",
            score=0,
            score_breakdown={"manual_override": True, "admin_approved_over_capacity": True},
            rematch_round=1 + db.session.query(Match).filter_by(
                mentee_id=mentee.id, status="rejected").count(),
            decided_by_id=current_user.id,
            decided_at=now,
            released_at=now,
            confirm_by=now + timedelta(days=7),
        )
        db.session.add(match)
        db.session.flush()
        override_request.status = "approved"
        override_request.decided_by_id = current_user.id
        override_request.decided_at = now
        override_request.match_id = match.id
        record_change(
            "manual_match_override_approved",
            f"Approved capacity override: {mentee.name} → {mentor.name}; released to mentee for confirmation.",
            target_user_id=mentee.id,
        )
        flash(f"Override approved. {mentee.name} has been sent the match for confirmation.", "ok")
    else:
        override_request.status = "denied"
        override_request.decided_by_id = current_user.id
        override_request.decided_at = utcnow()
        record_change(
            "manual_match_override_denied",
            f"Denied capacity override: {mentee.name} → {mentor.name}.",
            target_user_id=mentee.id,
        )
        flash("Override request denied; the mentee is back in the matching pool.", "ok")
    db.session.commit()
    return redirect(url_for("admin.dashboard"))


@bp.get("/matching-logistics")
def matching_logistics():
    staff = db.session.query(User).filter_by(role="staff").order_by(User.name).all()
    rows = []
    for user in staff:
        decisions = dict(
            db.session.query(Match.status, func.count(Match.id))
            .filter(Match.decided_by_id == user.id, Match.status.in_(("released", "approved", "rejected")))
            .group_by(Match.status).all()
        )
        denials = (
            db.session.query(MatchFeedback)
            .filter_by(author_id=user.id, kind="deny")
            .join(Match, Match.id == MatchFeedback.match_id)
            .order_by(MatchFeedback.created_at.desc())
            .all()
        )
        rows.append({
            "user": user,
            "accepted": decisions.get("released", 0) + decisions.get("approved", 0),
            "denied": decisions.get("rejected", 0),
            "denials": [{
                "mentee": feedback.match.mentee.name,
                "mentor": feedback.match.mentor.name,
                "reason": DENY_REASONS.get(feedback.reason, feedback.reason or "No reason recorded"),
                "comment": feedback.comment,
                "created_at": feedback.created_at,
            } for feedback in denials],
        })
    return render_template("admin/matching_logistics.html", rows=rows)


# --- user audit -----------------------------------------------------------------------

def _attendance_rates(users: list[User]) -> dict[int, str]:
    participants = [user for user in users if user.role in ("mentee", "mentor")]
    if not participants:
        return {}
    now = utcnow()
    events = db.session.query(Event).filter(Event.starts_at <= now).all()
    attended = {
        (user_id, event_id)
        for user_id, event_id in db.session.query(Attendance.user_id, Attendance.event_id)
        .filter(Attendance.user_id.in_([user.id for user in participants]))
    }
    rates = {}
    for user in participants:
        eligible = [event for event in events if event.starts_at >= user.created_at]
        if not eligible:
            rates[user.id] = "N/A"
            continue
        count = sum((user.id, event.id) in attended for event in eligible)
        rates[user.id] = f"{count / len(eligible) * 100:.0f}%"
    return rates


@bp.get("/users")
def users():
    visible_roles = ("mentee", "mentor", "staff")
    role = request.args.get("role") if request.args.get("role") in visible_roles else None
    status = request.args.get("status") if request.args.get("status") in ("active", "inactive") else None
    q = request.args.get("q", "").strip()
    query = db.session.query(User).filter(User.role.in_(visible_roles))
    if role:
        query = query.filter(User.role == role)
    if status:
        query = query.filter(User.is_active.is_(status == "active"))
    users = query.order_by(User.role, User.name).all()
    matched_to = {user.id: [] for user in users if user.role in ("mentee", "mentor")}
    if matched_to:
        matches = (db.session.query(Match)
                   .filter(Match.status.in_(("released", "approved")),
                           (Match.mentee_id.in_(matched_to)) | (Match.mentor_id.in_(matched_to)))
                   .all())
        for match in matches:
            if match.mentee_id in matched_to:
                matched_to[match.mentee_id].append(match.mentor.name)
            if match.mentor_id in matched_to:
                matched_to[match.mentor_id].append(match.mentee.name)
    attendance_rates = _attendance_rates(users)
    rows = [{"user": user, "matched_to": matched_to.get(user.id, []),
             "attendance_rate": attendance_rates.get(user.id, "—")} for user in users]
    return render_template("admin/users.html", rows=rows, role=role, status=status, q=q)


@bp.get("/users/<int:user_id>")
def user(user_id: int):
    u = db.get_or_404(User, user_id)
    current_match = (db.session.query(Match)
                     .filter(Match.status.in_(("released", "approved")),
                             (Match.mentee_id == u.id) | (Match.mentor_id == u.id))
                     .first())
    matched_to = current_match.other(u) if current_match else None
    candidates = []
    if u.role in ("mentee", "mentor"):
        other_role = "mentor" if u.role == "mentee" else "mentee"
        candidates = (db.session.query(User).filter(User.role == other_role, User.id != u.id)
                      .order_by(User.name).all())
    return render_template("admin/user.html", u=u, matched_to=matched_to, candidates=candidates)


@bp.post("/users/<int:user_id>/update")
def update_user(user_id: int):
    u = db.get_or_404(User, user_id)
    if u.id == current_user.id and request.form.get("status") == "inactive":
        flash("You can't deactivate your own account.", "error")
        return redirect(url_for("admin.user", user_id=u.id))

    old_role, old_active = u.role, u.is_active
    old_match = (db.session.query(Match)
                 .filter(Match.status.in_(("released", "approved")),
                         (Match.mentee_id == u.id) | (Match.mentor_id == u.id))
                 .first())
    old_match_id = old_match.other(u).id if old_match else None
    changed = []

    if u.role in ("mentee", "mentor"):
        new_role = request.form.get("role")
        if new_role not in ("mentee", "mentor"):
            abort(400)
        if new_role != old_role:
            has_match_history = db.session.query(Match.id).filter(
                (Match.mentee_id == u.id) | (Match.mentor_id == u.id)
            ).first()
            if has_match_history:
                flash("This role can't be changed because the account has matching history.", "error")
                return redirect(url_for("admin.user", user_id=u.id))
            u.role = new_role
            changed.append(f"role {ROLE_LABELS[old_role]} → {ROLE_LABELS[new_role]}")
        selected_match = request.form.get("matched_to", "").strip()
        target = db.session.get(User, int(selected_match)) if selected_match.isdigit() else None
        if selected_match and not target:
            abort(400)
        if target and (target.id == u.id or target.role != ("mentor" if u.role == "mentee" else "mentee")
                       or (not target.is_active and target.id != old_match_id)):
            flash("Choose an active participant with the opposite role, or choose Unmatch.", "error")
            return redirect(url_for("admin.user", user_id=u.id))
        target_id = target.id if target else None
        if target_id != old_match_id:
            affected_ids = [u.id] + ([target_id] if target_id else [])
            active_matches = db.session.query(Match).filter(
                Match.status.in_(("proposed", "released", "approved")),
                (Match.mentee_id.in_(affected_ids)) | (Match.mentor_id.in_(affected_ids)),
            ).all()
            for match in active_matches:
                if match.status == "proposed":
                    db.session.delete(match)
                else:
                    match.status = "ended"
                    match.decided_by_id = current_user.id
                    match.decided_at = utcnow()
            if target:
                db.session.add(Match(
                    mentee_id=u.id if u.role == "mentee" else target.id,
                    mentor_id=u.id if u.role == "mentor" else target.id,
                    status="released",
                    score=0,
                    score_breakdown={"manual_override": True},
                    decided_by_id=current_user.id,
                    decided_at=utcnow(),
                    released_at=utcnow(),
                    confirm_by=utcnow() + timedelta(days=7),
                ))
            changed.append("manual match assignment override changed")
    elif "role" in request.form or "matched_to" in request.form:
        abort(400)

    status = request.form.get("status")
    if status not in ("active", "inactive"):
        abort(400)
    u.is_active = status == "active"
    if u.is_active != old_active:
        changed.append(f"account status {'active' if old_active else 'deactivated'} → {status}")

    if changed:
        record_change("account_updated", f"{u.name}: " + "; ".join(changed), target_user_id=u.id)
    db.session.commit()
    flash("Account changes saved.", "ok")
    return redirect(url_for("admin.user", user_id=u.id))


@bp.post("/users/<int:user_id>/active")
def set_active(user_id: int):
    u = db.get_or_404(User, user_id)
    active = request.form.get("active") == "1"
    if u.id == current_user.id and not active:
        flash("You can't deactivate your own account.", "error")
    else:
        old_active = u.is_active
        u.is_active = active
        if old_active != active:
            record_change("account_status", f"{u.name}: account {'enabled' if active else 'disabled'}.",
                          target_user_id=u.id)
        db.session.commit()
        flash(f"{u.name} is {'active again' if active else 'deactivated and signed out'}.", "ok")
    target = request.form.get("next", "")
    return redirect(target if target.startswith("/") and not target.startswith("//")
                    else url_for("admin.user", user_id=u.id))


@bp.post("/users/<int:user_id>/reset-password")
def require_password_reset(user_id: int):
    u = db.get_or_404(User, user_id)
    if not u.must_reset_password:
        u.must_reset_password = True
        record_change("password_reset_required",
                      f"Required a password change for {u.name}; next login must use the current password "
                      "and choose a new password.",
                      target_user_id=u.id)
        db.session.commit()
    flash(f"{u.name} must choose a new password at their next login.", "ok")
    return redirect(url_for("admin.user", user_id=u.id))


@bp.post("/users/<int:user_id>/delete")
def delete_user(user_id: int):
    u = db.get_or_404(User, user_id)
    if u.id == current_user.id:
        flash("You can't delete your own account.", "error")
        return redirect(url_for("admin.user", user_id=u.id))
    if (u.role == "backend" and u.is_active
            and db.session.query(User).filter_by(role="backend", is_active=True).count() <= 1):
        flash("The last active admin account can't be deleted.", "error")
        return redirect(url_for("admin.user", user_id=u.id))

    user_id = u.id
    db.session.add(AuditLog(
        actor_id=current_user.id,
        actor_name=current_user.name,
        actor_role=current_user.role,
        action="account_deleted",
        description=f"Deleted account #{user_id}.",
    ))

    match_ids = [match_id for (match_id,) in db.session.query(Match.id).filter(
        or_(Match.mentee_id == user_id, Match.mentor_id == user_id)
    )]
    feedback_query = db.session.query(MatchFeedback.id).filter(
        or_(MatchFeedback.author_id == user_id,
            MatchFeedback.match_id.in_(match_ids) if match_ids else False)
    )
    feedback_ids = [feedback_id for (feedback_id,) in feedback_query]
    db.session.query(MatchExclusion).filter(or_(
        MatchExclusion.mentee_id == user_id,
        MatchExclusion.mentor_id == user_id,
        MatchExclusion.feedback_id.in_(feedback_ids) if feedback_ids else False,
    )).delete(synchronize_session=False)
    db.session.query(MatchFeedback).filter(
        or_(MatchFeedback.author_id == user_id,
            MatchFeedback.match_id.in_(match_ids) if match_ids else False)
    ).delete(synchronize_session=False)
    db.session.query(Message).filter(or_(
        Message.sender_id == user_id,
        Message.match_id.in_(match_ids) if match_ids else False,
    )).delete(synchronize_session=False)
    db.session.query(Meeting).filter(or_(
        Meeting.created_by_id == user_id,
        Meeting.match_id.in_(match_ids) if match_ids else False,
    )).delete(synchronize_session=False)
    db.session.query(Feedback).filter(or_(
        Feedback.user_id == user_id,
        Feedback.match_id.in_(match_ids) if match_ids else False,
    )).delete(synchronize_session=False)
    if match_ids:
        db.session.query(MatchOverrideRequest).filter(or_(
            MatchOverrideRequest.mentee_id == user_id,
            MatchOverrideRequest.mentor_id == user_id,
            MatchOverrideRequest.requested_by_id == user_id,
            MatchOverrideRequest.decided_by_id == user_id,
            MatchOverrideRequest.match_id.in_(match_ids),
        )).delete(synchronize_session=False)
        db.session.query(Match).filter(Match.id.in_(match_ids)).delete(synchronize_session=False)
    else:
        db.session.query(MatchOverrideRequest).filter(or_(
            MatchOverrideRequest.mentee_id == user_id,
            MatchOverrideRequest.mentor_id == user_id,
            MatchOverrideRequest.requested_by_id == user_id,
            MatchOverrideRequest.decided_by_id == user_id,
        )).delete(synchronize_session=False)

    for model in (AgreementSignature, Answer, Attendance, ReminderLog, Submission):
        db.session.query(model).filter_by(user_id=user_id).delete(synchronize_session=False)
    db.session.query(Application).filter_by(reviewed_by_id=user_id).update(
        {"reviewed_by_id": None}, synchronize_session=False)
    db.session.query(Match).filter_by(decided_by_id=user_id).update(
        {"decided_by_id": None}, synchronize_session=False)
    db.session.query(MatchingConfig).filter_by(created_by_id=user_id).update(
        {"created_by_id": None}, synchronize_session=False)
    db.session.query(ConfigSuggestion).filter_by(decided_by_id=user_id).update(
        {"decided_by_id": None}, synchronize_session=False)

    for log in db.session.query(AuditLog).all():
        description = log.description
        if u.name:
            description = description.replace(u.name, "[deleted account]")
        if u.email:
            description = description.replace(u.email, "[deleted account]")
        log.description = description
    db.session.query(AuditLog).filter_by(target_user_id=user_id).update(
        {"target_user_id": None}, synchronize_session=False)
    db.session.query(AuditLog).filter_by(actor_id=user_id).update(
        {"actor_id": None, "actor_name": "Deleted account"}, synchronize_session=False)

    db.session.delete(u)
    db.session.commit()
    flash("Account and associated user data were deleted.", "ok")
    return redirect(url_for("admin.users"))


@bp.route("/users/new", methods=["GET", "POST"])
def new_user():
    """Create staff accounts. Backend admin accounts are created outside the interface."""
    form = request.form
    if request.method == "POST":
        email, name, role = form.get("email", "").strip().lower(), form.get("name", "").strip(), form.get("role")
        if role != "staff":
            abort(400)
        if not name or "@" not in email:
            flash("Enter a name and an email address.", "error")
        elif len(form.get("password", "")) < 8:
            flash("The temporary password must be at least 8 characters.", "error")
        elif db.session.query(User).filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
        else:
            u = User(email=email, name=name, role=role)
            u.set_password(form["password"])
            db.session.add(u)
            db.session.flush()
            record_change("staff_account_created", f"Created staff account {name} ({email}).",
                          target_user_id=u.id)
            db.session.commit()
            flash(f"Created {ROLE_LABELS[role].lower()} account for {name}. Share the temporary password "
                  "with them; they can change it after logging in.", "ok")
            return redirect(url_for("admin.user", user_id=u.id))
    return render_template("admin/new_user.html", form=form)


# --- audit log ----------------------------------------------------------------------

@bp.get("/audit-logs")
def audit_logs():
    rows = (db.session.query(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(500).all())
    return render_template("admin/audit_logs.html", rows=rows)


# --- own account --------------------------------------------------------------------

@bp.route("/profile", methods=["GET", "POST"])
def profile():
    if request.method == "POST":
        error = change_password(current_user, request.form)
        flash(error or "Password changed successfully.", "error" if error else "ok")
        if not error:
            record_change("password_changed", f"{current_user.name} changed their password.",
                          target_user_id=current_user.id)
            db.session.commit()
            return redirect(url_for("admin.profile"))
    return render_template("admin/profile.html")
