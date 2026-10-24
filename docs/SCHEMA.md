# Schema

Defined in `app/models.py`. Migrations live in `migrations/versions/` (head: `b5d8e2f4a6c1`;
Supabase `sparthill-hackathon` is at `c6557a04922b` as of Oct 23, 2026). Table names are the snake_cased
class names. Timestamps are naive UTC.

On Postgres, the `vector(384)` columns use pgvector (in the `extensions` schema) with HNSW
cosine indexes. On SQLite they're JSON lists (`app/types.py`). RLS is enabled on every table
with no policies, which blocks Supabase's public Data API. The app connects as a role that
bypasses RLS.

## People

**user**: one account per person.
`email` (unique), `password_hash`, `name`, `role` (`mentee` | `mentor` | `staff` | `backend`),
`created_at`, `last_login_at`, `last_seen_at` (bumped at most once a minute), `is_active`
(false = deactivated: can't log in, signed out, left out of matching). Backend users ("Admin" in
the UI) can do everything staff can, plus create staff accounts, (de)activate any account, and
edit configuration (`/admin`).

**profile**: one per mentee/mentor (`user_id` unique). Holds the answers to the **hard
(dropdown) questions**. List fields are JSON arrays of `taxonomy_term.value`s. For mentees they
mean *what I want*; for mentors, *what I have/offer*.

| Column | Notes |
| --- | --- |
| `headline`, `bio`, `organization` | free display text |
| `major`, `concentration` | single values |
| `pathways`, `goals`, `development_areas` | lists |
| `career_interests` | legacy list, replaced by `industry`; no longer written |
| `years_experience` | integer |
| `languages`, `language_required` | list + "must share a language" flag. Matching treats a shared language as a hard filter; blank means English |
| `availability` | hard filter: `"Monday - morning"` … `"Sunday - night"` (morning, afternoon, evening, night); a pair must share one slot |
| `industry` | soft filter: one of `taxonomy.INDUSTRIES`, or whatever the user typed; matched ignoring case |
| `education_paths` | soft-filter list; scores 1 if the mentor has any of the mentee's picks |
| `school`, `prefers_alumni` | asked at sign-up. Mentee's school / mentor's alma mater; same-school bonus only when the mentee opts in |
| `interests`, `goals_other`, `looking_for` | free text (interests, goals beyond the presets, what the mentee wants / mentor offers); shown to staff, not scored yet |
| `organizations` | mentee: target orgs; mentor: current/past employers |
| `clubs_prior`, `clubs_current` | lists |
| `student_groups`, `groups_opt_in` | sensitive; only used for matching if opted in; never shown to the other party |
| `capacity` | unused: mentorship is one-to-one (`matching.MENTEES_PER_MENTOR`) |
| `linkedin_url`, `resume_key`, `resume_file_name` | uploaded resume / LinkedIn PDF in storage |
| `linkedin_data` | JSON parsed from the LinkedIn PDF (`app/linkedin.py`): headline, organization, school, industry, summary, years_experience, experience, education, activities, skills, suggested `tags`, and `source` (`llm` or `keywords`). Only suggestions: the form columns above hold what the user confirmed. Kept for matching |
| `text_embeddings` | JSON: `{"model": "text-embedding-3-small:384", "fields": {field: {"hash", "vector"}}}` for `interests` / `goals_other` / `looking_for` (`app/embeddings.py`); the hash ties each vector to the text it came from |
| `embedding`, `embedding_model` | `vector(384)` of all soft answers combined (not filled yet) |

## Intake

**cohort**: a program run. `name`, `starts_on`, `ends_on`, `is_active`, `phase`
(`signup` → `matching` → `review` → `released` → `closed`), `signup_opens`, `signup_closes`,
`review_deadline`, `confirm_days` (default 7), `matched_at`, `released_at`.

**application**: one per user. `status` (`draft` → `accepted`; `withdrawn` if a mentee leaves
after matching; older records may retain `rejected`), `answers` (JSON), `submitted_at`.

**agreement**: versioned agreement text. `title`, `version`, `body`, `audience` (`mentee` |
`mentor` | `all`), `is_active`.

**agreement_signature**: `agreement_id` + `user_id` (unique), `typed_name`, `signed_at`, `ip_address`.

## Soft questions

**question**: a free-text matching question. `key` (unique), `audience` (`mentee` | `mentor`),
`prompt`, `help_text`, `pairs_with_id` (the mentor question a mentee question is compared
against), `weight`, `required`, `sort`, `is_active`.

**answer**: `user_id` + `question_id` (unique), `text`, `embedding` (`vector(384)`, null until
embedded), `embedding_model`, `updated_at`.

