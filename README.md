# Tandem — Make music together

Tandem is an experimental full-stack, provider-agnostic, browser-based AI composition workspace for Mac and Android.

## Features
- Record/import humming, beatboxing and singing in browser.
- API transcription from 16-bit PCM WAV into notes and drum hits; editable piano roll, tempo and instruments.
- Two-track synthesis and playback; export arrangement as MIDI or WAV.
- AI conversational editing of a portable note-and-drum project. AI replies are validated structured actions, never executable code.
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
uvicorn server:app --reload --port 8001
```
For OpenAI-compatible models, override `TANDEM_BASE_URL` (examples: OpenRouter, LM Studio, vLLM, Ollama `http://localhost:11434/v1`). For Anthropic set `TANDEM_PROVIDER=anthropic`, and for Gemini set `TANDEM_PROVIDER=gemini`. Choose an appropriate model name and key.

For local browser testing, run `python -m http.server 8000` in another terminal and visit `http://localhost:8000`. The UI's Connection panel should point to `http://localhost:8001`.

## Deploy on Vercel

1. Import [ogoldberg/tandem-music](https://github.com/ogoldberg/tandem-music) at https://vercel.com/new.
2. Choose **Other** framework (no frontend build), repository root, and the default deploy settings. Python 3.12 is pinned in `.python-version`.
3. In Vercel Project → Settings → Environment Variables, set `TANDEM_PROVIDER`, `TANDEM_MODEL`, and `TANDEM_API_KEY`. Supported providers: `openai-compatible` (default), `anthropic`, `gemini`, `ollama`; compatible proxies may also use `TANDEM_BASE_URL`.
4. Optionally set `TANDEM_ACCESS_TOKEN` to restrict API access. This is a shared bearer secret for personal testing, **not** per-user authentication. Enter it in the app's Connection panel.
5. Redeploy after changing environment variables; verify `/api/health` and the site root, then record and transcribe a short sound.
6. Monitor Vercel function usage and AI usage; stay within your plan's quotas. Hobby is for personal/non-commercial use.

### Current limitations

- Audio-processing via Python NumPy/SciPy runs inside a Vercel Function; deployment is subject to the Python bundle and request-body limits.
- Project data stays in your browser or downloaded JSON. Server-side SQLite is intentionally **not** deployed on ephemeral serverless infrastructure.
- For production and multi-user access, add proper authentication, project storage, abuse prevention, rate limiting and privacy protections.
- Automatic singing pitch correction is not yet implemented. The vocal polish endpoint filters and compresses audio.
- Humming and beatbox recognition are heuristic and need real-device testing.
- Conversations are text-based; microphone recordings are analyzed by DSP, not sent to the LLM as voice messages.
- Never put provider API keys in the frontend or repository.
