"""Every page renders for every role (catches template errors)."""

import pytest

from app import matching
from app.extensions import db

from .conftest import login

PARTICIPANT_PAGES = ["/dashboard", "/profile/1", "/profile/2", "/profile/3", "/profile/4", "/apply", "/agreements",
                     "/account", "/dashboard/application", "/modules", "/modules/1", "/messages/"]


@pytest.fixture
def approved(app):
    matches = matching.propose_all()
    for m in matches:
        m.status = "approved"
    db.session.commit()
    return matches


def test_public_pages(client):
    for path in ["/", "/login", "/register?role=mentor"]:
        assert client.get(path).status_code == 200, path


@pytest.mark.parametrize("email", ["jordan.kim@example.org", "priya.raman@example.org",
                                   "morgan.diaz@example.org"])  # matched mentee, mentor, pending mentee
def test_participant_pages(client, approved, email):
    login(client, email)
    mine = [m for m in approved if email in (m.mentee.email, m.mentor.email)]
    for path in PARTICIPANT_PAGES + [f"/messages/{m.id}" for m in mine]:
        assert client.get(path, follow_redirects=True).status_code == 200, path  # /messages/ opens a lone match


def test_staff_detail_pages(client, approved):
    login(client, "staff.admin@example.org")
    for path in ["/modules", "/modules/1", f"/messages/{approved[0].id}", "/staff/applications/1",
                 "/staff/matching"]:
        assert client.get(path).status_code == 200, path
