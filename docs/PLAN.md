# Mentorship Platform: Plan

Updated Oct 23, 2026 (rev 3: matching pipeline, confirmation, schema live)

## 1. Goal

Build a mentorship platform that drives real engagement between mentors and mentees, with as
much of the cycle automated as possible. Staff keep the final say on every match.

| Component | What it covers | Status |
| --- | --- | --- |
| Intake | Separate mentor and mentee sign-up, profiles, applications, agreements, resume/LinkedIn-PDF import | Profiles, applications, and agreements are built. LinkedIn PDF import is built; resume import is planned (§6) |
| Matching | 4-stage pipeline: hard filters → structured score → embedding similarity → LLM context scaling | Schema live in Supabase. Basic engine built; pipeline planned (§4) |
| Match review | Staff approve or deny every proposed pair. A deny requires feedback, which the algorithm learns from | Approve, and deny with required reason + explanation (stored, pair excluded from re-proposal) built, plus a per-participant dashboard view for staff. Percent view, auto re-match, and load view planned (§5) |
| Program tools | Prework/postwork, check-ins, reminders, messaging, **automated match emails**, **mentee confirm/withdraw** | Built except match emails and confirmation (§5.5–5.6) |
| Resources | Tab of school resources for mentees | Planned (§7) |
| Site assistant | LLM chatbot that helps users find their way around | Planned (§8) |
| Reporting | Participation, satisfaction, mentor load | Participation and satisfaction built. Load view planned |

## 2. Roles

| Role | Who | Can |
| --- | --- | --- |
| **Mentee** | Students | Sign up, fill in profile, apply, sign agreements, see resources, and, once matched, message their mentor and do program work. **No say in who they're matched with.** |
| **Mentor** | Professionals / alumni | Same as mentee, minus resources. **No say in who they're matched with.** |
| **Staff** | Program team | Review applicants, see all proposed matches with % match, **approve or deny** (final say), see mentor load, run events, see reports, manage the resources tab |
| **Backend** | Technical admins | Everything staff can, plus: matching weights and settings, taxonomy lists (majors, pathways, clubs, groups), apply or reject AI-suggested weight changes, cohort dates, user and role management, email templates, logs and audit trail |

Mentees, mentors, and staff use the app day to day. Backend is the "keys to the machine" role,
so staff can't accidentally change how matching works, and there's always someone who can
fix configuration without touching code. Staff and backend accounts are created by a backend
user, never self-registered.

## 3. Cohort cycle (automated)

```
 Day 0 ─────────── Day 30 ──────── Day 30–35 ─────────── Day 35+ ───────────▶
 SIGN-UP OPEN       AUTO-MATCH       STAFF REVIEW           RELEASE + PROGRAM
 anyone registers   job runs at      approve / deny         emails sent automatically,
 and applies        close            (deny → auto re-match) messaging and events open
```

| Phase | What happens | Automated? |
| --- | --- | --- |
| **Sign-up open** (1 month) | Anyone registers as mentor or mentee and completes profile, application, and agreements. A complete application is **auto-accepted**; staff can still pull one out | Yes |
| **Auto-match** | At the close date, a scheduled job embeds any new soft answers, runs the 4-stage pipeline (§4), and assigns pairs within capacity. Staff get an email: "N pairs ready for review" | Yes |
| **Staff review** | Staff see every proposed pair with its % match and approve or deny each one. A deny **automatically re-matches** that mentee with the next-best candidate, which appears back in the queue | Re-match is automatic. Decisions are human |
| **Release** | When every pair is decided (or the review deadline passes, with a reminder to staff first), approved pairs get **intro emails automatically** | Yes |
| **Confirm** (7 days) | Each mentee confirms they're still in (messaging unlocks) or withdraws with feedback and optionally asks for a re-match (§5.6) | Reminders and re-match are automatic |
| **Program** | Events, prework/postwork, check-ins, reminders, satisfaction ratings | Reminders are automatic |

Dates live on the `cohort` row (`signup_opens`, `signup_closes`, `review_deadline`), which
backend sets. A cohort that is open shows a countdown on the landing page.

## 4. Matching algorithm

Staff have the final say, so the algorithm's job is to put the best possible pairs in front of
them and to **learn from every deny**. That's why the last stage is an LLM: it is the part that
reads staff feedback and applies it to new pairs. Matching runs in four stages:

