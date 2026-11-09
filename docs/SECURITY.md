# Security, privacy and cost controls

Last reviewed: 2026-11-09. Tandem is an **experimental public web app**, not a production-ready multi-user service.

## Current boundaries
- GitHub repository is public. Outsiders can read/fork/propose PRs; they cannot push without permissions. **Branch-protection status has not been verified**. Configure rulesets: required PR review, tests, no force pushes, restrict bypass.
- Vercel hosts frontend and backend. Production `/api/chat` refuses calls without configured `TANDEM_ACCESS_TOKEN`; with one, callers supply it as `x-tandem-token`. This is a shared bearer secret, **not user authentication**.
- `TANDEM_API_KEY` belongs exclusively in Vercel server variables. Never put provider keys in JS, project JSON, README, Git history, issue reports or chat.
- `/api/analyze`, `/api/polish` and `/api/tune` are public and consume CPU. They are rate-limited per client IP through a shared Upstash Redis store and their inputs are bounded (see **Request limits** below). Per-IP limits do not stop a distributed attacker; abuse can still incur infrastructure cost.
- The browser saves a project draft and may save the access token in `localStorage`; avoid shared devices and clear site data after using them. A production app needs a better auth/session model.
- The application does not implement server-side project storage. Audio sent for DSP is read into memory for a request; do not assume zero logs, network metadata or cloud retention outside our code.
- On-device Basic Pitch lazily fetches model/JS from external CDNs. Review privacy, network and supply-chain risks; pin or self-host audited assets before production.
- The backend validates LLM edit actions and the `/api/chat` request schema; `/api/chat` itself is not rate-limited beyond the shared token. Threat modeling and audit logs are still missing.

## Request limits (SEC.1)
Enforced by `RequestGuardMiddleware` in `request_guards.py` before a route reads its body:

| Limit | Value | Applies to | Response |
|---|---|---|---|
| Rate limit, one shared bucket per client IP | 20 requests per 60 s fixed window (`TANDEM_AUDIO_RATE_LIMIT`, `TANDEM_AUDIO_RATE_WINDOW_SECONDS`) | `POST /api/analyze`, `/api/polish`, `/api/tune` | 429 with `Retry-After` |
| Request body | 18,000,000 bytes (checked on `Content-Length` and while streaming) | audio routes | 413 |
| Request body | 262,144 bytes | `POST /api/chat` | 413 |
| WAV format | 16-bit PCM, 1-2 channels, 8-96 kHz, 1 frame to 90 s; anything else or unparseable | audio routes | 400 |
| Tune clip length | 25 s | `/api/tune` | 400 |
| Chat project | typed: `bpm` 45-220, `instrument` one of piano/marimba/bass/strings/chip, at most 1024 `notes` (`m` 0-127, `t` 0-600 s, `d` >0-600 s) and 1024 `drums` (`k` kick/snare/hat), boolean `melody_locked`, no other keys; `history` at most 12 user/assistant turns of 2000 chars | `/api/chat` | 422 |

**Where rate-limit state lives.** Vercel serverless instances do not share memory, so counters live in Upstash Redis (`UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN`, or the Vercel KV names `KV_REST_API_URL` + `KV_REST_API_TOKEN`), keyed `tandem:rl:audio:<client-ip>:<window>` and expiring after the window. On Vercel the client IP comes from `x-forwarded-for`, which the platform overwrites with the real address; elsewhere the socket address is used. **On Vercel without a configured store, or when the store errors, audio routes fail closed with 503** rather than run unlimited. Outside Vercel (local development, one process) an in-process counter is used when no store is configured.

Vercel's own platform limit on a function request body is 4.5 MB (per Vercel's documentation; not yet measured against this app), below the app's 18 MB cap, so long uncompressed WAVs (about 50 s of 44.1 kHz mono) are refused in production before they reach the app.

## Before enabling paid AI
1. Set `TANDEM_ACCESS_TOKEN` to a strong random secret; set provider/model/key only on Vercel.
2. Configure provider budget/caps and alerts. Be aware shared access tokens can be copied or stolen.
3. Avoid logging audio, secrets or complete personal prompts.
4. Add authentication, per-user quotas, safe usage limits and abuse monitoring before public commercial launch.
5. Separate project ownership and persistent object storage if cloud saving is introduced.

## Other safeguards
- Browser microphone access requires permission and HTTPS.
- Short clip, WAV-format and body-size limits are enforced and tested (`tests/test_api.py`); CPU cost of a maximum-size request has not been profiled on Vercel.
- No commercial plugin binaries or copyrighted sample libraries are redistributed.
- Run dependency/license/vulnerability reviews and independent privacy/security testing.
- Report discovered vulnerabilities privately to the repository owner instead of opening public issues with exploit details.
