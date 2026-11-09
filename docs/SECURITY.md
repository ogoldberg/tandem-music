# Security, privacy and cost controls

Last reviewed: 2026-11-09. Tandem is an **experimental public web app**, not a production-ready multi-user service.

## Current boundaries
- GitHub repository is public. Outsiders can read/fork/propose PRs; they cannot push without permissions. **Branch-protection status has not been verified**. Configure rulesets: required PR review, tests, no force pushes, restrict bypass.
- Vercel hosts frontend and backend. Production `/api/chat` refuses calls without configured `TANDEM_ACCESS_TOKEN`; with one, callers supply it as `x-tandem-token`. This is a shared bearer secret, **not user authentication**.
- `TANDEM_API_KEY` belongs exclusively in Vercel server variables. Never put provider keys in JS, project JSON, README, Git history, issue reports or chat.
- `/api/analyze`, `/api/polish` and `/api/tune` are public, consume CPU and **lack rate limits**. Abuse can still incur infrastructure cost even when AI calls are guarded.
- The browser saves a project draft and may save the access token in `localStorage`; avoid shared devices and clear site data after using them. A production app needs a better auth/session model.
- The application does not implement server-side project storage. Audio sent for DSP is read into memory for a request; do not assume zero logs, network metadata or cloud retention outside our code.
- On-device Basic Pitch lazily fetches model/JS from external CDNs. Review privacy, network and supply-chain risks; pin or self-host audited assets before production.
- The backend validates LLM edit actions but needs stronger schema validation, rate limiting, resource constraints, threat modeling and audit logs.

## Before enabling paid AI
1. Set `TANDEM_ACCESS_TOKEN` to a strong random secret; set provider/model/key only on Vercel.
2. Configure provider budget/caps and alerts. Be aware shared access tokens can be copied or stolen.
3. Avoid logging audio, secrets or complete personal prompts.
4. Add authentication, per-user quotas, safe usage limits and abuse monitoring before public commercial launch.
5. Separate project ownership and persistent object storage if cloud saving is introduced.

## Other safeguards
- Browser microphone access requires permission and HTTPS.
- Short clip and WAV-format limits exist; review memory/CPU use under malicious and unexpected inputs.
- No commercial plugin binaries or copyrighted sample libraries are redistributed.
- Run dependency/license/vulnerability reviews and independent privacy/security testing.
- Report discovered vulnerabilities privately to the repository owner instead of opening public issues with exploit details.
