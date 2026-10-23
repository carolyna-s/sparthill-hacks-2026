# Gaps and next steps

What the framework doesn't do yet, roughly in priority order.

## Product

- **Real-time messaging.** Messages need a page reload. Next step: poll with a small fetch
  loop or HTMX; WebSockets (API Gateway WebSocket or Flask-SocketIO) only if needed.
- **Charts on reports.** Reporting is tables and totals. Add trends over time (attendance
  per event, rating distribution) and CSV export.
- **Satisfaction surveys.** Only 1–5 ratings + comment today. Mid- and end-of-program
  surveys with structured questions would give richer reporting.
- **Mentee choice.** Mentees can't see or rank their top mentors; staff decide. Consider
  showing mentees their top 3 and letting them pick or rank before staff approval.
- **Matching inputs.** Add availability/time zone, location, identity or background
  preferences, and hard constraints (e.g. same organization excluded). Consider an
  optimal assignment (min-cost flow) instead of greedy once cohorts are large.
- **Cohorts.** Events and matches carry `cohort_id`, but pages don't filter by cohort yet.
- **Staff tooling.** No UI to edit agreements, questions, or the taxonomy; no way to
  promote users to staff; no editing or deleting events.
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