```
           hard questions (dropdowns / MCQ)            soft questions (free text)
                       │                                         │
   ┌───────────────────▼──────────────────┐                      │
1  │ HARD FILTERS: drop impossible pairs  │                      │
   └───────────────────┬──────────────────┘                      │
   ┌───────────────────▼──────────────────┐   ┌──────────────────▼──────────────────┐
2  │ STRUCTURED SCORE (0-1)               │ 3 │ SEMANTIC SCORE (0-1)                 │
   │ weighted per-feature similarity      │   │ vector embeddings, cosine similarity │
   └───────────────────┬──────────────────┘   └──────────────────┬──────────────────┘
                       └──────────── base = α·S + (1−α)·M ─────────┘
                                          │  top K candidates per mentee
                       ┌──────────────────▼───────────────────┐
4                      │ LLM CONTEXT SCALING                   │ ◀── retrieved staff deny
                       │ final = base × m,  m ∈ [0.85, 1.15]   │     and mentee withdraw feedback
                       └──────────────────┬───────────────────┘
                                          ▼
                      assignment (capacity + load balancing) → staff review
```

### 4.1 Two kinds of questions

| | Hard questions | Soft questions |
| --- | --- | --- |
| **Input** | Dropdowns, multiple choice, numbers | Free-text textbox |
| **Used for** | Stage 1 filters + stage 2 structured score | Stage 3 semantic score + stage 4 LLM context |
| **Stored in** | Typed `profile` columns (options from `taxonomy_term`) | `question` / `answer` rows, each answer with a `vector(384)` embedding |
| **Examples** | Major, concentration, pathway, interests, years of experience, languages, organization, clubs, student groups, goals | "What do you hope to get out of a mentor?" ↔ "What do you hope to offer?"; "Where do you see yourself in 3–5 years?" ↔ "Describe your career path"; "How do you like to receive feedback?" ↔ "Describe your mentoring style" |

Every soft question for mentees is **paired** with one for mentors (`question.pairs_with_id`), so
we compare like with like: what the mentee hopes for against what the mentor offers.

#### Hard question inputs

| Feature | Input | Mentee | Mentor |
| --- | --- | --- | --- |
| Major | dropdown | studying | studied |
| Concentration | dropdown filtered by major | focus | focus |
| Pathway | multi-select filtered by major (e.g. EE → Robotics, Power Systems, Embedded; Nutrition → Clinical Dietetics, Public Health, Food Science) | where they want to go | where they've been or are now |
| Interests | multi-select | wants exposure to | works in |
| Years of experience | number | own | own |
| Languages | multi-select, plus "must share a language" checkbox | speaks | speaks |
| Organization | searchable dropdown | target organizations (optional) | current or past employers |
| Clubs | multi-select from the school's list, plus "other" | current clubs | prior clubs (college) and current affiliations |
| Student groups / programs | multi-select, e.g. CAPISE, veteran, first-gen, transfer, EOP, international, plus opt-in "prefer a mentor who shares this" | belongs to | belongs or belonged to |
| Goals | multi-select | wants help with | can help with |

Student groups can be sensitive. They're optional, used only when the mentee opts in, never shown
to the other party, and visible to staff only on the review screen.

### 4.2 Stage 1: hard filters

A pair is dropped before scoring if any of these hold: mentor at capacity · either side not
accepted for this cohort · mentee requires a shared language and there isn't one · pair is in
`match_exclusion` (previously denied, or withdrawn as "not a good fit").

### 4.3 Stage 2: structured score

Per-feature similarity, each 0–1:

| Feature | Similarity |
| --- | --- |
| Major | 1.0 same major · 0.5 same field group (STEM, Business, Health, …) · 0 |
| Concentration | 1.0 same · 0 |
| Pathway, interests, goals | share of the mentee's selections the mentor covers |
| Years of experience | 1.0 when the mentor is 3–10 years ahead (settable), falling linearly to 0 at 0 and at 20 years ahead |
| Languages | 1.0 if any shared (when it's not already a hard filter) |
| Organization | 1.0 if the mentor's organization is one of the mentee's targets |
| Clubs | 1.0 shared club · 0.5 same club category · 0 |
| Student groups | share of the mentee's opted-in groups the mentor shares |

`S = Σ w_f·sim_f / Σ w_f`. A feature the mentee left blank counts as 1.0. Default weights:
pathway 0.15, interests 0.15, major 0.10, experience 0.10, languages 0.10, clubs 0.10, student
groups 0.10, goals 0.10, organization 0.05, concentration 0.05.

### 4.4 Stage 3: semantic score (vector embeddings)

- **Built for the sign-up form's text boxes** (interests, other goals, what they're looking
  for): each is embedded when saved with OpenAI `text-embedding-3-small` at 384 dims
  (`app/embeddings.py`), stored in `profile.text_embeddings`, and scored as the `text` weight in
  `app/matching.py`. Blank `OPENAI_API_KEY` turns it off; `flask embed` backfills. Claude has no
  embedding model, so this is the one non-Anthropic API. The notes below are the original
  design for the `question`/`answer` tables.
