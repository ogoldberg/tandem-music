# Testing and release-quality checklist

Last reviewed: 2026-11-09. **Test files exist; passing CI status and real-device outcomes are not assumed.**

## Automated suites
```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
node --test tests/transcription.test.mjs tests/polish.test.mjs tests/tuning.test.mjs

# Browser end-to-end (needs a Playwright Chromium)
python -m pip install -r requirements-e2e.txt
python -m playwright install chromium
python -m pytest e2e -q
```
GitHub Actions workflow: `.github/workflows/tests.yml` triggers all three suites (`backend`, `transcription`, `e2e`) on pushes to `main` and pull requests. Inspect https://github.com/ogoldberg/tandem-music/actions for actual run state. The Vercel build status READY means packaging succeeded, **not** that all tests passed.

Python tests cover API health/config, token access, musical action validation, bad-model responses, provider adapter mocks, audio WAV validation, sine/silence transcription, pitch correction routines, WORLD pitch-target/quantization logic, the VOX.1 pitch-correction benchmark (`tests/test_vocal_benchmark.py`; thresholds and metrics in [AUDIO.md](AUDIO.md#pitch-correction-benchmark-vox1)) and WORLD timing (a tuned clip keeps its length, level and note positions throughout). Node tests cover Basic Pitch event conversion and its project-melody vs vocal-target limits (with an injected Basic Pitch module), 48,000 → 22,050 Hz resampling using a mocked OfflineAudioContext, and chunked tuning (`tests/tuning.test.mjs`: chunk plan within the request caps, note targets offset to each chunk, exact reconstruction, no clicks or level gaps at seams, 429 retry), on-device polish (`tests/polish.test.mjs`: parity with the original SciPy output at 16 and 44.1 kHz, filter response, a 5-minute recording, input validation).

Browser end-to-end tests (`e2e/`, CI.2) start the real app with uvicorn and drive headless Chromium through Playwright: load `/`, import a 48 kHz WAV of three tones, transcribe with the server fallback (`/api/analyze`, expecting MIDI 69/72/76), remove a note and undo, add a note and a drum hit, play and stop, export WAV (checked non-silent), MIDI and project JSON, clear and reopen the saved project, and reload to restore the localStorage draft. A second test (PERF.3) imports a 3-minute WAV of held sung-range tones and runs real on-device Basic Pitch through Detect sung notes, expecting more than 128 targets, targets past 170 s and over 100 after 60 s; it takes about 2 minutes. The fixtures launch Chromium with `--enable-unsafe-swiftshader` so GPU-less machines such as GitHub runners still get software WebGL; without it TensorFlow.js falls back to its CPU backend and the test times out at "Detecting vocal notes…". A test fails on any uncaught page error or `console.error`. They do not cover Basic Pitch melody transcription, microphone recording, polish, tuning or AI chat, and headless Chromium is not a substitute for the real-device matrix below. `python -m pytest` without a path runs only `tests/` (see `pytest.ini`).

## Manual acceptance matrix
| Journey | macOS Chrome | macOS Safari | Android Chrome |
|---|---|---|---|
| Grant microphone permission and record/import | Unverified | Unverified | Unverified |
| Decode 48-kHz audio and transcribe with Basic Pitch | Unverified | Unverified | Unverified |
| Edit notes/drum hits; play both tracks | Unverified | Unverified | Unverified |
| Natural/Studio polish and original A/B | Unverified | Unverified | Unverified |
| Detect vocal notes, edit targets, WORLD tune, compare WAV | Unverified | Unverified | Unverified |
| AI edit chat with configured provider and melody lock | Unverified | Unverified | Unverified |
| Save/load JSON and export WAV/MIDI | Unverified | Unverified | Unverified |
| Offline/reconnection and malformed input handling | Unverified | Unverified | Unverified |

## Audio test requirements
Generate controlled dry solo singing samples with known MIDI pitches/timing, multiple sample rates and realistic consonants, vibrato and noise; preserve consent and privacy. Test 0% strength equivalence, clipping, silence, note overlaps and transitions. Measure pitch error, duration, loudness, artifacts and listener preference. Verify quality against real human vocals—synthetic sines alone are insufficient.

## Release gate
- CI green, no unresolved deploy/runtime errors, health endpoint 200.
- Frontend assets load; no uncaught JS errors, including sample-rate or model-import errors.
- Key user journey passes Mac and Android.
- No accidental billing exposure: unauthorized chat requests rejected; public CPU routes rate-limited before broader distribution.
- Documentation updated with behavior, limitations, model dependencies and verified outcomes.
