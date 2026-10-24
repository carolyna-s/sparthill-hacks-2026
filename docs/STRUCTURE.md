# Repo structure

This guide explains where things live and where new code should go. To set up and run the app, see the [README](README.md).
For the roadmap, see [PLAN.md](PLAN.md). For the tables, see [SCHEMA.md](SCHEMA.md).

The repo holds one Flask app that renders HTML pages on the server. There's no separate frontend or build step:
pages are Jinja templates styled with Tailwind, which loads from a CDN.

```
sparthill-hacks-2026/
├── app/                  the Flask application (all Python + templates)
│   ├── templates/        Jinja pages, one folder per feature area
│   └── static/           static assets (empty for now)
├── migrations/           Alembic database migrations (generated, then committed)
├── tests/                pytest suite
├── docs/                 all Markdown docs: README, plan, schema, known gaps, this file
├── wsgi.py               entry point: `python wsgi.py` (dev) or `gunicorn wsgi:app` (prod)
├── gunicorn.conf.py      production server settings
├── Dockerfile            production image: runs migrations, then gunicorn
├── docker-compose.yml    optional: app + local Postgres
├── requirements.txt      runtime dependencies
├── requirements-dev.txt  runtime + test dependencies
├── .env.example          template for .env (copy it; never commit .env)
├── .gitignore            what git skips (see "Not committed" below)
└── .dockerignore         what the Docker image leaves out (docs, tests, local data, secrets)
```

All Markdown docs live in `docs/`, and the repo root holds only the files that tools expect to
find there.

### Not committed

These are created on your machine and are listed in `.gitignore`, so never commit them.

| Path | What it is |
| --- | --- |
| `.env`, `.env.*` | Your local settings and secrets (`.env.example` is the exception and is committed) |
| `.venv/` | Your Python virtual environment |
| `instance/` | Local SQLite database (`mentorship.db`), created on first run |
| `data/` | Local file uploads, used when `S3_BUCKET` is empty |
| `__pycache__/`, `.pytest_cache/`, `.coverage`, `htmlcov/` | Python and test caches |
| `.vscode/`, `.idea/`, `.DS_Store`, `*.log` | Editor, OS, and log files |

## `app/`: the application

`app/__init__.py` holds `create_app()`, which wires everything together. It sets up the
extensions, registers each blueprint (a Flask group of routes), and defines the CLI commands
`flask seed` and `flask send-reminders`.

### Feature modules (blueprints)

Each of these files defines a blueprint, so it owns a group of URLs and the templates that
go with them.

| File | URLs | Purpose | Templates |
| --- | --- | --- | --- |
| `routes.py` | `/`, `/dashboard`, `/healthz`, `/internal/cron/reminders` | Landing page, each user's dashboard, health check, and the cron endpoint that sends scheduled reminders | `landing.html`, `dashboard.html` |
| `auth.py` | `/register`, `/login`, `/logout` | Email and password accounts, plus the `role_required(...)` decorator that limits a page to certain roles | `auth/` |
| `intake.py` | `/profile/<step>`, `/apply`, `/agreements` | The 4-step sign-up form (`STEPS`; steps 1-2 required, see `REQUIRED`), application review and submit (the questions are in `QUESTIONS`), and signing digital agreements | `intake/` |
| `program.py` | `/modules`, `/messages/<id>`, `/meetings/<id>`, `/feedback` | Modules with prework and postwork uploads, attendance check-ins, messages between a mentor and mentee, mentor-scheduled meetings, and feedback ratings | `program/` |
| `staff.py` | `/staff/...` | Staff-only pages: reviewing applicants, approving matches, creating modules, and reports | `staff/` |

### Core logic (no routes)

| File | Purpose |
| --- | --- |
| `models.py` | Every database table as a SQLAlchemy model ([SCHEMA.md](SCHEMA.md) describes each one) |
| `matching.py` | The matching engine: scores and ranks mentors for each mentee and assigns pairs one-to-one (each mentor gets at most one mentee). The scoring functions take plain dicts, so you can test them without a database |
| `taxonomy.py` | Fixed tag lists (career interests, goals, development areas) shared by the profile forms and the matching engine |
| `reminders.py` | Finds reminders that are due and sends them. Each reminder is logged so it's never sent twice, which makes it safe to run repeatedly |

### Infrastructure adapters

These files switch between a local and an AWS implementation based on settings in `.env`.

| File | Locally | In production |
| --- | --- | --- |
| `config.py` | Reads `.env` and uses SQLite when `DATABASE_URL` is empty | Postgres (Supabase) |
| `storage.py` | Saves uploads to `./data/uploads` | S3, when `S3_BUCKET` is set |
| `notify.py` | Prints emails to the console | Sends through Amazon SES, when `EMAIL_BACKEND=ses` |
| `extensions.py` | Shared `db`, `migrate`, `login_manager`, and `csrf` objects, imported everywhere so imports don't loop | (same) |

### Other

- `seed.py`: demo data loaded by `flask seed`, including staff, 4 mentors, 5 mentees, a
  cohort, an agreement, and a sample module. Every demo account's password is `password123`.
- `templates/base.html`: the layout and navigation every page extends.
- `templates/_macros.html`: reusable form and UI pieces.
- `templates/staff/_summary.html`: a partial that several staff pages include.

## `migrations/`

These Alembic files are managed by Flask-Migrate. Don't edit `env.py` or `alembic.ini`.
Migration scripts go in `versions/`. To change the schema:

1. Edit `app/models.py`.
2. Run `flask db migrate -m "what changed"` and check the generated file in `migrations/versions/`.
3. Run `flask db upgrade`.
4. Commit the new migration file along with the model change.

## `tests/`

Run them with `pytest`. Tests always use a throwaway SQLite database, never the one in `.env`.

| File | What it checks |
| --- | --- |
| `conftest.py` | Fixtures: a fresh seeded app and test client for each test, plus a `login()` helper |
| `test_pages.py` | Every page renders for every role, which catches template errors |
| `test_flows.py` | End-to-end HTTP flows for each role, with checks on what lands in the database |
| `test_matching.py` | Unit tests for the scoring and assignment math in `matching.py` |

## `docs/`

| File | Contents |
| --- | --- |
| `README.md` | Setup, running locally, everyday commands, config, troubleshooting (GitHub shows it on the repo homepage) |
| `PLAN.md` | Goals, architecture, and the roadmap |
| `SCHEMA.md` | What each table and column means |
| `GAPS.md` | What isn't built yet, roughly in priority order |
| `STRUCTURE.md` | This file |

## Where do I put…

- **A new page in an existing area**: add a route to that area's blueprint (for example
  `program.py`) and a template in the matching `templates/<area>/` folder. Then add the
  URL to `tests/test_pages.py`.
- **A new feature area**: create `app/<area>.py` with a `Blueprint`, register it in
  `create_app()` in `app/__init__.py`, and add a `templates/<area>/` folder.
- **A new table or column**: change `models.py`, generate a migration (see above), and
  update `docs/SCHEMA.md`.
- **A new matching tag or weight**: change `taxonomy.py` for tags or `WEIGHTS` in `matching.py`.
- **A new setting or secret**: read it in `config.py` and document it in `.env.example`.
- **A staff-only page**: put it in `staff.py`. That blueprint already restricts every route to staff.
- **A new doc**: add it to `docs/` and list it in the `docs/` table above.
- **A one-off script** (data fix, import): add a `flask` CLI command in `create_app()` instead of a
  loose script, so it runs with the app's config and database.
- **A new runtime dependency**: add it to `requirements.txt` with an exact version. Test-only
  tools go in `requirements-dev.txt`.
