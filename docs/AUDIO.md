# Audio engineering: transcription and tuning

Last reviewed: 2026-11-09.

## Record and transcribe
Browser MediaRecorder may record at 44,100 or 48,000 Hz. Tandem decodes audio, uses Web Audio's offline resampler to meet Basic Pitch's **22,050 Hz** input requirement, then maps note detections to portable MIDI pitches and second-based timestamps. A user encountered the original 48,000 vs 22,050 sample-rate failure; a regression test covers it.

For beatboxing, server analysis uses approximate energy peaks and spectral centroid to classify kicks/snares/hats. This is **not** an accurate trained classifier yet. Note confidence and correction UI require improvement.

## Vocal polish vs vocal tuning
Polish (`polish.js`, on device since PERF.1): band-pass EQ, soft gating, compression and makeup gain (Natural/Studio), run in the browser on the decoded recording, so audio is not uploaded and there is no length cap beyond the device's memory. It is a sample-exact port of the former `/api/polish` SciPy DSP (`tests/fixtures/make_polish_fixture.py` keeps that reference). It can affect tone/level but does not fix singing pitch.

Tune (`/api/tune`): **WORLD/PyWorld** vocoder. Separate F0 estimation, spectral envelope and aperiodicity enable resynthesis with changed F0 while approximately retaining vowel/formant character. Corrected audio is a new WAV; the original is unchanged. Analysis and synthesis share one 10 ms frame period (`FRAME_PERIOD_MS`); before November 2026 synthesis used pyworld's 5 ms default, so tuned clips played at double speed and the second half was silent.

The browser can call Basic Pitch to detect vocal note targets and present +/- semitone controls. The WORLD endpoint supports strength 0..1 and optional `notes_json`. Without targets it snaps voiced frames toward nearest semitone. Each request is limited to a 25-second clip; the browser (`tuning.js`) tunes longer recordings in 16 s chunks that overlap by 1 s, offsets each chunk's note targets to its own start time (when targets are set, a chunk with none keeps its original audio rather than being snapped, matching how audio outside the targets is left alone within a request), and joins the results with a 40 ms linear crossfade at the quietest point of each overlap. WORLD restarts each chunk at its own phase, so a long crossfade partly cancels; the short seam keeps any dip brief. A recording tunes in about one request per 15 s, so long takes can wait on the per-IP rate limit, which the browser retries after `Retry-After`. It does not separate voice from background music or reliably edit polyphonic sources.

### Known artifacts
- Pitch-detection errors, wrong octaves and note boundaries.
- Consonant, breath, transient and unvoiced regions; vibrato flattening.
- Audible timbre changes and mechanical artifacts even with formant-aware synthesis.
- Short notes and blended pitches may not produce reliable targets.
- The note UI is a list of detected targets—not a Melodyne-style pitch curve.

## Research/evaluation plan
Build a consented test set of dry solo voices across ranges, devices, vowels, consonants, vibrato, quiet notes, slides and sample rates (16/22.05/44.1/48 kHz). Include known target MIDI and timings, silence and noisy negatives. Measure note error in cents, preservation of length, spectral artifacts, clicks and loudness. Conduct blinded listening tests against original and reference correction. Never claim “professional quality” merely because a deployment succeeds or unit tests pass.

## Open-source dependencies and licensing
- [Basic Pitch](https://github.com/spotify/basic-pitch-ts): audio-to-MIDI in JS.
- [WORLD](https://github.com/mmorise/World): open-source vocoder; used via `pyworld-prebuilt` Python package. Review redistributed binary and dependency licenses.
- [Rubber Band](https://github.com/breakfastquay/rubberband) and [x42 Auto Tune](https://www.x42-plugins.com/x42/x42-autotune): alternative research references, **not incorporated**.
- Melodyne and Antares are commercial UX/quality references, **not dependencies**.

Avoid copying proprietary code or bypassing license controls.
