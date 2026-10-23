# Mentorship Platform: Plan

Updated Oct 23, 2026

## 1. Goal

Build a mentorship platform that drives real engagement between mentors and mentees.

| Component | What it covers | Status |
| --- | --- | --- |
| Intake | Mentor and mentee profiles, separate applications, digital agreements, resume/LinkedIn import | Profiles, applications, and agreements are built. Import is planned (§5) |
| Matching | Weighted, score-based ranking of mentors per mentee | Engine built on tags. New features and adjustable weights planned (§4) |
| Program tools | Prework/postwork, attendance check-ins, automated reminders, messaging | Built |
| Staff dashboard | Applicant review, match approval, participation and satisfaction reporting | Built. Weight tuning UI planned |
| Site assistant | LLM chatbot that helps users find their way around and see what's next | Planned (§6) |

## 2. Architecture

```
 Browser ──HTTPS──▶ Flask app (AWS App Runner, Docker)
                     ├─ Jinja pages + small JS (chat widget)
                     ├─ SQLAlchemy ──────────▶ Supabase Postgres  (all app data)
                     ├─ storage.py ──────────▶ Supabase Storage   (resumes, submissions)
                     ├─ Claude API ──────────▶ chatbot, resume extraction
                     └─ notify.py ───────────▶ Amazon SES         (reminder email)
 EventBridge Scheduler ──hourly──▶ POST /internal/cron/reminders
```

| Layer | Choice | Why |
| --- | --- | --- |
| Web | Flask + Jinja + Tailwind CDN | Already built; one service with no frontend build step |
| Database | **Supabase Postgres** via SQLAlchemy | Managed Postgres the team already has (`sparthill-hackathon`, us-east-1). SQLite stays available for offline dev and tests |
| Migrations | Alembic (`flask db upgrade`) | Schema lives in code; same migrations run on SQLite and Supabase |
| File storage | Supabase Storage (private bucket) | One vendor for data and files. `storage.py` gets a Supabase backend next to the S3 one |
| Auth | Flask-Login (email + password, roles) | Works now. Supabase Auth with LinkedIn sign-in is a stretch goal (§5.3) |
| LLM | Claude API (`anthropic` Python SDK) | Chatbot tool use, plus structured extraction from resumes |
| Hosting | AWS App Runner (container from ECR) | Stateless container, health checks, autoscaling. Connects to Supabase over the public internet |
| Email / cron | SES + EventBridge Scheduler | Native AWS; the reminder sweep is already idempotent |

### 2.1 Supabase usage rules

- **The app connects as a server.** Flask uses the Postgres connection string (session
  pooler, port 5432). It does not use supabase-js or the anon key in the browser.
- **Lock down the Data API.** Supabase exposes `public` tables over REST to anyone holding
  the anon key. After the first `flask db upgrade`, enable RLS on every table with no
  policies, which denies the anon and authenticated roles. The app's Postgres role bypasses
  RLS. Add an Alembic migration that does this so new tables get it too.
- **MCP is for development only.** Use the Supabase MCP connection to inspect tables, run
  ad-hoc SQL, read logs, and check the security/performance advisors. Schema changes still
  go through Alembic migrations in the repo, never through MCP or the dashboard, so code and
  database don't drift.
- **One shared database, so be careful.** Seeding and migrating against Supabase affects
  everyone. Use SQLite locally for experiments; consider a Supabase branch for risky
  migrations.

## 3. Users and sign-in

- Mentors and mentees **apply separately**: each registers with a role, fills in their own
  profile, and gets their own application questions (`intake.QUESTIONS`).
- Both **sign in through the app** and land on a role-specific dashboard. Staff accounts are
  created by an admin, never self-registered.
- All profile and application data lives in the database. Uploaded files live in the private
  storage bucket and are only ever served through short-lived signed URLs.

## 4. Matching algorithm

### 4.1 Inputs

Collected from the intake form as dropdowns (and pre-filled from a resume where possible):

| Feature | Input | Mentee meaning | Mentor meaning |
| --- | --- | --- | --- |
| Major | single select (from a list with field groups) | studying / studied | studied |
| Concentration | single select, filtered by major | focus area | focus area |
| Interests | multi-select tags | wants exposure to | works in / knows |
| Years of experience | number | own experience | own experience |
| Goals *(existing)* | multi-select | wants help with | can help with |
| Development areas *(existing)* | multi-select | wants to grow | can coach |