- Every soft answer is embedded when saved (384-dim). Stored in `answer.embedding` (pgvector,
  HNSW index).
- For each paired question q: `sim_q = cosine(mentee answer, mentor's paired answer)`, rescaled
  from the typical range to 0–1.
- `M = Σ weight_q·sim_q / Σ weight_q`. Unanswered questions are skipped.
- `profile.embedding` (all of a person's soft answers combined) enables fast "nearest mentors"
  lookups in Postgres, e.g. to pre-select candidates when cohorts get large.

Embeddings capture what dropdowns can't: "I want someone who's been through a career switch
from lab research to industry" lands near a mentor who wrote about exactly that path, even with
no shared keywords.

### 4.5 Stage 4: LLM context scaling (where feedback is used)

Combine `base = α·S + (1−α)·M` (default α = 0.6), take each mentee's **top K = 5** candidates,
and send them to Claude in one request per mentee with:
- both sides' hard answers and soft answers (student groups only if opted in)
- each candidate's S, M, and per-feature breakdown
- **relevant past feedback**: the deny and withdraw comments whose embeddings are nearest to this
  mentee's and these mentors' profiles (pgvector search over `match_feedback.embedding`), plus
  any active rules from applied config suggestions

Claude returns, per candidate, through structured outputs:

```
{ "mentor_id": 12, "multiplier": 1.08, "confidence": "high",
  "note": "Both moved from research into industry robotics; past denies flagged pure-startup
           mentors for research-track mentees, which doesn't apply here.",
  "flags": [], "feedback_ids_used": [41, 57] }
```

- `final = 100 × base × multiplier`, with the multiplier clamped to `[0.85, 1.15]` (setting
  `context_range`). The LLM can move a pair up or down **±15%** but can't override the
  evidence entirely.
- The LLM only sees the K candidates that passed the filters, so it can't invent pairs or
  bypass capacity.
- Everything is stored on the match (`structured_score`, `semantic_score`,
  `context_multiplier`, `ai_review`, `config_id`), so staff see how the final % was built:
  **"82% = structured 78 · semantic 85 · AI ×1.04"**.
- Cost: one LLM call per mentee per (re)match, `claude-opus-5-5` at low effort. Cohort-scale
  runs can use the Batch API at half price.

### 4.6 Assignment

**Built:** matching is strictly one-to-one (each mentor takes one mentee; `profile.capacity` is
no longer asked or used, so there's no load balancing). Pairs are assigned with the Hungarian
algorithm (`scipy.optimize.linear_sum_assignment` in `app/matching.py`): the assignment with the
highest total score. Every mentee is matched while free mentors last: the solver avoids pairs
that fail a hard filter, but if nothing compatible is left it matches them anyway and flags the
pair for staff (`score_breakdown.filters_failed`). Rejected pairs are never proposed again. Each
run covers only the pool: mentees and mentors with no approved or pending match; approved
matches are out of it for good, and each new proposal records its `rematch_round`. Weights,
α, the experience gap, λ, K, and the context range are all in the active `matching_config`
(versioned, set by backend).

## 5. Match review (staff) and the feedback loop

### 5.1 Review screen: percent match view

One row per proposed pair:

| Mentee | Mentor | Match % | Why (top 3 features) | Mentor load | AI note | Action |
| --- | --- | --- | --- | --- | --- | --- |
| Jordan Kim | Priya Raman | **86%** | Robotics pathway · EE major · shared Spanish | 1 / 2 | ✓ consistent with past approvals | Approve · Deny |

- Hover the % to see how it was built: structured · semantic · AI multiplier (§4.5).
- Expand a row to see the full per-feature breakdown, both profiles, and both sides' free-text
  answers side by side.
- Filters: by % range, by mentor, "flagged by AI".
- **Bulk approve**: "approve all ≥ 80% with no AI flags" for the clear cases, so staff time
  goes to the borderline ones.
- Counters at the top: pending, approved, denied, mentees still unmatched.

### 5.2 Deny requires feedback

Denying opens a short form, and the deny doesn't go through without it:

- **Reason** (dropdown): different interests or pathway · experience gap wrong · language or
  communication · personality or fit concern · mentor overloaded · conflict of interest · other
- **Comment** (free text, shown and required only for "other"): e.g. "Mentee wants industry research, mentor is pure startup."

Then, automatically:
1. The pair goes on an exclusion list and is never proposed again.
2. The mentee is re-matched with the best remaining candidate (after AI review), and the new
   pair appears in the queue marked "re-match #2".
3. The feedback is stored in `match_feedback` for the learning loop.

### 5.3 How feedback flows back into matching

Every deny (§5.2) and every withdrawal (§5.6) is a `match_feedback` row: reason, comment,
and an **embedding of the comment**. It's used in two ways:

**a) Immediately, through the LLM stage (§4.5).** The next time any similar mentee or mentor
is scored (including the automatic re-match right after a deny), the nearest past feedback is
retrieved and included in the prompt. The multiplier and note reflect it. If staff deny "pure
startup mentor for a research-track mentee" twice, the third such pair comes in lower and
flagged, citing those feedback ids.

**b) Over time, through config suggestions.** At the end of each review round, Claude reads all
of the cohort's feedback plus approve/deny rates by feature and proposes concrete changes, each
with reasoning and the feedback ids it's based on:
- weight changes ("raise pathway 0.15 → 0.20: 7 of 11 denies cited pathway mismatch")
- settings ("narrow the experience gap to 3–8")
- rules ("treat Clinical Dietetics and Food Science as partial pathway matches")

