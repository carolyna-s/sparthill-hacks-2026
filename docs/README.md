# Mentorship Platform

A web app for running a mentorship program: mentors and mentees apply and sign agreements,
a weighted matching engine ranks mentors for each mentee, matched pairs work through modules
(pre-work, a live session with check-in, post-work), message each other and schedule meetings,
and staff review applicants, approve matches, and track participation. Admins manage accounts.

One Flask service serves the whole app. Data lives in **Supabase Postgres** and uploads in
**Supabase Storage**; there is no local-database mode (tests use a throwaway SQLite file). The target host is **AWS**. Roadmap and design: [docs/PLAN.md](PLAN.md).

## How people use the app

There are four roles. Mentors and mentees sign themselves up. Staff and admin accounts are
created by an admin.

### Mentee and mentor

1. **Register.** On `/register`, pick *mentee* or *mentor* and enter your name, school, email, and
   a password (8+ characters).
2. **Onboard.** Until onboarding is done, every page except the profile steps sends you back to
   the step you were on ("Please complete onboarding to access …"). In order:
   - **Profile**, in 4 steps: *About you*, *Availability & language* (both required, since
     matching filters on them), then *Preferences* and *In your own words* (optional). A LinkedIn
     PDF can be uploaded to pre-fill suggestions.
   - **Agreements**: sign each active agreement for your role by typing your name.
   - **Application**: answer the application questions and submit.
3. **Wait for review.** Staff accept or reject the application. Only accepted people go into
   the matching pool. You can still edit your submitted application from the dashboard
   (*Submitted Application* → `/dashboard/application`).
4. **Get matched.** Staff propose and approve pairs. Matching is one-to-one, and mentees and
   mentors don't choose each other. Once a pair is approved it shows under **Your match** /
   **Your mentees** on the dashboard.
5. **Work together.**
   - **Dashboard:** your match, a *To do* list of pre-/post-work that's open and not yet
     submitted, a month calendar with sessions, due dates, and meetings, upcoming items, and
     resource links.
   - **Messages:** a thread with your match. Mentors schedule meetings from the thread (and can
     cancel them), and the meetings show on both calendars.
   - **Modules:** the list shows every module with its date and status pills. Opening one shows
     three steps in order:
     1. **Pre-work:** mentees can submit it (text and/or a file) at any time and update it
        until they're done.
     2. **Session:** at the live session, mentees enter the check-in code staff show them.
     3. **Post-work:** locked until the session's start time. It then opens like pre-work.

     Mentors don't submit. They see each prompt plus their mentees' submissions and files, and
     the list shows "N/M mentees submitted".
6. **Reminders by email** (via `flask send-reminders` or the cron endpoint), each sent at most
   once: unsigned agreements, open pre-/post-work due soon (accepted mentees only), and messages
   left unread for a while.
7. **Instant emails** (templates in `app/templates/email/`): both people get one when their match is
   confirmed, and 3 minutes after a message the recipient gets "You have new messages from X" if
   they haven't opened the thread yet, at most once an hour per thread.

### Staff

Staff land on **Dashboard** (Staff Overview) and work through the cycle from the top nav:

- **Applicants:** the combined participant and application list. Read each application and accept
  or reject it (with notes). The table has Name, Role, Application, Attendance_Rate, Match,
  Submitted, and Acceptance Status columns and
  pending/all filters, live search, sortable columns, quick accept/reject controls, and a confirmed
  bulk accept action for every pending application. The last decision can be undone.
- **Matching:** *Auto-propose* runs the engine over everyone accepted and unmatched, or propose
  for one mentee. Staff **approve** to release a match to the mentee for confirmation, **reject**
  (needs a reason; the pair is never proposed again), or cancel proposals. Reviews started from
  the proposal list continue through the remaining proposals until staff exits or the queue is
  complete. Mentees must confirm before a match becomes active; declining a mentor returns them
  to the pool, while withdrawing ends their application. Staff can override the matchmaker for
  an accepted unmatched mentee and an accepted mentor with an open slot; assigning a full mentor
  sends a request to the backend admin for approval. Any approved capacity override still waits
  for both mentee and mentor confirmation, shown as notifications inside each participant's
  **Your Match** section. If the mentor denies it, the mentee returns to the pool. Overrides are
  recorded in the audit log. The mentee's matchmaker override control is positioned at the far
  right of their row.
