# Tandem — Make music together

**Status: experimental alpha · Last documented: 2026-11-09**

[Try Tandem](https://tandem-music.vercel.app/) · [Repository](https://github.com/ogoldberg/tandem-music) · [GitHub Actions](https://github.com/ogoldberg/tandem-music/actions)

Tandem is a Mac- and Android-oriented, full-stack musical collaborator. Sing, hum, beatbox or describe a musical idea; turn it into editable music, work with an AI on the arrangement, and keep creative control of the original idea. The project is **not** a finished production-quality DAW, vocal editor or song-generation service. Read the [product brief](docs/PRODUCT.md) before changing scope.

## Documentation — start here

| Document | Purpose |
|---|---|
| [Product vision and user journeys](docs/PRODUCT.md) | What we are trying to achieve; experience principles, acceptance criteria, implemented vs planned |
| [Architecture](docs/ARCHITECTURE.md) | Frontend/backend boundaries, API, schema, providers, code map |
| [Audio engineering](docs/AUDIO.md) | Basic Pitch, beatboxing, WORLD vocal correction, audio quality and licensing |
| [Development and deployment](docs/DEVELOPMENT.md) | Local setup, Vercel deployment, environment variables, operations |
| [Testing and QA](docs/TESTING.md) | Unit tests, device matrix, quality evaluation, release gates |
| [Security and privacy](docs/SECURITY.md) | Secrets, spending controls, risks and production hardening |
| [Roadmap and history](docs/ROADMAP.md) | Current delivery state, fixes, sequencing and open decisions |
| [Decision log](docs/DECISIONS.md) | Why the app uses these technologies and boundaries |

The code is the source of truth for what is currently implemented; documents should be updated whenever behavior or scope changes. Avoid describing deployed/compiling software as “fully working” until real use has been tested.

## Current capabilities

- Browser microphone recording and audio import (Mac/Android browser intended; real device QA incomplete).
- Spotify Basic Pitch **on-device** humming transcription (audio resampled to 22,050 Hz); heuristic server fallback.
- Basic beatbox onset-to-kick/snare/hat detection.
- Two simple instrument tracks, rudimentary timeline editing, play/stop, undo, WAV/MIDI export.
- Save/load portable project JSON and local browser draft (recording not embedded).
- Optional text LLM collaboration with validated structured edits and melody protection; **production model credentials not configured as of last inspection**.
- EQ/gate/compression vocal polish with Natural/Studio presets, separate from tuning.
- Experimental monophonic vocal pitch correction using the open-source **WORLD** vocoder via `pyworld-prebuilt`, adjustable strength and +/- note targets.
- Python API and browser UI hosted together on Vercel.

**Still missing:** reliable pitch contour editing, proven natural vocal quality, mature instrument sounds and arrangement, generative music/audio models, voice conversation, accounts/cloud project storage, real-device end-to-end evidence, and robust public rate limiting.

## Quick start (local)

Python 3.12 and Node 22+ recommended:

```bash
git clone https://github.com/ogoldberg/tandem-music.git
cd tandem-music
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
uvicorn tandem_backend:app --reload --host 127.0.0.1 --port 8000
```

Open http://localhost:8000. Recording/transcription/voice processing need no paid LLM key. To enable text AI, configure server-side `TANDEM_PROVIDER`, `TANDEM_MODEL`, `TANDEM_API_KEY`, optionally `TANDEM_BASE_URL` and `TANDEM_ACCESS_TOKEN`. Never commit secrets.

```bash
python -m pytest -q
node --test tests/transcription.test.mjs
```

See [DEVELOPMENT.md](docs/DEVELOPMENT.md) for deployment and configuration, and [TESTING.md](docs/TESTING.md) for verification standards.

## Repository layout

`index.html` (UI), `transcription.js` (Basic Pitch), `tandem_backend.py` (FastAPI/LLM/DSP), `world_tuning.py` (active vocal pitch correction), `vocal_tuning.py` (earlier experimental reference), `api/index.py` (Vercel), `tests/` (automated checks).

## Contributions

Start with [PRODUCT.md](docs/PRODUCT.md), follow the current APIs in [ARCHITECTURE.md](docs/ARCHITECTURE.md), add tests for behavior changes and document limitations honestly. The repository is public; review write access, branch rules and third-party dependency licenses before broader collaboration.