These are saved as `config_suggestion` rows and shown to backend for **one-click apply**, which
creates a new `matching_config` version. They aren't auto-applied, so a few denies can't swing
the whole algorithm, and every change has a named approver.

### 5.4 Mentor load dashboard

A staff page showing every mentor with:
- capacity, approved mentees, pending proposals, and a utilization bar
  (green < 80%, amber at capacity, red if over, which should never happen and is flagged)
- mentors with **zero** mentees, so staff can see untapped capacity
- a link to that mentor's proposed and approved pairs

The same summary (overloaded / at capacity / idle counts) shows on the staff overview.

### 5.5 Automated match emails

On release, sent through SES from editable templates (backend):
- **Mentee:** "You've been matched with {mentor}" with headline, why you were matched (top
  features), link to message them, first steps, and the kickoff event.
- **Mentor:** the same, the other way round.
- **Mentees still unmatched:** "We're still finding the right mentor" with what happens next.
- **Staff:** release summary (approved, denied, unmatched).

Every send is logged in `reminder_log`-style dedup, so re-running the release never double-emails.

### 5.6 Mentee confirms they're still in (or withdraws)

Released pairs aren't active until the mentee confirms. Interest can fade over a month-long
sign-up window, and an unconfirmed match wastes a mentor slot.

1. The match email has **Confirm** and **I can't continue** buttons, and the same choice shows on
   the mentee's dashboard. The deadline is `confirm_by = released_at + cohort.confirm_days`
   (default 7).
2. **Confirm** sets `mentee_confirmed_at`, unlocks messaging, and emails the mentor that it's on.
   An optional "anything your mentor should know?" note is saved as `match_feedback` (kind
   `confirm`).
