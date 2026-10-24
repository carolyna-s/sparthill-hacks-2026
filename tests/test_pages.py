"""Every page renders for every role (catches template errors)."""

import pytest

from app import matching
from app.extensions import db
from app.models import User

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


@pytest.mark.parametrize(("status", "label"), [("accepted", "Approved"), ("rejected", "Rejected")])
def test_dashboard_application_status_labels(client, status, label):
    application = db.session.query(User).filter_by(email="morgan.diaz@example.org").one().application
    application.status = status
    db.session.commit()

    login(client, "morgan.diaz@example.org")
    for path in ("/dashboard", "/dashboard/application", "/apply"):
        response = client.get(path, follow_redirects=True)
        assert response.status_code == 200, path
        assert f">{label}</span>".encode() in response.data, path


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
        assert client.get(path).status_code == 200


@pytest.mark.parametrize(
    ("email", "path", "label"),
    [
        ("jordan.kim@example.org", "/dashboard", "Dashboard"),
        ("jordan.kim@example.org", "/modules", "Modules"),
        ("staff.admin@example.org", "/staff/", "Dashboard"),
        ("staff.admin@example.org", "/staff/applications", "Applicants"),
        ("staff.admin@example.org", "/staff/matching", "Matching"),
        ("staff.admin@example.org", "/modules", "Modules"),
        ("staff.admin@example.org", "/staff/reports", "Reports"),
    ],
)
def test_navigation_bolds_current_section(client, email, path, label):
    import re

    login(client, email)
    response = client.get(path, follow_redirects=True)

    assert response.status_code == 200
    active_links = re.findall(
        rb'<a[^>]*aria-current="page"[^>]*>(.*?)</a>', response.data, re.DOTALL
    )
    assert [link.decode().strip() for link in active_links] == [label], path


def test_admin_logistics_page_is_admin_only(client):
    login(client, "staff.admin@example.org")
    assert client.get("/admin/matching-logistics").status_code == 403
    login(client, "backend.admin@example.org")
    assert client.get("/admin/matching-logistics").status_code == 200
