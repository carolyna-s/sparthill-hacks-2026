"""Helpers for recording administrative and staff changes outside matching workflows."""

from flask_login import current_user

from .extensions import db
from .models import AuditLog


def record_change(action: str, description: str, target_user_id: int | None = None) -> None:
    if not current_user.is_authenticated or current_user.role not in ("staff", "backend"):
        raise RuntimeError("Audit changes require an authenticated staff or admin actor.")
    db.session.add(AuditLog(
        actor_id=current_user.id,
        actor_role=current_user.role,
        target_user_id=target_user_id,
        action=action,
        description=description,
    ))
