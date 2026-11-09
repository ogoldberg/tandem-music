# Development and Vercel operations

**Reviewed 2026-11-09.** Canonical repository: https://github.com/ogoldberg/tandem-music  
Production URL: https://tandem-music.vercel.app/

## Local setup

Use Python 3.12 (matches `.python-version`) and Node 22+.

```bash
git clone https://github.com/ogoldberg/tandem-music.git
cd tandem-music
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
uvicorn tandem_backend:app --reload --host 127.0.0.1 --port 8000
```

Open http://localhost:8000. The FastAPI server serves the browser interface and API **on the same origin**; there is no need for a second frontend development server. Browser microphone requires permission; localhost is treated as a secure context. The built-in transcription module loads model and JS dependencies from public CDNs.

If a PyWorld wheel is unsupported on your workstation's OS/architecture, investigate compatible binaries instead of silently removing tuning or calling the feature verified. On Vercel Python 3.12 the earlier `pyworld` package failed to resolve; `pyworld-prebuilt==0.3.6.post1` allowed a READY build. This is a packaging result, not proof of natural sounding correction.

## Tests

```bash
python -m pytest -q
node --test tests/transcription.test.mjs tests/polish.test.mjs tests/tuning.test.mjs
```

The GitHub Actions test workflow is `.github/workflows/tests.yml`. See [TESTING.md](TESTING.md) for the test matrix, real-device requirements, and release gates. Do not infer passing tests merely from a successful Vercel build.

## Production deployment

The repo is linked to the Vercel project `tandem-music`. Git pushes to `main` create production deployments using the FastAPI framework and `api/index.py`, with `vercel.json` configuring function duration and asset packaging. The app is intended for low fixed-cost personal experimentation, but Vercel and external model limits can still produce charges or request failures.

Vercel project settings: https://vercel.com/oren-goldbergs-projects-c0a37bd5/tandem-music/settings

### Configuration (server environment variables)

| Name | Meaning | Notes |
|---|---|---|
| `TANDEM_PROVIDER` | Text model API adapter | `openai-compatible` (default), `anthropic`, `gemini`, or `ollama`-compatible local endpoint |
| `TANDEM_MODEL` | Text model identifier | Provider-specific identifier; never assume a model exists without checking |
| `TANDEM_API_KEY` | Provider credential | Secret. Configure in Vercel; never commit |
| `TANDEM_BASE_URL` | Optional compatible API base | For supported gateways/proxies; ensure server can reach it |
| `TANDEM_ACCESS_TOKEN` | Shared personal access password for `/api/chat` | **Required on Vercel to use paid AI**; not per-user authentication |
| `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` | Shared rate-limit store for the audio routes | **Required on Vercel** or `/api/analyze` and `/api/tune` return 503. Add the Upstash Redis integration from the Vercel Marketplace (free tier); it sets these, or the equivalent `KV_REST_API_URL`/`KV_REST_API_TOKEN`, which are also accepted. Secret token; never commit |
| `TANDEM_AUDIO_RATE_LIMIT`, `TANDEM_AUDIO_RATE_WINDOW_SECONDS` | Audio-route rate limit per client IP | Defaults 20 requests per 60 s; limits are listed in [SECURITY.md](SECURITY.md#request-limits-sec1) |
| `TANDEM_ALLOWED_ORIGINS` | Cross-origin requests | Usually unnecessary with single-origin deployment |
| `TANDEM_MUSIC_PROVIDER`, `TANDEM_MUSIC_MODEL` | Reserved music-generation metadata | Setting these **does not enable** music generation; no adapter exists yet |

On the last inspected Vercel environment (2026-11-09), no model configuration variables were present. Check current settings directly before relying on this historical observation.

To generate a long random access token on macOS: `openssl rand -hex 32`. Store it in Vercel Production environment variables and enter the same token in the browser's **Connection** panel. Avoid shared computers since the browser currently saves this token in localStorage. Redeploy after environment changes. Do not paste credentials into issues, chat, screenshots or source.

### Sanity check after deploy

1. Inspect Vercel build logs and ensure the latest `main` commit is READY.
2. Visit `/`, `/transcription.js`, `/polish.js`, `/tuning.js`, `/api/health`, `/api/config`; verify HTTP 200 and current UI content.
3. Verify unconfigured `/api/chat` fails safely, but free `/api/analyze` and `/api/tune` remain accessible.
4. Test record/import → transcription → edit → export in a real browser. Test vocal tuning on a short clean recording and on one longer than 90 s (tuned in chunks), and listen to original/tuned audio, especially around 15 s, 30 s, 45 s... where chunks join.
5. Only after configuring a provider, verify a small authenticated text edit and that melody-lock behavior is preserved.
6. Review GitHub Actions results, browser console, Vercel runtime errors and external model usage/cost.

Do not treat an HTTP 200 response from the root or READY build as validation of pitch accuracy or audio quality.

## Persistence and media

Projects are local JSON exports/browser drafts, not cloud-saved. `/api/tune` and other audio routes accept in-memory uploads; Vercel functions have ephemeral filesystems. Cloud sync requires authenticated object storage and project ownership before enabling it.

## Cost and security

The provider key never belongs in browser JavaScript. Vercel production refuses `/api/chat` if `TANDEM_ACCESS_TOKEN` is unset. This prevents accidental public use of a paid model; the token is shared. Audio-processing routes are rate-limited per client IP (20 requests per 60 s by default) through Upstash Redis and fail closed with 503 on Vercel when the store is not configured; bodies are capped at 18 MB (audio) and 256 KB (chat). Full limits are in [SECURITY.md](SECURITY.md#request-limits-sec1). Configure provider budget limits and review [SECURITY.md](SECURITY.md) before opening access beyond a small personal test.

## Troubleshooting

- **503: “Set TANDEM_ACCESS_TOKEN...”**: Set the token in Vercel and reload/redeploy for paid chat; other audio endpoints should work without it.
- **503: “Rate limiting unavailable...”** on an audio route: the Upstash Redis variables are missing on Vercel or the store is unreachable. Add the Upstash integration (or fix its variables) and redeploy.
- **429: “Too many audio requests”**: the per-IP audio limit was hit; wait for `Retry-After` seconds or raise `TANDEM_AUDIO_RATE_LIMIT`.
- **413**: the upload is over the app's 18 MB cap or Vercel's 4.5 MB request-body limit; record a shorter clip.
- **48,000 vs 22,050 sample-rate error**: Verify the deployed `transcription.js` includes `resampleForBasicPitch` and refresh cached frontend assets.
- **Basic Pitch import/model unavailable**: Check CDN availability, supported browser and memory; select server fallback for basic melody/rhythm detection.
- **WORLD dependency build failure**: Check PyWorld wheel Python ABI and Vercel build output; use the pinned prebuilt distribution instead of the unsupported original package.
- **Unchanged or unnatural vocal**: Separate polish (EQ) from tune (WORLD). Ensure solo voiced singing, review detected targets and strength; no quality guarantee.
- **Chat returns 503/401**: Inspect provider and token config on server; confirm browser connection token but never expose provider credentials.
- **Blank page or 404**: Check FastAPI root/static asset routes, project framework detection, current deployment commit and service-worker cache.
