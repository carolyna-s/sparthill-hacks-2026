# Gaps and next steps

What the framework doesn't do yet, roughly in priority order.

## Product

- **Real-time messaging.** Messages need a page reload. Next step: poll with a small fetch
  loop or HTMX; WebSockets (API Gateway WebSocket or Flask-SocketIO) only if needed.
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
  Optionally move to Amazon Cognito.
- **Uploads.** No file type allow-list or virus scanning.
- **Privacy.** No account deletion / data export flow; decide retention for messages
  and submissions.
- **Observability.** Logs go to stdout (CloudWatch on App Runner). Add error tracking.
- **Infrastructure as code.** AWS setup in `docs/PLAN.md` is manual; capture it in
  CDK or Terraform, plus a GitHub Actions workflow to build, push to ECR, and deploy.
