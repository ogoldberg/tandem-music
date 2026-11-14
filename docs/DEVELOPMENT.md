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

Open http://localhost:8000. The FastAPI server serves the browser interface and API **on the same origin**; there is no need for a second frontend development server. Browser microphone requires permission; localhost is treated as a secure context. The built-in transcription module loads the Basic Pitch bundle and model from this same server (`vendor/basic-pitch-1.0.1/`); no CDN is involved. Rebuild them with `bash tools/basic-pitch/build.sh` (needs Node and network access to the npm registry); `--check` verifies the committed files are reproducible.

If a PyWorld wheel is unsupported on your workstation's OS/architecture, investigate compatible binaries instead of silently removing tuning or calling the feature verified. On Vercel Python 3.12 the earlier `pyworld` package failed to resolve; `pyworld-prebuilt==0.3.6.post1` allowed a READY build. This is a packaging result, not proof of natural sounding correction.

## Mac app from source (DESK.1-DESK.3, AI.4, MODEL.1, SEP.1, GEN.2, TIMBRE.1)

The Mac app is the same studio in a native window (pywebview over WKWebView), with the same FastAPI app running on `127.0.0.1` behind it. It runs from source; a signed `.app` is DESK.4.

```bash
python -m pip install -r requirements-desktop.txt   # requirements.txt plus pywebview and keyring
python -m tandem_desktop
```

