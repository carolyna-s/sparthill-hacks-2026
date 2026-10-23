# Schema

Defined in `app/models.py`; migrations in `migrations/versions/`. Table names are the
lowercased class names. Timestamps are naive UTC.

## People

**user** — one account per person.
`email` (unique), `password_hash`, `name`, `role` (`mentee` | `mentor` | `staff`), `created_at`.

**profile** — one per mentee/mentor (`user_id` unique).
`headline`, `bio`, `organization`, `career_interests`, `goals`, `development_areas` (JSON
lists of tags from `app/taxonomy.py`), `capacity` (mentors: max concurrent mentees).
For mentees the tag fields mean *what I want*; for mentors, *what I can offer*.

## Intake

**cohort** — a program run. `name`, `starts_on`, `ends_on`, `is_active`. New applications
attach to the newest active cohort.

**application** — one per user. `status` (`draft` → `submitted` → `accepted` | `waitlisted` |
`rejected`), `answers` (JSON `{question_key: text}`; questions in `intake.QUESTIONS`),
`submitted_at`, `reviewed_by_id`, `reviewed_at`, `staff_notes`.

**agreement** — versioned agreement text. `title`, `version`, `body`, `audience` (`mentee` |
`mentor` | `all`), `is_active`. Publish a new version as a new row and deactivate the old one;
everyone will be asked to sign again.

**agreement_signature** — `agreement_id`, `user_id` (unique together), `typed_name`,
`signed_at`, `ip_address`.

## Matching

**match** — `mentee_id`, `mentor_id`, `cohort_id`, `status` (`proposed` → `approved` |
`rejected`; `approved` → `ended`), `score` (0–100), `score_breakdown` (JSON per dimension:
`coverage`, `shared`, `weight`), `proposed_at`, `decided_by_id`, `decided_at`.
`proposed` and `approved` matches count against mentor capacity.

## Program

**event** — a session. `title`, `description`, `starts_at`, `location`, `checkin_code`,
`prework_prompt`/`prework_due`, `postwork_prompt`/`postwork_due` (blank prompt = none).

**submission** — `event_id`, `user_id`, `kind` (`prework` | `postwork`; unique together),
`body`, `file_key` (S3 key or path under `UPLOAD_DIR`), `file_name`, `submitted_at`.
Resubmitting overwrites.

**attendance** — `event_id`, `user_id` (unique together), `checked_in_at`.

**message** — `match_id`, `sender_id`, `body`, `sent_at`, `read_at` (set when the other
participant opens the thread).

**feedback** — satisfaction. `user_id`, `event_id` *or* `match_id`, `rating` (1–5), `comment`.

**reminder_log** — `user_id`, `key` (unique together; e.g. `prework:3`, `agreement:1`,
`message:42`), `sent_at`. Dedupes the reminder sweep.
