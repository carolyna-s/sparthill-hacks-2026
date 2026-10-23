from __future__ import annotations

import hmac

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import program
from .extensions import csrf, db
from .models import Application, Match

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
    app_row = db.session.query(Application).filter_by(user_id=current_user.id).first()
    unsigned = program.unsigned_agreements(current_user)
    matches = (db.session.query(Match)
               .filter(Match.status == "approved",
                       (Match.mentee_id == current_user.id) | (Match.mentor_id == current_user.id))
               .all())
    return render_template("dashboard.html", application=app_row, unsigned=unsigned, matches=matches,
                           upcoming=program.upcoming_events(), todo=program.todo_for(current_user))


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
