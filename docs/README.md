# Mentorship Platform

A web app for running a mentorship program: mentors and mentees apply and sign agreements,
a weighted matching engine ranks mentors for each mentee, matched pairs work through sessions
(prework, postwork, check-ins, reminders, messaging), and staff review applicants, approve
matches, and track participation and satisfaction.

One Flask service serves the whole app. Data lives in **Supabase Postgres** (SQLite works for
offline local dev). The target host is **AWS**. Roadmap and design: [docs/PLAN.md](PLAN.md).

## Prerequisites

- Python 3.12 (`python3.12 --version`)
- Git
- Optional: access to the `sparthill-hackathon` Supabase project (ask a teammate for the
  database password)
- Optional: Docker, only for running the production container locally

## Run it locally

### 1. Install

```bash
git clone <repo-url> && cd sparthill-hacks-2026
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env
```

### 2. Pick a database

**Option A: SQLite (no setup, offline).** Leave `DATABASE_URL` blank in `.env`. The app
creates `instance/mentorship.db`, which is good for quick UI work and tests.

**Option B: Supabase (shared team database).**

1. In the Supabase dashboard, open **sparthill-hackathon → Connect**.
2. Copy the **Session pooler** connection string (port `5432`) and fill in the password.
   Use the session pooler, not the direct connection (IPv6-only) or the transaction pooler
   on port 6543 (it breaks prepared statements).
3. Paste it into `.env`:
   ```
   DATABASE_URL=postgresql://postgres.<project-ref>:<password>@aws-0-us-east-1.pooler.supabase.com:5432/postgres
   ```

Everyone using Option B shares the same data, so coordinate before running `flask seed` or
any migration there.

### 3. Create tables and demo data

```bash
export FLASK_APP=wsgi              # Windows PowerShell: $env:FLASK_APP="wsgi"
flask db upgrade                   # creates/updates tables in whichever DB .env points at
flask seed                         # demo cohort, agreement, events, staff, mentors, mentees
```

`flask seed` does nothing if the database already has data.

### 4. Start the server

```bash
python wsgi.py                     # http://localhost:8000, auto-reloads on code changes
```

### 5. Log in

All demo accounts use the password `password123`.

| Role | Email |
| --- | --- |
| Staff | `staff.admin@example.org` |
| Mentor | `priya.raman@example.org`, `marcus.lee@example.org`, `elena.ortiz@example.org`, `sam.okafor@example.org` |
| Mentee | `jordan.kim@example.org`, `avery.patel@example.org`, `riley.chen@example.org`, `taylor.brooks@example.org`, `morgan.diaz@example.org` (pending review) |

Quick tour:
1. As **staff**: go to **Applicants** and accept Morgan, then **Matching** → *Auto-propose* → approve.
2. As **jordan.kim**: open your match and send a message, open the Kickoff event, submit
   prework, and check in with code `KICK01`.
3. As **staff**: open **Reports** to see the attendance, submission, and rating counts.

## Everyday commands

| Task | Command |
| --- | --- |
| Run tests | `pytest` (always uses a throwaway SQLite DB, never `.env`'s) |
| Send due reminders | `flask send-reminders` (prints emails unless `EMAIL_BACKEND=ses`) |
| Change the schema | edit `app/models.py`, then `flask db migrate -m "what changed"` and `flask db upgrade`, then commit `migrations/versions/*` |
| Run like production | `gunicorn -c gunicorn.conf.py wsgi:app` |
| Production container | `docker build -t mentorship . && docker run -p 8000:8000 --env-file .env mentorship` |

## Project layout

Full guide, including where to put new code: [docs/STRUCTURE.md](STRUCTURE.md).

```
app/
  __init__.py     app factory + CLI commands (seed, send-reminders)
  config.py       settings from .env
  models.py       all tables (docs/SCHEMA.md)
  taxonomy.py     dropdown/tag vocabularies used by profiles and matching
  auth.py         register / login / logout, role_required
  intake.py       profiles, applications, digital agreements
  matching.py     scoring, ranking, capacity-aware assignment
  program.py      events, prework/postwork, check-ins, messaging, feedback
  reminders.py    idempotent reminder sweep
  staff.py        applicant review, match approval, events, reports
  routes.py       landing, dashboard, /healthz, cron endpoint
  storage.py      file uploads (local disk or S3)
  notify.py       email (console or SES)
  seed.py         demo data
  templates/      Jinja + Tailwind via CDN (no frontend build)
migrations/       Alembic migrations
docs/             all Markdown: README, PLAN, SCHEMA, GAPS, STRUCTURE
tests/
```

## Configuration

Everything is set in `.env` (template in `.env.example`, never commit `.env`):

| Variable | Blank / default | Set it to |
| --- | --- | --- |
| `DATABASE_URL` | local SQLite | Supabase session-pooler URI |
| `FLASK_SECRET_KEY` | dev-only key | a long random string in any shared or deployed environment |
| `S3_BUCKET` | uploads saved to `./data/uploads` | a bucket name (see PLAN.md for Supabase Storage) |
| `EMAIL_BACKEND` | `console` | `ses` |
| `CRON_SECRET` | cron endpoint disabled | shared secret for `POST /internal/cron/reminders` |
| `ANTHROPIC_API_KEY` | planned chatbot and resume parsing off | API key |

## Troubleshooting

- **`ModuleNotFoundError`**: activate the venv (`source .venv/bin/activate`).
- **`Could not locate a Flask application`**: run `export FLASK_APP=wsgi` first.
- **Supabase connection hangs or times out**: check that you used the *session pooler*
  string and that the password has no unescaped special characters (URL-encode `@`, `#`, `/`).
- **`prepared statement ... already exists`**: you're on the transaction pooler (port 6543).
  Switch to 5432.
- **Port 8000 in use**: `PORT=8001 python wsgi.py`.
