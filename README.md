# Tandem — Make music together

Tandem is an experimental full-stack, provider-agnostic, browser-based AI composition workspace for Mac and Android.

## Features
- Record/import humming, beatboxing and singing in browser.
- On-device Spotify Basic Pitch 1.0.1 neural transcription for melodies (lazy-loaded from external model/CDN), with server heuristic fallback; server beatbox onset analysis. Editable note timeline, tempo and instruments.
- Two-track synthesis and playback; export arrangement as MIDI or WAV.
- AI conversational editing of a portable note-and-drum project. AI replies are validated structured actions, never executable code. Melody lock is enabled by default to reject AI edits that change your notes.
- Server-side basic vocal polishing (band-pass filter, gate and compression). **Automatic pitch correction is not implemented**.
- Portable project JSON save/load and undo.
- OpenAI-compatible chat completions, Anthropic Messages API, Gemini generateContent.
- Single-origin Vercel frontend and FastAPI backend with secure server-side AI credentials.

## Run the backend locally
Python 3.11+:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export TANDEM_PROVIDER=openai-compatible
export TANDEM_MODEL=gpt-4.1-mini
export TANDEM_API_KEY=your-key-here
uvicorn tandem_backend:app --reload --port 8001
```
For OpenAI-compatible models, override `TANDEM_BASE_URL` (examples: OpenRouter, LM Studio, vLLM, Ollama `http://localhost:11434/v1`). For Anthropic set `TANDEM_PROVIDER=anthropic`, and for Gemini set `TANDEM_PROVIDER=gemini`. Choose an appropriate model name and key.

For local browser testing, run `python -m http.server 8000` in another terminal and visit `http://localhost:8000`. The UI's Connection panel should point to `http://localhost:8001` for local testing.

## Deploy on Vercel

1. Import [ogoldberg/tandem-music](https://github.com/ogoldberg/tandem-music) at https://vercel.com/new.
2. Choose **Other** framework (no frontend build), repository root, and the default deploy settings. Python 3.12 is pinned in `.python-version`.
3. In Vercel Project → Settings → Environment Variables, set `TANDEM_PROVIDER`, `TANDEM_MODEL`, and `TANDEM_API_KEY`. Supported providers: `openai-compatible` (default), `anthropic`, `gemini`, `ollama`; compatible proxies may also use `TANDEM_BASE_URL`.
4. Optionally set `TANDEM_ACCESS_TOKEN` to restrict API access. This is a shared bearer secret for personal testing, **not** per-user authentication. Enter it in the app's Connection panel.
5. Redeploy after changing environment variables; verify `/api/health` and the site root, then record and transcribe a short sound.
6. Monitor Vercel function usage and AI usage; stay within your plan's quotas. Hobby is for personal/non-commercial use.

### Current limitations

- Audio-processing via Python NumPy/SciPy runs inside a Vercel Function; deployment is subject to the Python bundle and request-body limits. Basic Pitch downloads its JavaScript model from a public CDN on first use, so it needs a network connection, and browser/memory compatibility still requires device testing.
- Project data stays in your browser or downloaded JSON. Server-side SQLite is intentionally **not** deployed on ephemeral serverless infrastructure.
- For production and multi-user access, add proper authentication, project storage, abuse prevention, rate limiting and privacy protections.
- Automatic singing pitch correction is not yet implemented. The vocal polish endpoint filters and compresses audio.
- Humming and beatbox recognition are heuristic and need real-device testing.
- Conversations are text-based; microphone recordings are analyzed by DSP, not sent to the LLM as voice messages.
- Never put provider API keys in the frontend or repository.

## Model capability boundaries

`GET /api/config` reports distinct capabilities for conversation, on-device transcription, rhythm recognition, vocal polish, and a reserved music-generation slot. Music generation is currently disabled; setting `TANDEM_MUSIC_PROVIDER` and `TANDEM_MUSIC_MODEL` alone **does not activate a provider integration**. For the LLM, use server environment variables; do not check credentials into Git. Spotify Basic Pitch is Apache-2.0 licensed (https://github.com/spotify/basic-pitch-ts).

## Tests

- Backend: `python -m pytest -q`
- Browser transcription adapter: `node --test tests/transcription.test.mjs` (Node 22+)
- GitHub Actions runs both suites on pushes and pull requests. Browser microphone and Basic Pitch model-loading tests still need real Chrome/Safari/Android validation.

## Open-source vocal tuning (WORLD)

Tandem uses [WORLD](https://github.com/mmorise/World) via the Python 3.12 compatible `pyworld-prebuilt==0.3.6.post1` package, retaining separate pitch (F0), spectral-envelope and aperiodicity representations. The `/api/tune` endpoint accepts a WAV file, `strength=0..1`, and optional `notes_json` (the user's manually edited targets). Detect sung notes in the browser and adjust target pitches using the −/+ buttons before correction. The original file remains unchanged.

WORLD is an open-source vocoder, not Melodyne or Antares Auto-Tune. This first integration is **experimental and monophonic**: it is not intended for background mixes or complex polyphony, and may produce artifacts, especially on consonants and vibrato. For no edited targets it quantizes each voiced F0 frame to the nearest chromatic note; user-edited targets override this within their time ranges. The server limits inputs to 25 seconds for processing safety. The UI currently uses the browser Basic Pitch detector to create editable note targets.

Automated tests cover F0 quantization, bypass, scale constraints, manual targets, and the original pitch-correction routines. A deployment-ready build is not an audio-quality evaluation; test using dry human singing on Android and Mac before claiming production-ready vocal correction.