Majors, concentrations, and interests move into `app/taxonomy.py` as fixed lists, plus a
field group for each major (STEM, Business, Health, Humanities, Arts, Social Sciences).

### 4.2 Per-feature similarity (each 0 to 1)

| Feature | Similarity |
| --- | --- |
| Major | 1.0 if same major · 0.5 if same field group · 0 otherwise |
| Concentration | 1.0 if same · 0 otherwise (skipped if mentee left it blank) |
| Interests | share of the mentee's interests the mentor covers: `|shared| / |mentee|` |
| Years of experience | `gap = mentor − mentee`. 1.0 when `MIN_GAP ≤ gap ≤ MAX_GAP` (default 3–10), falling linearly to 0 at `gap = 0` and at `gap = MAX_GAP + 10` |
| Goals, development areas | same coverage formula as interests |

A feature the mentee left blank counts as 1.0, so missing data never drags scores down.

### 4.3 Weighted score

```
score = 100 × Σ (w_f × sim_f) / Σ w_f
```

- **Weights are adjustable by staff.** A `matching_config` table holds one active weight set
  (default: interests 0.35, major 0.20, experience 0.20, concentration 0.10, goals 0.10,
  development areas 0.05). The staff Matching page gets sliders with a live re-ranked
  preview before saving.
- **Hard filters run before scoring**: mentor at capacity, mentor not accepted, mentor
  rejected for this mentee before. Optional later: same organization excluded.
- **Explainable.** Every proposed match stores the per-feature breakdown and the weight-set
  id that produced it, so staff see why the pair was suggested and old matches stay auditable
  after weights change.
- **Assignment** stays greedy (best pairs first, respecting capacity). If cohort size makes
  that visibly unfair, switch to optimal assignment (Hungarian / min-cost flow via `scipy`).

### 4.4 Code changes

- `models.Profile`: add `major`, `concentration`, `years_experience`, `interests`
  (replacing `career_interests`). Add a `MatchingConfig` table and `Match.config_id`.
- `matching.py`: a similarity function per feature, plus a `FEATURES` registry. The existing
  `score_pair` / `rank_mentors` / `assign` keep their signatures but take weights as an
  argument.
- Unit tests per similarity function and for weight normalization.

## 5. Intake connectors

Goal: less typing, better matching data. The form is always the source of truth.
Connectors only **pre-fill suggestions that the user reviews and confirms**.

### 5.1 Resume upload (core)

1. User uploads a PDF or DOCX on the profile page. It's stored in the private bucket.
2. Text is extracted server-side (`pypdf`, `python-docx`).
3. Two extraction passes:
   - **Keyword pass (deterministic, free).** An alias dictionary per taxonomy value
     (`"ML"`, `"machine learning"` → *data science*; `"B.S. Computer Science"` → major
     *Computer Science*) finds majors, concentrations, and interests.
   - **LLM pass (more accurate).** Claude with structured outputs returns
     `{major, concentration, interests[], years_experience, goals[]}`. Every field is
     constrained to the taxonomy's enum values, so the result maps straight onto the
     dropdowns. Years of experience is estimated from dated roles, which keywords can't do
     reliably.
4. The profile form shows the suggestions pre-selected and highlighted. The user edits and saves.
5. We keep the file (staff can view it during review) and the extracted fields. The raw text
   is discarded after extraction.

### 5.2 LinkedIn

- **No scraping.** LinkedIn's terms prohibit scraping, and its API doesn't give apps access to
  work history or education.
- **Instead, use the profile PDF.** LinkedIn's *More → Save to PDF* export produces a resume-like
  PDF, so users upload it through the same resume flow (§5.1). The upload page explains how.
- We can also store a LinkedIn profile URL on the profile, for staff to click during review.

### 5.3 Sign in with LinkedIn (stretch)

Supabase Auth supports LinkedIn (OIDC), which gives name, email, and photo only. Adopting it
means replacing Flask-Login with Supabase Auth sessions verified server-side. That's
worthwhile only if time allows after §4–§6.

## 6. Site assistant (chatbot)

### 6.1 What it does

A chat bubble on every signed-in page that helps users get around and stay on track:

- "Where do I sign the agreement?" → explains it and returns a **link button** to `/agreements`.
- "What do I need to do this week?" → reads the user's own to-do list and upcoming events.
- "How does matching work?" → answers from the program FAQ.
- Staff: "How many applications are waiting?" → reads aggregate counts and links to the queue.

It never **takes actions** such as submitting, signing, approving, or sending messages. It
points the user to the page where they do that themselves.

### 6.2 Design

