# Gaps and next steps

What the framework doesn't do yet, roughly in priority order.

## Product

- **Real-time messaging.** Threads poll every 5 seconds and the unread badge every 15. Move to
  WebSockets or server-sent events only if polling load becomes a problem.
- **Charts on reports.** Reporting is tables and totals. Add trends over time (attendance
  per event, rating distribution) and CSV export.
- **Satisfaction surveys.** Nothing collects ratings right now (the 1–5 form on the module page
  was removed), so the rating columns in staff reports stay empty. Mid- and end-of-program
  surveys with structured questions would replace it.
- **Module end times.** Modules only have a start time, so post-work opens when the session
  starts. Add a duration or end time to open it when the session ends.
- **Mentee choice.** Mentees can't see or rank their top mentors; staff decide. Consider
  showing mentees their top 3 and letting them pick or rank before staff approval.
- **Matching inputs.** Add availability/time zone, location, identity or background
  preferences, and hard constraints (e.g. same organization excluded).
- **Cohorts.** Events and matches carry `cohort_id`, but pages don't filter by cohort yet.
- **Staff tooling.** No UI to edit agreements, questions, or the taxonomy; no editing or
  deleting modules. (Admins can create staff accounts but can't change an existing user's role.)
- **Notifications in-app.** Reminders are email only.

## Platform

- **Auth hardening.** Password reset, email verification, rate limiting on login.
  Optionally move to Supabase Auth.
- **Uploads.** No file type allow-list or virus scanning.
- **Privacy.** Admins can delete accounts, but users can't delete or export their own data;
  decide retention for messages and submissions.
- **Observability.** Logs go to stdout (Cloud Logging on Cloud Run). Add error tracking.
- **Deploy automation.** Cloud Run deploys are manual (`gcloud run deploy`, see the README).
  Add a Cloud Build trigger or GitHub Actions workflow that runs `pytest`, builds, and deploys
  on push to `main`, and keep env vars in Secret Manager.
