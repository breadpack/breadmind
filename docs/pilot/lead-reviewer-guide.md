# Lead Reviewer Guide

You receive a Slack DM or a web-UI task every time a promotion candidate is
created. You have four actions:

## [승인] Approve
Promotes the candidate into `org_knowledge`. Confirm:
1. Title is descriptive (not "Re: Re: Re:").
2. Body has no secrets (API keys, customer names, personal data).
3. Category is appropriate (howto/decision/bug_fix/onboarding).
4. `source_channel` is set correctly:
   - Public-to-project knowledge → leave blank.
   - Sensitive but project-wide → a channel the team is already in.
   - Private → the originating channel id (only members see it).

## [거부] Reject
Use for duplicates, off-topic, or low-quality items. Add a one-line reason.

## [수정 후 승인] Edit then approve
Opens the web form. Fix title/body/category, then submit.

## [기각] Dismiss with reason
Kills the candidate permanently. Use when the content is sensitive in a way
that cannot be redacted (e.g. HR detail leaked into an engineering channel).

## Backlog hygiene
- Process within 48h.
- Backlog > 500 auto-pauses new extractions (alert fires). Burn it down before
  un-pausing.
- Suspicious patterns (mass-promote attempts) → check audit log, report in
  `#breadmind-security`.

## MFA
Approval requires MFA reconfirmation. If your prompt loops, logout/login.
