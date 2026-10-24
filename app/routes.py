from __future__ import annotations

import calendar
import hmac
from datetime import timedelta

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import program
from .extensions import csrf, db
from .intake import signup_next_step
from .models import Event, Match, utcnow

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
    return render_template("dashboard.html", application=current_user.application, matches=matches,
                           upcoming=program.upcoming_events(), todo=program.todo_for(current_user),
                           cal=_month_calendar())


def _month_calendar() -> dict:
    """This month as weeks of day numbers (0 = padding), with the events falling on each day."""
    today = utcnow().date()
    start = today.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1)
    by_day: dict[int, list] = {}
    for e in db.session.query(Event).filter(Event.starts_at >= start, Event.starts_at < end).order_by(Event.starts_at):
        by_day.setdefault(e.starts_at.day, []).append(e)
    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(today.year, today.month)
    return {"title": today.strftime("%B %Y"), "today": today.day, "weeks": weeks, "events": by_day}


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