3. **Withdraw** asks for a reason (no time · not a good fit with this mentor · found other
   mentorship · program isn't for me · other), an optional comment, and "match me with someone
   else?":
   - The match becomes `withdrawn` and the mentor's slot frees up. Mentor and staff are notified.
   - Feedback is stored (kind `withdraw`, with `wants_rematch`) and feeds the LLM like a deny.
   - "Not a good fit" also adds the pair to `match_exclusion`.
   - Wants a re-match → the mentee goes back into the queue, and the auto re-match proposes
     someone new for staff approval. Doesn't → the application becomes `withdrawn`.
4. No answer → reminders at day 3 and day 6. After the deadline, staff see the pair flagged
   "unconfirmed" and decide. It's not auto-withdrawn.
5. Optional later: a 30-day "still finding this useful?" pulse (kind `check_in`) that also feeds
   the feedback loop.

Mentors could get the same confirm step. It's off for now; turn it on if mentor drop-off is a
problem.

## 6. Intake connectors

The form is always the source of truth. Connectors only **pre-fill suggestions that the user
confirms**.

### 6.1 Resume upload

1. Upload a PDF or DOCX on the profile page. It's stored in the private Supabase Storage bucket.
2. Extract the text server-side (`pypdf`, `python-docx`).
3. Two passes:
   - **Keyword pass** (free, deterministic): an alias dictionary per taxonomy value finds
     majors, pathways, interests, clubs, and languages.
   - **LLM pass**: Claude with structured outputs returns major, concentration, pathways,
     interests, clubs (prior and current), languages, organizations, and years of
     experience. Every field is constrained to the taxonomy's values, so the result maps
     straight onto the dropdowns.
4. The form shows the suggestions pre-selected and highlighted. The user edits and saves.
5. Keep the file (staff can view it in review) and the confirmed fields. Discard the raw text.

### 6.2 LinkedIn (clubs and history for mentors)

- **No scraping.** LinkedIn's terms prohibit it, and its API doesn't give apps work history,
  education, or activities.
- **Use the LinkedIn PDF instead.** Mentors use *More → Save to PDF* on their profile and upload
  it through §6.1. That PDF includes education, activities and societies (prior clubs), and
  experience, which is exactly the data we wanted from scraping. The upload page shows how in
  two screenshots.
- Store the profile URL so staff can click through during review.
- Stretch: "Sign in with LinkedIn" through Supabase Auth (OIDC), which gives name, email, and
  photo only.

## 7. Resources tab (mentees)

A **Resources** page in the mentee nav listing school resources: career center, tutoring,
counseling, financial aid, clubs directory, program-specific offices (e.g. CAPISE, veteran
services). It's purely informational.

- Stored in a `resource` table: title, description, URL, category, optional student-group tag.
  Staff add and edit entries in the app.
- Filter by category. Resources tagged with a group the mentee belongs to show first.
- The site assistant can link to them ("where's tutoring?").

## 8. Site assistant (chatbot)

A chat bubble on signed-in pages that helps users get around. It **reads but never acts**: it
points users to the page where they do things themselves.

- **Examples:** "Where do I sign the agreement?" → link to `/agreements`. "What's due this
  week?" → the user's to-dos. "Where's the writing center?" → resources link. Staff: "How many
  pairs are pending?" → count and link to the review queue.
- **Endpoint:** `POST /chat`, login required. The conversation is kept in the browser's
  `sessionStorage`.
- **Model:** Claude via the `anthropic` SDK, `claude-opus-5-5` at `effort: "low"` with
  server-side refusal fallbacks. The team can choose `claude-haiku-5-5` for this route if
  cost matters after comparing answers.
- **Tools** (read-only, always run with the session's user id):
  `link_to(page)` (role-filtered allow-list), `my_status()`, `upcoming_events()`,
  `find_resource(query)`, and, for staff and backend only, `review_queue_stats()` and
  `mentor_load_summary()`.
- **Guardrails:** tools only return what the user could already see on their own pages. Per-user
  rate limit. Hidden if `ANTHROPIC_API_KEY` is unset. Token usage is logged, message content isn't.

## 9. Architecture

```
 Browser ──HTTPS──▶ Flask app (AWS App Runner, Docker)
                     ├─ Jinja pages + small JS (chat widget, review table)
                     ├─ SQLAlchemy ──────────▶ Supabase Postgres  (all app data)
                     ├─ storage.py ──────────▶ Supabase Storage   (resumes, submissions)
                     ├─ Claude API ──────────▶ AI match review, feedback digest,
                     │                         resume extraction, chatbot
                     └─ notify.py ───────────▶ Amazon SES         (match + reminder email)
 EventBridge Scheduler ──▶ POST /internal/cron/{reminders, cohort-tick}
```

| Layer | Choice |
| --- | --- |
| Web | Flask + Jinja + Tailwind CDN (built) |
| Database | Supabase Postgres via SQLAlchemy. SQLite for offline dev and tests |
| Migrations | Alembic (`flask db upgrade`). Schema changes only through migrations, never MCP or the dashboard |
| Files | Supabase Storage, private bucket, signed URLs |
| Auth | Flask-Login with 4 roles. Supabase Auth is optional later |
| LLM | Claude API (`anthropic` SDK), structured outputs + tool use |
| Hosting / email / cron | AWS App Runner, SES, EventBridge Scheduler |

**Cohort automation** runs as one idempotent `cohort-tick` job (hourly). It checks each
cohort's dates and does whatever is due: close sign-up and auto-match, remind staff before the
review deadline, release and email. Running it twice does nothing extra.

**Supabase rules:** the app connects server-side over the session pooler (port 5432). RLS is
enabled on every table with no policies, which blocks the public Data API; the app's role
bypasses RLS. MCP is for inspection, SQL, logs, and advisors during development.

## 10. Data model

**Applied to Supabase (`sparthill-hackathon`) on Oct 23, 2026** via Alembic revision
`31ed905ca990`. RLS is on for every table with no policies, so the public Data API is blocked
and only the app's server connection can read or write. Full column reference:
[SCHEMA.md](SCHEMA.md).

| Area | Tables |
| --- | --- |
| People | `user` (role: mentee / mentor / staff / backend), `profile` (hard-question answers + combined embedding) |
| Intake | `cohort` (phase + cycle dates), `application` (+ `withdrawn`), `agreement`, `agreement_signature` |
| Soft questions | `question` (mentee↔mentor pairing, weight), `answer` (text + `vector(384)`) |
| Matching | `match` (structured / semantic / multiplier / final, AI review, config, re-match round, release + confirm/withdraw timestamps), `matching_config` (versioned weights + settings), `config_suggestion`, `match_exclusion` |
| Feedback loop | `match_feedback` (deny / withdraw / confirm / check_in, reason, comment, `vector(384)`) |
| Config + content | `taxonomy_term` (all dropdown options with parent/group), `resource` |
| Program | `event`, `submission`, `attendance`, `message`, `feedback` (ratings), `reminder_log` |

The app code still matches on the original tags (`career_interests`, `goals`,
`development_areas`); M2 moves it onto the new columns.

## 11. Milestones

| # | Milestone | Main work | Done when |
| --- | --- | --- | --- |
| M0 | Framework *(done)* | App skeleton, all components on basic tags, tests | `pytest` green, demo works |
| M1 | Supabase + roles | ~~Schema + RLS on Supabase~~ (done), team `.env` setup, reference data (config v1, soft questions, taxonomy), Storage backend, `backend` pages | Team shares one DB; backend user can manage roles |
| M2 | New intake + matching | Taxonomy terms, hard-question form, soft-question form, embedding job, stages 1–3, versioned config, load-balanced assignment | Seed cohort produces sensible pairs; tests per stage |
| M3 | Review + feedback | Percent view with score build-up, bulk approve, deny-with-feedback, auto re-match, mentor load dashboard | Staff can run a full review of 10+ pairs |
| M4 | Automation | Cohort dates, `cohort-tick` job, auto-accept, release + match emails, mentee confirm/withdraw | A cohort with shortened dates runs end to end without clicks except approve/deny and confirm |
| M5 | AI layer | Stage 4 context scaling with feedback retrieval, config suggestions, resume/LinkedIn-PDF extraction | A deny visibly lowers similar pairs in the next re-match; resume pre-fills the form |
| M6 | Resources + assistant | Resources tab, chatbot with tools | Scripted questions per role answered with correct links |
| M7 | AWS deploy + polish | App Runner, SES, schedulers, report charts, demo script | Public URL; demo rehearsed |

After M1, M2 and M6 can run in parallel. M3 builds on M2. M4 and M5 can run in parallel after M3.

## 12. Open questions

- **Backend role.** Is the meaning above (technical admin: weights, taxonomy, users, config) what
  the team intends?
- **Student groups list.** Which groups and programs go in the dropdown (CAPISE, veteran,
  first-gen, EOP, transfer, …)? Who maintains it?
- **Pathways.** Who drafts the major → pathway lists? Start with the 10–15 most common majors.
- **Clubs list.** Is there a source list of school clubs we can import?
- **Unmatched mentees.** If a mentee runs out of candidates after denies, do they wait for the
  next cohort, or can staff hand-pick a mentor (overriding capacity)?
- **Deny permanence.** Is a denied pair excluded for this cohort only, or forever?
- **Auto-accept.** Is auto-accepting every complete application OK, or do some need manual
  review (e.g. mentors need vetting)?
- **Resume retention.** How long are resumes kept, and can users delete them?