- **Endpoint:** `POST /chat` (login required, CSRF-protected). The browser keeps the
  conversation in `sessionStorage` and sends it with each message. Nothing is stored
  server-side in v1.
- **Model:** Claude via the `anthropic` SDK, using `claude-opus-5-5` at `effort: "low"`
  (short, tool-driven turns) with server-side refusal fallbacks enabled. If cost matters at
  scale, the team can choose `claude-haiku-5-5` for this route after comparing answers.
- **System prompt** (cached): site map (page → URL → what it's for → which roles can see it),
  program FAQ (`docs/help/*.md`), and tone rules (short answers, always offer a link).
- **Tools** (read-only, run with the *session's* user id, never an id from the model):

  | Tool | Returns | Roles |
  | --- | --- | --- |
  | `link_to(page)` | URL + label from an allow-list filtered by role | all |
  | `my_status()` | application status, unsigned agreements, to-dos, match name | mentee, mentor |
  | `upcoming_events()` | next events with prework/postwork due dates | all |
  | `program_stats()` | counts from `staff.report_data()` | staff |

  Implemented with the SDK's tool runner (`@beta_tool` functions in `app/assistant.py`).
- **UI:** a small vanilla-JS widget in `base.html`. Assistant replies render as text plus
  link buttons for any `link_to` results.

### 6.3 Guardrails

- Tools only read data the current user could already see on their own pages. No tool
  touches another participant's profile or messages.
- Per-user rate limit (e.g. 30 messages per hour) and a cap on conversation length.
- The chatbot is hidden if `ANTHROPIC_API_KEY` is unset, so the app runs without it.
- Log token usage per request. Don't log message content.

## 7. Milestones

| # | Milestone | Main work | Done when |
| --- | --- | --- | --- |
| M0 | Framework *(done)* | App skeleton, all four components on tags, tests | `pytest` green, demo flow works |
| M1 | Supabase live | Point `DATABASE_URL` at Supabase, `flask db upgrade`, RLS migration, seed, Supabase Storage backend | Team shares one DB; advisors show no RLS warnings |
| M2 | New matching | Taxonomy lists, profile fields, per-feature similarity, `matching_config` + staff sliders | Staff change weights and see rankings change; tests per feature |
| M3 | Resume import | Upload, text extraction, keyword pass, LLM structured pass, confirm-suggestions UI, LinkedIn PDF instructions | Uploading a sample resume pre-fills the form correctly |
| M4 | Site assistant | `/chat`, tools, widget, rate limit | Scripted questions per role answered with correct links |
| M5 | AWS deploy | ECR image, App Runner, secrets, SES, EventBridge cron | Public URL works end to end; reminders arrive by email |
| M6 | Polish | Charts on reports, real-time-ish messaging (polling), demo script | Demo rehearsed |

M2, M3, and M4 can run in parallel once M1 is done. They touch different files (`matching.py`
and `staff.py`; `intake.py` and a new `extract.py`; a new `assistant.py`).

## 8. AWS deployment (M5)

1. Build and push: `docker build --platform linux/amd64 -t mentorship .`, then tag and push to ECR.
2. App Runner service from the image: port 8000, health check `/healthz`.
   Env from Secrets Manager: `DATABASE_URL` (Supabase session pooler), `FLASK_SECRET_KEY`,
   `ANTHROPIC_API_KEY`, `CRON_SECRET`, Supabase Storage key, `EMAIL_BACKEND=ses`,
   `MAIL_FROM`, `BASE_URL`.
3. The container runs `flask db upgrade` on start, then gunicorn.
4. SES: verify the sender. Production access is needed to email unverified addresses.
5. EventBridge Scheduler, hourly: `POST https://<app>/internal/cron/reminders` with header
   `X-Cron-Secret`.

## 9. Open questions

- **Major list.** Use a standard list (e.g. CIP codes, condensed) or the host program's own?
  Who owns the concentration list per major?
- **Experience gap.** Is 3–10 years the right ideal mentor-mentee gap? Should staff tune it
  alongside the weights?
- **Mentee input on matches.** Do mentees see and rank their top 3 before staff approve, or is
  matching staff-only?
- **Resume retention.** How long do we keep uploaded resumes, and can applicants delete them?
- **Chatbot scope.** Should it answer general career questions, or strictly the site and program?
  (Recommendation: strictly site and program for now.)
- **Supabase Auth.** Move sign-in to Supabase Auth (enables LinkedIn login and password reset
  for free), or keep Flask-Login?
