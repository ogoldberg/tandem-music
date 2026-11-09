# Testing and release-quality checklist

Last reviewed: 2026-11-09. **Test files exist; passing CI status and real-device outcomes are not assumed.**

## Automated suites
```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
node --test tests/transcription.test.mjs tests/polish.test.mjs tests/tuning.test.mjs
```
GitHub Actions workflow: `.github/workflows/tests.yml` triggers both suites on pushes to `main` and pull requests. Inspect https://github.com/ogoldberg/tandem-music/actions for actual run state. The Vercel build status READY means packaging succeeded, **not** that all tests passed.

Python tests cover API health/config, token access, musical action validation, bad-model responses, provider adapter mocks, audio WAV validation, sine/silence transcription, pitch correction routines and WORLD pitch-target/quantization logic. Node tests cover Basic Pitch event conversion, 48,000 → 22,050 Hz resampling using a mocked OfflineAudioContext, and chunked tuning (`tests/tuning.test.mjs`: chunk plan within the request caps, note targets offset to each chunk, exact reconstruction, no clicks or level gaps at seams, 429 retry), on-device polish (`tests/polish.test.mjs`: parity with the original SciPy output at 16 and 44.1 kHz, filter response, a 5-minute recording, input validation).

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
