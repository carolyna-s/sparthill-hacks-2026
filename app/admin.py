"""Admin (backend role) pages: account metrics, the user audit with activate/deactivate,
creating staff accounts, and account-level reports. Admins can open every staff page too."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func

from .auth import change_password, role_required
from .extensions import db
from .models import (Application, Attendance, Feedback, Match, MatchFeedback, Meeting, Message, ROLES,
                     Submission, User, utcnow)
from .staff import dashboard_for, report_data

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
    return render_template(
        "admin/dashboard.html", by_role=accounts_by_role(), staff=staff,
        totals={"accounts": users.count(),
                "active_week": users.filter(User.last_seen_at >= week).count(),
                "new_week": users.filter(User.created_at >= week).count(),
                "inactive": users.filter(User.is_active.is_(False)).count()},
        recent=users.filter(User.last_seen_at.isnot(None)).order_by(User.last_seen_at.desc()).limit(8).all(),
        signups=users.filter(User.created_at >= week).order_by(User.created_at.desc()).all())


# --- user audit -----------------------------------------------------------------------

@bp.get("/users")
def users():
    role = request.args.get("role") if request.args.get("role") in ROLES else None
    status = request.args.get("status") if request.args.get("status") in ("active", "inactive") else None
    q = request.args.get("q", "").strip()
    query = db.session.query(User)
    if role:
        query = query.filter(User.role == role)
    if status:
        query = query.filter(User.is_active.is_(status == "active"))
    if q:
        query = query.filter(User.name.ilike(f"%{q}%") | User.email.ilike(f"%{q}%"))
    rows = [dashboard_for(u) if u.role in ("mentee", "mentor") else {"user": u}
            for u in query.order_by(User.role, User.name)]
    return render_template("admin/users.html", rows=rows, role=role, status=status, q=q)


def _staff_activity(user: User) -> dict:
    """What a staff or admin account has done: reviews and match decisions."""
    reviews = (db.session.query(Application).filter_by(reviewed_by_id=user.id)
               .order_by(Application.reviewed_at.desc()))
    decisions = dict(db.session.query(Match.status, func.count(Match.id)).filter_by(decided_by_id=user.id)
                     .group_by(Match.status).all())
    return {"reviews": reviews.count(), "recent_reviews": reviews.limit(10).all(), "decisions": decisions,
            "denials": db.session.query(MatchFeedback).filter_by(author_id=user.id, kind="deny").count()}


def _participant_activity(user: User) -> dict:
    match_ids = [m.id for m in db.session.query(Match.id)
                 .filter((Match.mentee_id == user.id) | (Match.mentor_id == user.id))]
    return {"attended": db.session.query(Attendance).filter_by(user_id=user.id).count(),
            "submissions": db.session.query(Submission).filter_by(user_id=user.id).count(),
            "messages": db.session.query(Message).filter_by(sender_id=user.id).count(),
            "meetings": db.session.query(Meeting).filter(Meeting.match_id.in_(match_ids)).count(),
            "ratings": db.session.query(Feedback).filter_by(user_id=user.id).count()}


@bp.get("/users/<int:user_id>")
def user(user_id: int):
    u = db.get_or_404(User, user_id)
    participant = u.role in ("mentee", "mentor")
    return render_template("admin/user.html", u=u,
                           d=dashboard_for(u) if participant else None,
                           activity=_participant_activity(u) if participant else _staff_activity(u))


@bp.post("/users/<int:user_id>/active")
def set_active(user_id: int):
    u = db.get_or_404(User, user_id)
    active = request.form.get("active") == "1"
    if u.id == current_user.id and not active:
        flash("You can't deactivate your own account.", "error")
    else:
        u.is_active = active
        db.session.commit()
        flash(f"{u.name} is {'active again' if active else 'deactivated and signed out'}.", "ok")
    target = request.form.get("next", "")
    return redirect(target if target.startswith("/") and not target.startswith("//")
                    else url_for("admin.user", user_id=u.id))


@bp.route("/users/new", methods=["GET", "POST"])
def new_user():
    """Create a staff (or admin) account. Mentors and mentees sign themselves up."""
    form = request.form
    if request.method == "POST":
        email, name, role = form.get("email", "").strip().lower(), form.get("name", "").strip(), form.get("role")
        if role not in ("staff", "backend"):
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
            db.session.commit()
            flash(f"Created {ROLE_LABELS[role].lower()} account for {name}. Share the temporary password "
                  "with them; they can change it after logging in.", "ok")
            return redirect(url_for("admin.user", user_id=u.id))
    return render_template("admin/new_user.html", form=form)


# --- reports ------------------------------------------------------------------------

@bp.get("/reports")
def reports():
    funnel = {(role, status): n for role, status, n in
              db.session.query(User.role, Application.status, func.count(Application.id))
              .join(Application, Application.user_id == User.id).group_by(User.role, Application.status)}
    staff = db.session.query(User).filter(User.role.in_(("staff", "backend"))).order_by(User.name).all()
    reviews = dict(db.session.query(Application.reviewed_by_id, func.count(Application.id))
                   .filter(Application.reviewed_by_id.isnot(None)).group_by(Application.reviewed_by_id).all())
    decisions = {(uid, s): n for uid, s, n in
                 db.session.query(Match.decided_by_id, Match.status, func.count(Match.id))
                 .filter(Match.decided_by_id.isnot(None)).group_by(Match.decided_by_id, Match.status)}
    return render_template("admin/reports.html", by_role=accounts_by_role(), funnel=funnel,
                           statuses=Application.STATUSES, staff=staff, reviews=reviews, decisions=decisions,
                           report=report_data())


# --- own account --------------------------------------------------------------------

@bp.route("/profile", methods=["GET", "POST"])
def profile():
    if request.method == "POST":
        error = change_password(current_user, request.form)
        flash(error or "Password changed successfully.", "error" if error else "ok")
        if not error:
            return redirect(url_for("admin.profile"))
    return render_template("admin/profile.html")
