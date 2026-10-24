"""Email + password accounts with three roles: mentee, mentor, staff.

Staff accounts can't self-register; create them with `flask seed` or promote a user in the
database. Swap in Amazon Cognito later by replacing this blueprint; the rest of the app
only relies on Flask-Login's `current_user` and `role_required`.
"""

from __future__ import annotations

from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from .extensions import db
from .models import Profile, User

bp = Blueprint("auth", __name__)


def role_required(*roles: str):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapper

    return decorator


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        role = request.form.get("role")
        if role not in ("mentee", "mentor"):
            abort(400)
        if len(request.form["password"]) < 8:
            flash("Password must be at least 8 characters.", "error")
        elif not request.form.get("school", "").strip():
            flash("Enter your school.", "error")
        elif db.session.query(User).filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
        else:
            user = User(email=email, name=request.form["name"].strip(), role=role)
            user.set_password(request.form["password"])
            user.profile = Profile(school=request.form.get("school", "").strip())
            db.session.add(user)
            db.session.commit()
            login_user(user)
            return redirect(url_for("intake.profile"))
    return render_template("auth/register.html", role=request.args.get("role", "mentee"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = db.session.query(User).filter_by(email=request.form["email"].strip().lower()).first()
        if user and user.check_password(request.form["password"]):
            login_user(user, remember=True)
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("main.dashboard"))
        flash("Wrong email or password.", "error")
    return render_template("auth/login.html")


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.landing"))
