# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Tandem is an experimental-alpha browser music collaborator (sing/hum/beatbox -> editable notes/drums -> AI-assisted arrangement). Read `docs/PRODUCT.md` before changing scope; `docs/ARCHITECTURE.md`, `docs/AUDIO.md`, `docs/DEVELOPMENT.md`, `docs/TESTING.md`, `docs/SECURITY.md`, `docs/ROADMAP.md` and `docs/DECISIONS.md` (ADRs) hold the details. Update the relevant doc whenever behavior or scope changes.

## Commands

Python 3.12 (`.python-version`) and Node 22+.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements-dev.txt

# Run app (UI + API on one origin, no separate frontend server or build step)
uvicorn tandem_backend:app --reload --host 127.0.0.1 --port 8000

# Tests (both run in CI: .github/workflows/tests.yml)
python -m pytest -q
python -m pytest tests/test_api.py::test_token_auth -q     # single Python test
node --test tests/transcription.test.mjs tests/polish.test.mjs
node --test --test-name-pattern="resampl" tests/transcription.test.mjs  # single Node test
```

There is no linter or formatter configured.

## Architecture

- **No build step / no framework.** `index.html` is the entire studio UI (inline script, Web Audio, piano roll, playback, WAV/MIDI export, localStorage draft). It lazy-imports `transcription.js` (ES module) which loads Spotify Basic Pitch from a CDN, resamples to 22,050 Hz (`resampleForBasicPitch`) and converts output to the project schema. It also lazy-imports `polish.js` (on-device vocal polish: band-pass EQ/gate/compression only, never pitch; a sample-exact port of the old server DSP). Both modules are imported directly by the Node tests, so keep their exports pure/testable.
- **FastAPI serves everything.** `tandem_backend.py` explicitly routes `/`, `/sw.js`, `/transcription.js`, `/polish.js`, `/manifest.webmanifest` via `FileResponse` — a new static frontend file needs its own route here (there is no static mount). `sw.js` caches same-origin GETs (not `/api/`); bump `CACHE` when stale-asset issues matter.
- **Vercel deploy:** `api/index.py` just re-exports `tandem_backend.app`; pushes to `main` deploy to production (https://tandem-music.vercel.app). `vercel.json` sets `maxDuration: 60` and excludes tests. A READY build is not evidence that tests pass or audio quality is acceptable.
- **API routes:** `/api/health`, `/api/config` (non-secret capability metadata), `/api/chat` (LLM), `/api/analyze` (heuristic autocorrelation melody + onset drums fallback), `/api/tune` (pitch correction via `world_tuning.world_tune`, WORLD vocoder from `pyworld-prebuilt`; WAV only, <=25 s).
- **Auth/spend guard:** an HTTP middleware protects only `/api/chat` with the `x-tandem-token` header vs `TANDEM_ACCESS_TOKEN`; when `VERCEL` is set and no token is configured, chat fails closed with 503. Audio routes are public but rate-limited per client IP by `RequestGuardMiddleware` (`request_guards.py`), which also caps body sizes for audio routes and `/api/chat`; on Vercel the counters live in Upstash Redis and audio routes fail closed with 503 when the store is unset or failing.
- **LLM flow:** `invoke_llm` is a hand-rolled httpx adapter for `openai-compatible` (default; also ollama), `anthropic`, and `gemini`, chosen by `TANDEM_PROVIDER`/`TANDEM_MODEL`/`TANDEM_API_KEY`/`TANDEM_BASE_URL`. The model must return JSON `{reply, actions}`; `extract_json` parses it, `normalize_actions` allowlists action types and clamps values, and melody lock (default on, ADR-004) strips `transpose`/`add_note`/`replace_notes`/melody `remove_track`. The browser applies validated actions with undo. Provider keys stay server-side only.
- **Project schema** (portable JSON, no audio embedded; `/api/chat` validates it with the `ChatProject` pydantic model, extra keys forbidden): `{"format":"tandem-project","version":1,"bpm","instrument","melody_locked","notes":[{m,t,d}],"drums":[{k,t}]}` — `m` MIDI pitch, `t`/`d` seconds, `k` in kick/snare/hat. Keep frontend, `normalize_actions`, and `/api/tune` note validation consistent with it.
- **Storage is stateless** (ADR-006): there is no server-side database; Vercel filesystems are ephemeral.
- `TANDEM_MUSIC_PROVIDER`/`TANDEM_MUSIC_MODEL` are reserved metadata only; no music-generation adapter exists.

## Testing conventions

- `tests/test_api.py` drives the ASGI app in-process with `httpx.ASGITransport` (no server needed), uses `monkeypatch` for env vars, and builds synthetic WAVs with `wav_bytes`. LLM providers are mocked — never call real paid APIs in tests.
- Node tests mock `OfflineAudioContext`.
- Docs are deliberate about "implemented vs planned" and "unverified" device QA status; don't describe features as working or verified without real evidence (see `docs/TESTING.md` release gate).