## Matching

**match**: a proposed or approved pair.

| Column | Notes |
| --- | --- |
| `mentee_id`, `mentor_id`, `cohort_id` | |
| `status` | `proposed` → `released` \| `rejected` (staff decision); `released` → `approved` (mentee confirms; capacity overrides also need mentor confirmation) \| `rejected` (a participant declines) \| `withdrawn` (mentee leaves program); `approved` → `withdrawn` \| `ended`. Only confirmed matches are active; rejected/withdrawn pairs aren't re-proposed |
| `score` | final 0–100 shown to staff |
| `structured_score`, `semantic_score`, `context_multiplier` | stage 2, stage 3, stage 4 (docs/PLAN.md §4) |
| `score_breakdown` | per-feature similarities and shared values |
| `ai_review` | `{note, flags, confidence, feedback_ids_used}` |
| `config_id` | the `matching_config` used |
| `rematch_round` | 1 for the first proposal, +1 for each auto re-match after a deny |
| `proposed_at`, `decided_by_id`, `decided_at` | staff decision || `released_at`, `confirm_by`, `mentee_confirmed_at`, `mentor_confirmed_at`, `withdrawn_at` | participant confirmation; mentor confirmation is required only for admin-approved capacity overrides |

**matching_config**: versioned weights. `weights` (`{feature: weight}`), `settings`
(`alpha`, `experience_gap`, `load_penalty`, `context_range`, `llm_top_k`), `is_active` (one
row), `source` (`manual` | `ai`), `notes`, `created_by_id`, `created_at`.

**config_suggestion**: an LLM-proposed change from feedback. `cohort_id`, `based_on_config_id`,
`proposed_weights`, `proposed_settings`, `rules` (plain-language), `rationale`,
`evidence_feedback_ids`, `status` (`pending` | `applied` | `dismissed`), `decided_by_id`,
`decided_at`, `applied_config_id`.

**match_exclusion**: a pair never to propose again. `mentee_id`, `mentor_id`, `cohort_id` (null =
all cohorts), `feedback_id`. Unique per (mentee, mentor, cohort). A mentee declining or releasing
a mentor creates an exclusion and returns the mentee to the pool.

**match_override_request**: staff requests for a backend admin to approve/deny assignment to an
at-capacity mentor. `mentee_id`, `mentor_id`, `requested_by_id`, `status` (`pending` | `approved` |
`denied`), decision actor/time, and the released match id. Approval permits the capacity override
but still requires the mentee to confirm the match.

## Feedback loop

**match_feedback**: what the matching LLM learns from. `match_id`, `author_id`, `kind`
(`deny` | `withdraw` | `confirm` | `check_in`), `reason` (from `MatchFeedback.REASONS`),
`comment`, `wants_rematch` (withdraw only), `embedding` (`vector(384)` of the comment),
`created_at`.

## Configuration and content

**taxonomy_term**: every dropdown option. `kind` (`major`, `concentration`, `pathway`,
`interest`, `goal`, `development_area`, `language`, `organization`, `club`, `student_group`),
`value`, `group` (a major's field group or a club's category), `parent_id` (concentrations and
pathways → their major), `sort`, `is_active`. Unique per (kind, value, parent).

**resource**: entries on the mentee Resources tab. `title`, `description`, `url`, `category`,
`student_group`, `sort`, `is_active`.

## Program

**event**: a module (shown as **Modules** in the app). `title`, `description`, `starts_at`, `location`, `checkin_code`,
`prework_prompt` / `prework_due`, `postwork_prompt` / `postwork_due`. There's no end time:
post-work can only be submitted once `starts_at` has passed (`Event.is_open`), while pre-work is
open from creation.

**submission**: `event_id` + `user_id` + `kind` (`prework` | `postwork`; unique), `body`,
`file_key`, `file_name`, `submitted_at`.

**attendance**: `event_id` + `user_id` (unique), `checked_in_at`.

**message**: `match_id`, `sender_id`, `body`, `sent_at`, `read_at`.

**meeting**: a mentor-scheduled meeting, shown on both people's dashboard calendars. `match_id`,
`starts_at`, `note`, `created_by_id`, `created_at`.

**feedback**: satisfaction ratings. `user_id`, `event_id` *or* `match_id`, `rating` (1–5), `comment`.
No page collects ratings right now (the module page's rating form was removed), so the table only
holds older rows.

**reminder_log**: `user_id` + `key` (unique; e.g. `prework:3`, `match-release:12`), `sent_at`.
Dedupes reminders and automated emails.
