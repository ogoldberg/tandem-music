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

## Capability checklist

A checked box means the feature is **implemented in code**, not that it has been verified on real devices or meets a quality bar. Unchecked items point to their task IDs in the [roadmap task backlog](docs/ROADMAP.md#task-backlog), which is the authoritative work list.

**Implemented**

- [x] Browser microphone recording and audio import (Mac/Android browser intended; real device QA incomplete).
- [x] Spotify Basic Pitch **on-device** humming transcription (audio resampled to 22,050 Hz); heuristic server fallback.
- [x] Basic beatbox onset-to-kick/snare/hat detection.
- [x] Two simple instrument tracks, rudimentary timeline editing, play/stop, undo, WAV/MIDI export.
- [x] Save/load portable project JSON; the draft and named versions are kept on the device in IndexedDB (STORE.2a; recordings are not saved yet).
- [x] Optional text LLM collaboration with validated structured edits and melody protection; **production model credentials not configured as of last inspection**.
- [x] EQ/gate/compression vocal polish with Natural/Studio presets, separate from tuning; runs on the device, with no length cap.
- [x] Experimental monophonic vocal pitch correction using the open-source **WORLD** vocoder via `pyworld-prebuilt`, adjustable strength and +/- note targets; long recordings are tuned in 16 s chunks, so there is no length cap; on-device note-target detection also covers the whole recording (PERF.3).
- [x] Python API and browser UI hosted together on Vercel.
- [x] Automated Python and Node test suites passing in GitHub Actions (verified 2026-11-09).

**Still missing**

- [x] Browser end-to-end tests in headless Chromium run in GitHub Actions (CI.2; import, server transcription, edit/undo, play, export, save/reload).
- [ ] Real-device evidence on Mac and Android (QA.1).
- [x] Per-IP rate limiting of the audio routes (shared Upstash Redis store) and input resource limits (SEC.1).
- [ ] Proven natural vocal quality (VOX.1, VOX.2).
- [x] Undo/redo history across manual, AI, project-load and vocal-target edits (EDIT.1; per session).
- [x] Named project versions saved in this browser: save, list, restore (undoable) and delete (EDIT.2).
- [x] Detect tempo from the notes and drums, and quantize to a 1/4, 1/8 or 1/16 grid with swing and strength (ARR.1a).
- [x] Pitch-contour editor: drag, resize and step note targets over the sung pitch line, key/scale snapping, keep vibrato (VOX.3; not yet judged by ear, VOX.2).
- [ ] AI edits with your own key, kept in the macOS Keychain by the Mac app (AI.4), verified with a real model (AI.2); the hosted model on Vercel (AI.1) is optional.
- [x] Richer instrument voices, generated chord/bass harmony and phrase move/copy/transpose (ARR.1; not yet judged by ear on real devices).
- [x] Local-first storage with no accounts (ADR-011): the draft, versions and recordings are kept on the device (STORE.2a; not yet tried in Safari or on real devices).
- [~] Sampled instruments: recorded General MIDI samples for melody, harmony and drums, with the synthesized voices as a fallback (SND.1; not yet judged by ear on real speakers).
- [ ] A Mac app running the same studio with its own local backend: no hosted limits, projects as files (DESK.1-DESK.4, ADR-012).
- [~] Stems and multi-track MIDI for any DAW (EXP.1; not yet checked by importing into GarageBand or Logic).
- [ ] Local AI audio models in the Mac app: voice separation (SEP.1), a backing band from your hum (GEN.2), voice to instrument (TIMBRE.1).
- [ ] Hosted generative music providers (GEN.1).
- [ ] Voice conversation (SPEECH.1).

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
node --test tests/transcription.test.mjs tests/polish.test.mjs tests/tuning.test.mjs tests/history.test.mjs tests/versions.test.mjs tests/contour.test.mjs tests/groove.test.mjs
```

See [DEVELOPMENT.md](docs/DEVELOPMENT.md) for deployment and configuration, and [TESTING.md](docs/TESTING.md) for verification standards.

## Repository layout

`index.html` (UI), `transcription.js` (Basic Pitch), `polish.js` (on-device polish), `tuning.js` (chunked pitch correction), `history.js` (undo/redo), `versions.js` (named versions), `groove.js` (tempo detection and quantize), `tandem_backend.py` (FastAPI/LLM/DSP), `world_tuning.py` (active vocal pitch correction), `api/index.py` (Vercel), `tests/` (automated checks).

## Contributions

Start with [PRODUCT.md](docs/PRODUCT.md), follow the current APIs in [ARCHITECTURE.md](docs/ARCHITECTURE.md), add tests for behavior changes and document limitations honestly. The repository is public; review write access, branch rules and third-party dependency licenses before broader collaboration.