- **Modules:** create a module with a date, location, check-in code, and optional pre-/post-work
  prompts and due dates. On a module page, staff see the check-in code to display at the session.
- **Reports:** attendance and pre-/post-work counts per module, plus totals. Open a module from
  the report to see the participant lists for those who checked in and those who did not.

### Admin (`backend` role)

Admins can open every staff page, plus **/admin**:

- **Admin Dashboard:** account totals, logins by role over the last 7 and 30 days, accounts that never
  logged in, recent activity and sign-ups, staff roster, and approve/deny actions for mentor
  capacity override requests.
- **Users:** mentor, mentee, and staff accounts, match status, and disable/enable controls. Search
  updates as you type; click column headings to sort, with the latest heading as the primary sort.
  The list includes last access and attendance rate (check-ins divided by past modules since signup;
  `N/A` when no past module is eligible); clicking a username opens the account editor.
  Disabling an account signs the person out on their next request and blocks login. Accounts can
  also be permanently deleted there; related user, application, profile, and match data is removed
  and audit references are anonymized. The active admin cannot delete their own account or the last
  active admin account.
- **Matching logistics:** staff accept/deny counts and a dropdown of denied pairs with reasons.
- **New staff account:** create staff accounts with a temporary password. Backend admin accounts
  cannot be created through the interface.
- **Audit Logs:** actor/source and descriptions of staff/admin changes, including account edits,
  password-reset requests, application reviews, and module creation. Match proposals and decisions
  are excluded.

Admins can require a user to change their password at the next login. The user must still enter the
current password to log in, then choose a new password of at least eight characters.

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

### 2. Connect to Supabase

The app only runs against the shared Supabase project and refuses to start without it.

1. In the Supabase dashboard, open **sparthill-hackathon → Connect**.
2. Copy the **Session pooler** connection string (port `5432`) and fill in the password.
   Use the session pooler, not the direct connection (IPv6-only) or the transaction pooler
   on port 6543 (it breaks prepared statements).
3. Paste it into `.env`:
   ```
   DATABASE_URL=postgresql://postgres.<project-ref>:<password>@aws-0-us-east-1.pooler.supabase.com:5432/postgres
   ```
4. For uploads, set `SUPABASE_SERVICE_ROLE_KEY` (Project Settings → API Keys → secret /
   service_role). `SUPABASE_URL` is already filled in. Without it, uploading a file errors.

Everyone shares the same data, so coordinate before running `flask seed` or
any migration there.

### 3. Create tables and demo data

```bash
export FLASK_APP=wsgi              # Windows PowerShell: $env:FLASK_APP="wsgi"
flask db upgrade                   # creates/updates tables in whichever DB .env points at
flask seed                         # demo cohort, agreement, a module, admin, staff, mentors, mentees
```

`flask seed` does nothing if the database already has data.

On Supabase the schema is already applied, so `flask db upgrade` reports nothing to do. Don't
run `flask seed` there unless the team agrees, because it adds demo accounts to the shared database.

### 4. Start the server

```bash
python wsgi.py                     # http://localhost:8000, auto-reloads on code changes
```

### 5. Log in

All demo accounts use the password `password123`.

| Role | Email |
| --- | --- |
| Admin | `backend.admin@example.org` |
| Staff | `staff.admin@example.org` (also `jamie.torres@example.org`, never logged in; `dana.whitfield@example.org`, deactivated) |
| Mentor | `priya.raman@example.org`, `marcus.lee@example.org`, `elena.ortiz@example.org`, `sam.okafor@example.org` |
| Mentee | `jordan.kim@example.org`, `avery.patel@example.org`, `riley.chen@example.org`, `taylor.brooks@example.org`, `morgan.diaz@example.org` (pending review) |

