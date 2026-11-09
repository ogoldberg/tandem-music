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
- Static GitHub Pages client and separate FastAPI backend for secret management.

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

## Production deployment
1. GitHub Pages builds the frontend using `.github/workflows/pages.yml`. Under Settings → Pages set source **GitHub Actions**.
2. Deploy the FastAPI server with `render.yaml` (Render Blueprint) or another Python web host. A public HTTPS backend is needed for Android access.
3. Set on backend: `TANDEM_PROVIDER`, `TANDEM_MODEL`, `TANDEM_API_KEY` and, for OpenAI-compatible gateways, `TANDEM_BASE_URL`. Set `TANDEM_ALLOWED_ORIGINS=https://ogoldberg.github.io`.
4. Configure `TANDEM_ACCESS_TOKEN` on backend and enter the matching value in the frontend Connection panel. Never commit provider credentials or share the access token.
5. Copy the deployed backend URL into the Connection panel and press Test connection.

### Production caveats
- This is an **alpha**, not a completed or production-hardened service. Pitch/beatbox recognition is heuristic and will need calibration and real-device testing.
- The server's SQLite project endpoints are unscoped and are not used by the web app yet. For a multi-user product, implement user auth, per-user isolation, proper database and object storage, abuse protection and rate limits before use.
- Render free/ephemeral filesystems do not persist SQLite data reliably. Project files currently stay in the user's browser as downloaded JSON.
- Audio uploads are held in memory for processing and are not persisted by backend code.
- No voice AI conversation yet: text chat sends editable project state to the configured LLM.
- Local browser storage includes project draft and optional Tandem access token; do not use a shared computer when a token is configured.
- PWA manifest is included, but full installability may require appropriate PNG icons.
