# Testing and release-quality checklist

Last reviewed: 2026-11-10. **Test files exist; passing CI status and real-device outcomes are not assumed.**

## Automated suites
```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
node --test tests/transcription.test.mjs tests/polish.test.mjs tests/tuning.test.mjs tests/history.test.mjs tests/versions.test.mjs

# Browser end-to-end (needs a Playwright Chromium)
python -m pip install -r requirements-e2e.txt
python -m playwright install chromium
python -m pytest e2e -q
```
GitHub Actions workflow: `.github/workflows/tests.yml` triggers all three suites (`backend`, `transcription`, `e2e`) on pushes to `main` and pull requests. Inspect https://github.com/ogoldberg/tandem-music/actions for actual run state. The Vercel build status READY means packaging succeeded, **not** that all tests passed.

Python tests cover API health/config, token access, musical action validation, bad-model responses, provider adapter mocks, audio WAV validation, sine/silence transcription, pitch correction routines, WORLD pitch-target/quantization logic (including VOX.3's note shift, Keep vibrato, the stray-frame cap, the `vibrato`/`scale` parameters of `/api/tune`, and a check that the server still matches the shared preview fixture), the VOX.1 pitch-correction benchmark (`tests/test_vocal_benchmark.py`; thresholds and metrics in [AUDIO.md](AUDIO.md#pitch-correction-benchmark-vox1)) and WORLD timing (a tuned clip keeps its length, level and note positions throughout). Node tests cover named versions (`tests/versions.test.mjs`: save/list/restore/delete, reload persistence, name and project validation, the 50-version cap, a full quota and unreadable storage), Basic Pitch event conversion and its project-melody vs vocal-target limits (with an injected Basic Pitch module), 48,000 → 22,050 Hz resampling using a mocked OfflineAudioContext, and chunked tuning (`tests/tuning.test.mjs`: chunk plan within the request caps, note targets offset to each chunk, exact reconstruction, no clicks or level gaps at seams, 429 retry), on-device polish (`tests/polish.test.mjs`: parity with the original SciPy output at 16 and 44.1 kHz, filter response, a 5-minute recording, input validation), the pitch-contour editor model (`tests/contour.test.mjs`: Basic Pitch frame timing and contour pitch, note centres, scales, snapping and scale-degree steps, fragment merging, edge resizing, and the correction preview against the server's output on `tests/fixtures/target-correction.json`), and the edit history (`tests/history.test.mjs`: undo/redo order and labels, redo cleared by a new edit, no-op edits skipped, the size cap, and `rewrite` dropping edits that became no-ops).

Browser end-to-end tests (`e2e/`, CI.2) start the real app with uvicorn and drive headless Chromium through Playwright: load `/`, import a 48 kHz WAV of three tones, transcribe with the server fallback (`/api/analyze`, expecting MIDI 69/72/76), remove a note and undo, add a note and a drum hit, play and stop, export WAV (checked non-silent), MIDI and project JSON, clear and reopen the saved project, and reload to restore the localStorage draft. A second test (EDIT.1) walks one history through Load example, removing a note, instrument and tempo changes, an AI chat reply (the real chat form and action applier, with only the `/api/chat` response fulfilled by the test because CI has no provider credentials), and Open project; it undoes and redoes all of them with the buttons, Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z and Ctrl+Y, checks that Ctrl+Z in a text field is left alone, that a new edit clears redo and a no-op edit is not recorded, then detects sung notes with on-device Basic Pitch, undoes/redoes a vocal target arrow-key step, and checks that a new recording drops the old targets from history. A third test (PERF.3) imports a 3-minute WAV of held sung-range tones and runs real on-device Basic Pitch through Detect sung notes, expecting more than 128 targets, targets past 170 s and over 100 after 60 s; it takes about 2 minutes. The fixtures launch Chromium with `--enable-unsafe-swiftshader` so GPU-less machines such as GitHub runners still get software WebGL; without it TensorFlow.js falls back to its CPU backend and the test times out at "Detecting vocal notes…". A VOX.3 test detects the three tones on device and checks one target per tone at the sung pitch, each with a confidence, then drags a target up two semitones, drags another's end edge, steps a target with the arrow keys, picks C major and snaps (the A♯/B tie goes to the sung A), steps by scale degree, deletes and undoes, and confirms the `/api/tune` request carries exactly the edited `m`/`t`/`d` targets (no confidence) and the Keep vibrato amount before tuning completes. A fourth test (EDIT.2) saves two named versions, rejects a blank name, restores one (checking notes, drums and tempo) and undoes the restore, reloads to confirm versions persist, and deletes one. An AI.3 test checks that a `tandem-token` left in `localStorage` by an older version is deleted on load, that a successful connection keeps the token in `sessionStorage` only, that it survives a reload but not a new tab, and that connecting with an empty field forgets it. A test fails on any uncaught page error or `console.error`. They do not cover Basic Pitch melody transcription, microphone recording, polish, the sound of tuned audio, or AI chat against a real model, and headless Chromium is not a substitute for the real-device matrix below. `python -m pytest` without a path runs only `tests/` (see `pytest.ini`).

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
