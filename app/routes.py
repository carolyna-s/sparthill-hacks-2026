from __future__ import annotations

import calendar
import hmac
from datetime import timedelta

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import program
from .extensions import csrf, db
from .intake import signup_next_step
from .models import Event, Match, Meeting, Submission, utcnow

bp = Blueprint("main", __name__)


@bp.get("/")
def landing():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("landing.html")


@bp.get("/dashboard")
@login_required
def dashboard():
    if current_user.is_staff:
        return redirect(url_for("staff.overview"))
    next_step = signup_next_step(current_user)
    if next_step:
        flash("Finish signing up to open your dashboard.", "error")
        return redirect(next_step)
    matches = (db.session.query(Match)
               .filter(Match.status == "approved",
                       (Match.mentee_id == current_user.id) | (Match.mentor_id == current_user.id))
               .all())
    meetings = program.meetings_for(current_user)
    upcoming = sorted([("meeting", mt.starts_at, mt) for mt in meetings if mt.starts_at >= utcnow() - timedelta(hours=1)]
                      + [("module", e.starts_at, e) for e in program.upcoming_modules()],
                      key=lambda row: row[1])[:5]
    return render_template("dashboard.html", application=current_user.application, matches=matches,
                           upcoming=upcoming, todo=program.todo_for(current_user),
                           cal=_month_calendar(meetings))


def _month_calendar(meetings: list[Meeting]) -> dict:
    """This month as weeks of day numbers (0 = padding), with what falls on each day: module sessions,
    pre-/post-work due dates (mentees only), and the user's meetings. Each item is (kind, label, url)."""
    today = utcnow().date()
    start = today.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1)
    dated: list[tuple] = []
    for e in db.session.query(Event).order_by(Event.starts_at):
        url = url_for("program.module", event_id=e.id)
        dated.append((e.starts_at, "module", e.title, url))
        if current_user.role == "mentee":
            for kind in Submission.KINDS:
                due = getattr(e, f"{kind}_due")
                if getattr(e, f"{kind}_prompt") and due:
                    dated.append((due, "due", f"{kind.replace('work', '-work').capitalize()} due: {e.title}", url))
    for mt in meetings:
        other = mt.match.other(current_user)
        dated.append((mt.starts_at, "meeting", f"Meeting with {other.name} at {mt.starts_at:%I:%M %p}",
                      url_for("program.messages", match_id=mt.match_id)))
    by_day: dict[int, list] = {}
    for when, kind, label, url in sorted(dated, key=lambda row: row[0]):
        if start <= when.date() < end:
            by_day.setdefault(when.day, []).append((kind, label, url))
    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(today.year, today.month)
    return {"title": today.strftime("%B %Y"), "today": today.day, "weeks": weeks, "days": by_day}


@bp.get("/healthz")
def healthz():
    db.session.execute(db.text("SELECT 1"))
    return {"ok": True}


@bp.post("/internal/cron/reminders")
@csrf.exempt
def cron_reminders():
    """Called by EventBridge Scheduler (or any cron) with `X-Cron-Secret`."""
    secret = current_app.config["CRON_SECRET"]
    if not secret or not hmac.compare_digest(request.headers.get("X-Cron-Secret", ""), secret):
        abort(403)
    from .reminders import send_due_reminders

    return {"sent": send_due_reminders()}