- The first launch picks the port (47823, or a free port if that one is taken) and saves it in `~/Library/Application Support/Tandem/desktop.json`; every later launch uses the same port. The draft, versions and recordings live in the web view's storage for `http://127.0.0.1:<port>`, so a different port would hide them. Set `TANDEM_DESKTOP_HOME=<dir>` to keep the settings file elsewhere (for trying the app without touching your real one).
- If the saved port is busy, the launcher stops and says Tandem may already be running; it does not move to another port. A damaged `desktop.json` is reported, not replaced.
- The microphone is granted to the app's own page without a WebKit prompt (see SECURITY.md). Running from source, macOS asks for microphone access on behalf of the app that started Python (for example Terminal), once.
- Closing the window stops the server. Export WAV/MIDI and Save project open the native Save panel.
- **Save to folder…** saves the project as a folder (`project.json`, `tandem.json` and its recordings as WAV) wherever you pick, such as an iCloud Drive or Dropbox folder; **Open folder…** opens one, with its recordings (DESK.3). The folder's name is the project's name. These two buttons are only in the Mac app's window.
- **Your AI** (under Compose together, only in the Mac app's window) uses your own AI account (AI.4): choose the provider, name the model as the provider lists it, paste your key and Save. The key goes to your login Keychain (item `Tandem AI key`), the provider and model to `ai.json` next to `desktop.json`. Ollama needs no key; another OpenAI-compatible server (LM Studio, vLLM, a gateway) needs its address and, if it asks for one, a key. With nothing saved, the `TANDEM_*` environment variables still configure chat.
- Large audio models (MODEL.1) are downloaded on request into `models/` next to `desktop.json`, checked against their pinned SHA-256, and run as background jobs with progress and cancel. Their Python packages are in `requirements-models.txt` (`python -m pip install -r requirements-models.txt`), installed only for the Mac app.
- **Separate voice from music** (SEP.1, next to Correct singing pitch, only in the Mac app's window) splits the recording into the voice and the music with Demucs' htdemucs model. It needs `python -m pip install -r requirements-models.txt` (PyTorch, Demucs); the first press downloads the model (84 MB, from Hugging Face, checked against its SHA-256). It runs on the Mac's GPU (Metal): a 3-minute song took 24 s on an M5 (263 s on its CPU). Afterwards ▶ Vocal and ▶ Music play the parts, Transcribe, Polish and Tune work on the voice, ▶ Original still plays the full recording, and Use the full recording goes back to it.
- **Generate band** (GEN.2, the Band track under Harmony, only in the Mac app's window) plays up to 30 s of a backing band that follows the melody notes or the recording, in the style you describe, with Meta's MusicGen-Melody. It needs `requirements-models.txt` (PyTorch, transformers); the first press says the download's size (6.23 GB) and the weights' licence (CC-BY-NC 4.0, non-commercial use only) and a second press downloads it. 10 s of band takes about a minute on Metal. The band can be played alone, muted, removed and generated again, all undoable.
- **Play my voice on it** (TIMBRE.1, the Voice as instrument track under Band, only in the Mac app's window) plays the tuned voice, else the take, as a soprano saxophone, an electric guitar or a church organ with a RAVE model. It needs `requirements-models.txt` (PyTorch); the first press for an instrument says its download's size (121-164 MB) and the models' licence (CC-BY-NC 4.0, non-commercial use only) and a second press downloads it. A minute of voice takes about ten seconds. The result can be played alone, muted, removed and made again, all undoable; the original recording stays.
- `/api/config` reports `"runtime": "desktop"` in the Mac app and `"web"` elsewhere. The Mac app's own window has no rate limits and tunes or analyses a take up to 10 minutes in one request (DESK.2; `/api/config` reports the limits under `limits`). Its server answers `/api/` only with the per-launch secret the launcher gives its window, so opening `http://127.0.0.1:<port>/` in an ordinary browser shows the studio but its server features (analyse, tune, chat) get 403; use the window.

## Tests

```bash
python -m pytest -q
node --test tests/transcription.test.mjs tests/polish.test.mjs tests/tuning.test.mjs tests/history.test.mjs tests/versions.test.mjs tests/contour.test.mjs tests/groove.test.mjs tests/voices.test.mjs tests/harmony.test.mjs tests/phrases.test.mjs tests/storage.test.mjs tests/recordings.test.mjs tests/samples.test.mjs tests/ideas.test.mjs tests/bundle.test.mjs tests/daw.test.mjs tests/notation.test.mjs tests/dawproject.test.mjs tests/noteedit.test.mjs tests/guide.test.mjs tests/playhead.test.mjs tests/evolution.test.mjs
# Browser end-to-end, once: pip install -r requirements-e2e.txt && python -m playwright install chromium
python -m pytest e2e -q
```

The GitHub Actions test workflow is `.github/workflows/tests.yml`. See [TESTING.md](TESTING.md) for the test matrix, real-device requirements, and release gates. Do not infer passing tests merely from a successful Vercel build.

## Rebuilding the instrument samples

The recorded instrument samples (SND.1) in `vendor/gm-samples-1/` are generated, not edited by hand. You only need to rebuild them to change the sample set.

```bash
brew install fluid-synth lame
python tools/gm-samples/build.py          # renders the samples into vendor/gm-samples-1/
python tools/gm-samples/build.py --check  # rebuilds in a temp directory and diffs against the committed files
```

The script downloads the SoundFont package and checks its SHA-256 before use. The files are served as immutable, so a changed sample set must move to a new versioned directory such as `gm-samples-2` (the build `dest`, the vendor route, `samples.js` and the tests), or browsers will mix old and new files. Bump the `CACHE` name in `sw.js` too, and the `VENDOR` cache name, so browsers drop the old directory's cached files. See [SECURITY.md](SECURITY.md) for the license and hashes.

The app icons (MOB.2) are drawn in `icons/icon.svg` (rounded, for manifest purpose "any") and `icons/icon-maskable.svg` (full bleed, notes inside the maskable safe zone). After changing either, render the PNGs with headless Chromium and commit them:

```bash
python tools/icons/build.py   # needs requirements-e2e.txt and `python -m playwright install chromium`
```

It writes `icons/icon-192.png`, `icons/icon-512.png`, `icons/icon-maskable-512.png` and `icons/apple-touch-icon.png`. A new icon file also needs adding to `ICON_FILES` in `tandem_backend.py` and to the precache list in `sw.js` (bump `CACHE`).

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

To generate a long random access token on macOS: `openssl rand -hex 32`. Store it in Vercel Production environment variables and enter the same token in the browser's **Connection** panel. The browser keeps the token only for that tab (sessionStorage), so you re-enter it in each new tab. Redeploy after environment changes. Do not paste credentials into issues, chat, screenshots or source.

### Sanity check after deploy

1. Inspect Vercel build logs and ensure the latest `main` commit is READY.
2. Visit `/`, `/transcription.js`, `/polish.js`, `/tuning.js`, `/api/health`, `/api/config`; verify HTTP 200 and current UI content.
3. Verify unconfigured `/api/chat` fails safely, but free `/api/analyze` and `/api/tune` remain accessible.
4. Test record/import → transcription → edit → export in a real browser. Test vocal tuning on a short clean recording and on one longer than 90 s (tuned in chunks), and listen to original/tuned audio, especially around 15 s, 30 s, 45 s... where chunks join.
5. Only after configuring a provider, verify a small authenticated text edit and that melody-lock behavior is preserved.
6. Review GitHub Actions results, browser console, Vercel runtime errors and external model usage/cost.

Do not treat an HTTP 200 response from the root or READY build as validation of pitch accuracy or audio quality.

## Persistence and media

Projects are local JSON exports, and the draft and named versions are kept in the browser's IndexedDB (`storage.js`, STORE.2a), not cloud-saved (ADR-011). `/api/tune` and other audio routes accept in-memory uploads; Vercel functions have ephemeral filesystems. Roaming between devices through a folder or bucket the user brings (STORE.2b/c) is parked by ADR-012; the Mac app saves projects as files in a folder the user picks, which can be synced (DESK.3). There is no Tandem server for it.

## Cost and security

The provider key never belongs in browser JavaScript. Vercel production refuses `/api/chat` if `TANDEM_ACCESS_TOKEN` is unset. This prevents accidental public use of a paid model; the token is shared. Audio-processing routes are rate-limited per client IP (20 requests per 60 s by default) through Upstash Redis and fail closed with 503 on Vercel when the store is not configured; bodies are capped at 18 MB (audio) and 256 KB (chat). Full limits are in [SECURITY.md](SECURITY.md#request-limits-sec1). Configure provider budget limits and review [SECURITY.md](SECURITY.md) before opening access beyond a small personal test.

## Troubleshooting

- **503: “Set TANDEM_ACCESS_TOKEN...”**: Set the token in Vercel and reload/redeploy for paid chat; other audio endpoints should work without it.
- **503: “Rate limiting unavailable...”** on an audio route: the Upstash Redis variables are missing on Vercel or the store is unreachable. Add the Upstash integration (or fix its variables) and redeploy.
- **429: “Too many audio requests”**: the per-IP audio limit was hit; wait for `Retry-After` seconds or raise `TANDEM_AUDIO_RATE_LIMIT`.
- **413**: the upload is over the app's 18 MB cap or Vercel's 4.5 MB request-body limit; record a shorter clip.
- **48,000 vs 22,050 sample-rate error**: Verify the deployed `transcription.js` includes `resampleForBasicPitch` and refresh cached frontend assets.
- **Basic Pitch import/model unavailable**: Check that `/vendor/basic-pitch-1.0.1/basic-pitch.mjs` and `/model/model.json` load (a 404 means the route or the deployed files are missing), then supported browser and memory; select server fallback for basic melody/rhythm detection.
- **WORLD dependency build failure**: Check PyWorld wheel Python ABI and Vercel build output; use the pinned prebuilt distribution instead of the unsupported original package.
- **Unchanged or unnatural vocal**: Separate polish (EQ) from tune (WORLD). Ensure solo voiced singing, review detected targets and strength; no quality guarantee.
- **Chat returns 503/401**: Inspect provider and token config on server; confirm browser connection token but never expose provider credentials.
- **Blank page or 404**: Check FastAPI root/static asset routes, project framework detection, current deployment commit and service-worker cache.