Quick tour:
1. As **staff**: go to **Applicants** and accept Morgan, then **Matching** → *Auto-propose* → approve.
2. As jordan.kim's mentor: open **Messages** and schedule a meeting. As **jordan.kim**: see it on the
   dashboard calendar, open **Modules** → *Updating your Resume*, submit pre-work, and check in with code `RES01`.
   Post-work stays locked until the session's start time.
3. As **staff**: open **Reports** to see the attendance and submission counts.
4. As **admin**: open **User Audit** to see every account's activity, and deactivate or reactivate one.

## Everyday commands

| Task | Command |
| --- | --- |
| Run tests | `pytest` (always uses a throwaway SQLite DB, never `.env`'s) |
| Send due reminders | `flask send-reminders` (prints emails unless `EMAIL_BACKEND=ses`) |
| Embed text answers for matching | `flask embed` (needs `OPENAI_API_KEY`; only calls the API for new or changed answers) |
| Change the schema | edit `app/models.py`, then `flask db migrate -m "what changed"` and `flask db upgrade`, then commit `migrations/versions/*` |
| Run like production | `gunicorn -c gunicorn.conf.py wsgi:app` |
| Production container | `docker build -t mentorship . && docker run -p 8000:8000 --env-file .env mentorship` |

## Project layout

Full guide, including where to put new code: [docs/STRUCTURE.md](STRUCTURE.md).

```
app/
  __init__.py     app factory + CLI commands (seed, send-reminders, embed)
  config.py       settings from .env
  models.py       all tables (docs/SCHEMA.md)
  taxonomy.py     dropdown/tag vocabularies used by profiles and matching
  auth.py         register / login / logout, role_required
  intake.py       onboarding gate, profiles, applications, digital agreements
  linkedin.py     LinkedIn PDF parsing into profile suggestions
  matching.py     scoring, ranking, one-to-one assignment
  embeddings.py   OpenAI embeddings of free-text answers, for the text part of the score
  program.py      modules, pre-/post-work, check-ins, messaging, meetings
  reminders.py    idempotent reminder sweep
  staff.py        applicant review, people, match approval, modules, reports
  admin.py        account metrics, user audit, (de)activation, creating staff accounts
  routes.py       landing, dashboard, application edits, /healthz, cron endpoint
  storage.py      file uploads (Supabase Storage; local disk in tests)
  types.py        vector column type (pgvector on Postgres, JSON on SQLite)
  notify.py       email (console, SMTP or SES), each logged to email_log
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
| `DATABASE_URL` | required: app won't start | Supabase session-pooler URI |
| `FLASK_SECRET_KEY` | dev-only key | a long random string in any shared or deployed environment |
| `SUPABASE_URL` | prefilled in `.env.example` | project API URL |
| `SUPABASE_SERVICE_ROLE_KEY` | uploads fail | the project's secret / service_role key (server-only) |
| `SUPABASE_STORAGE_BUCKET` | `uploads` | another private bucket |
| `EMAIL_BACKEND` | `console` (log only) | `smtp` (Gmail: set `MAIL_FROM`, `SMTP_USERNAME`, `SMTP_PASSWORD` = app password) or `ses` |
| `CRON_SECRET` | cron endpoint disabled | shared secret for `POST /internal/cron/reminders` |
| `ANTHROPIC_API_KEY` | planned chatbot and resume parsing off | API key |
| `OPENAI_API_KEY` | text answers not used in matching | OpenAI API key (embeddings only), then run `flask embed` once |

## Troubleshooting

- **`ModuleNotFoundError`**: activate the venv (`source .venv/bin/activate`).
- **`Could not locate a Flask application`**: run `export FLASK_APP=wsgi` first.
- **Supabase connection hangs or times out**: check that you used the *session pooler*
  string and that the password has no unescaped special characters (URL-encode `@`, `#`, `/`).
- **`prepared statement ... already exists`**: you're on the transaction pooler (port 6543).
  Switch to 5432.
- **Port 8000 in use**: `PORT=8001 python wsgi.py`.
