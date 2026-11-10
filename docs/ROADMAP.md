# Roadmap and change history

Last reviewed: 2026-11-10. This is a prioritized working plan, not a delivery promise.

## Milestones and status
| Status | Milestone | Notes |
|---|---|---|
| Implemented, needs device QA | Responsive browser studio | Mac/Android browser targets, recording/import, playback |
| Implemented, experimental | Humming-to-note transcription | Basic Pitch + 22,050 Hz resampling, fallback heuristic |
| Implemented, experimental | Beatbox-to-drum events | Onset and centroid heuristics |
| Implemented, limited | Two-track arrangement | Basic synthesized instruments/drums and simple editing |
| Implemented, limited | WAV/MIDI/JSON export | No embedded recorded audio in JSON |
| Backend implemented, not live-configured | Model-agnostic text conversation | OpenAI-compatible, Anthropic, Gemini; production AI credentials absent on last inspection |
| Implemented, experimental | EQ/dynamics vocal polish | Not tuning |
| Implemented, experimental | Vocal pitch correction | WORLD/PyWorld; semi-automatic note targets; not Melodyne-level |
| Planned | Reliable vocal contour editor | Drag notes, retain vibrato, key/scale UI, confidence |
| Planned | Better vocal quality | Quality benchmark, artifact handling, phoneme preservation |
| Planned | Better arrangement | Richer instruments, harmony, swing, phrase-aware editing |
| Planned | Music generation | Capability-specific adapters for externally hosted or self-hosted audio models |
| Planned | Conversational speech | Spoken chat and audio intent alongside text |
| Planned | Privacy/storage/auth | Accounts, durable projects/recordings, rate limiting and safe spending controls |
| Planned | Production QA | Android/Mac e2e recording and audio quality evaluations |

## Task backlog

This is the working task list, in strategic order: protect the deployment, prove the core loop works on real devices, turn on the AI half of the product, then build a safety net before the larger editor work. Loopkit's `/next-task` reads it (see `.agent-workflow.yml`). Format: `- [ ]` pending, `- [~]` in progress, `- [x]` done; the bold token is the task ID. `*(HUMAN)*` marks work that needs the owner: real devices, listening judgement, credentials, account settings or product decisions. Mark a task `[x]` only with evidence (CI run, recorded device result, merged PR). Real-device results (QA.1) may reorder the vocal and arrangement work.

### 1. Protect the deployment
- [x] **CI.1** Confirm the GitHub Actions Python and Node suites pass on `main`
  - Verified 2026-11-09: run 42598992550 (`Tests`, success).
- [ ] **SEC.4** *(HUMAN)* Configure GitHub branch protection on `main`: required status checks (`backend`, `transcription`, `loopkit-review`), no force pushes, no direct pushes
  - Loopkit merges approved PRs without a human click, so `main` must refuse anything that has not passed CI and review.
  - **Acceptance:** ruleset verified in GitHub settings and recorded in `docs/SECURITY.md`.
- [x] **SEC.1** Rate-limit and resource-limit the public CPU routes `/api/analyze`, `/api/polish` and `/api/tune`
  - Must work on serverless Vercel, where in-process memory does not persist between instances: use a shared store or Vercel's firewall rate limiting, and document the choice and where state lives.
  - Also review memory/CPU use under malicious or unexpected inputs (oversized, malformed, long, many-channel WAVs) and make sure no route reads unbounded input.
  - Tighten the `/api/chat` project schema validation (typed, bounded `notes`/`drums`/`bpm`/`instrument` instead of a free-form dict) before paid AI is enabled in AI.1.
  - **Acceptance:** tests prove requests over the limit get 429, each rejected input class is refused, and malformed `/api/chat` projects get 422; limits documented in `docs/SECURITY.md` and `docs/DEVELOPMENT.md`.

### 2. Prove the core loop
- [x] **PERF.1** Move vocal polish into the browser so recordings are not uploaded and have no 90 s / 4.5 MB cap
  - Port the `/api/polish` SciPy DSP to `polish.js` and remove the server route.
  - **Acceptance:** Node tests show sample parity with the SciPy reference and a 5-minute recording processes; a 120 s stereo recording polishes in a real browser with no API call.
- [x] **PERF.2** Remove the length cap on pitch correction by tuning long recordings in chunks
  - The browser splits the recording into overlapping chunks of about 15 s, each under Vercel's 4.5 MB body limit, sends them to `/api/tune` and stitches the results with short crossfades. The server stays stateless.
  - **Acceptance:** a recording longer than 90 s tunes end to end; tests show chunk boundaries add no clicks or gaps (crossfade continuity) and that each chunk's detected/edited note targets are offset to the chunk's start time.
- [x] **PERF.3** Detect vocal note targets on recordings of any length
  - Vocal note detection (Basic Pitch in `transcription.js`) refuses recordings over 60 s and keeps only the first 128 notes, so on long takes the note editor covers only the start. Since PERF.2 the server limit of 128 targets applies per chunk, not per recording.
  - **Acceptance:** a 3-minute vocal yields note targets across its whole length in a real browser; melody transcription into the project keeps whatever cap the project schema and `/api/chat` need.
- [ ] **QA.1** *(HUMAN)* Run the manual acceptance matrix in `docs/TESTING.md` on macOS Chrome, macOS Safari and Android Chrome
  - **Acceptance:** each matrix cell in `docs/TESTING.md` is updated from "Unverified" to a dated pass/fail, with notes and quality ratings for transcription and tuning.
- [x] **DEV.1** Remove dead code: the unused SQLite `db()` helper and `TANDEM_DATABASE`, and the unused `vocal_tuning.py` import and module with its `tests/test_vocal_tuning.py`
  - **Acceptance:** remaining tests pass (and `tests/test_api.py` no longer patches `server.DB`); `README.md`, `CLAUDE.md`, `docs/ARCHITECTURE.md` and `docs/AUDIO.md` no longer describe them as present.

### 3. Turn on AI collaboration
- [ ] **AI.1** *(HUMAN)* Choose the text provider and model; set `TANDEM_PROVIDER`, `TANDEM_MODEL`, `TANDEM_API_KEY` and `TANDEM_ACCESS_TOKEN` in Vercel with provider budget caps and alerts
  - **Depends:** SEC.1
  - Follow "Before enabling paid AI" in `docs/SECURITY.md`.
- [ ] **AI.2** Verify structured AI edits end to end on production
  - **Depends:** AI.1
  - **Acceptance:** a small authenticated edit succeeds on the deployed app; melody lock still blocks melody changes; result recorded in `docs/TESTING.md`.
- [ ] **AI.3** Replace the localStorage access token with a safer session model
  - **Acceptance:** the shared token is no longer stored in `localStorage`; `docs/SECURITY.md` updated.

### 4. Safety net before larger UI work
- [x] **CI.2** Add browser end-to-end tests that run in CI
  - Headless browser (e.g. Playwright) against the real FastAPI app: load `/`, import a WAV fixture, transcribe with the server fallback, edit a note, undo, play, export WAV/MIDI/JSON, save and reload a project.
  - **Acceptance:** runs in `.github/workflows/tests.yml`; fails on any uncaught page error or console error; covers the 48 kHz decode path.
- [x] **SEC.3** Add integrity checks to, or self-host, the Basic Pitch JS and model
  - `transcription.js` already pins `basic-pitch@1.0.1`; what is missing is integrity verification, so a changed or unavailable CDN file can silently break or tamper with transcription.
  - **Acceptance:** assets verified by hash or served from this app; transcription still works; supply-chain note in `docs/SECURITY.md` updated.

### 5. Vocal quality and editing
- [x] **VOX.1** Build an automated vocal pitch-correction benchmark
  - Generate fixtures with known MIDI pitches and timing at several sample rates, with vibrato, noise and transitions; measure pitch error, duration and loudness change of `/api/tune`, and 0%-strength equivalence.
  - **Acceptance:** runs under `pytest`; records metrics; thresholds documented in `docs/AUDIO.md`.
- [ ] **VOX.2** *(HUMAN)* Blinded A/B listening test of WORLD tuning on real singing
  - **Depends:** VOX.1
  - **Acceptance:** recordings used with consent; results and artifacts noted in `docs/AUDIO.md`.
- [x] **EDIT.1** Proper undo/redo
  - Replace ad hoc note-list edits with an edit history covering manual edits, AI actions and tuning targets.
  - Done: `history.js` (bounded, labelled undo/redo with no-op detection) records every project and vocal-target edit; Redo button and keyboard shortcuts; Node unit tests and a browser test across manual, AI, load and vocal-target edits. History is per page session; persistent named project versions moved to EDIT.2.
  - **Depends:** CI.2
  - **Acceptance:** undo/redo works across all edit types; tests cover history behavior.
- [x] **EDIT.2** Project versioning: named, persisted versions of a project
  - Done: `versions.js` keeps up to 50 named versions in localStorage; the Versions panel saves, lists, restores (one undoable edit) and deletes them. Covered by Node unit tests and a browser test that includes a reload. Versions are per browser profile, not synced.
  - **Depends:** EDIT.1
  - **Acceptance:** a user can save, list and restore named versions; they survive reload and are covered by unit and browser tests.
- [x] **VOX.3** Continuous pitch-contour editor
  - Replace the +/- target note list with a visual contour: drag notes, keep vibrato, key/scale selection, per-note confidence.
  - Done: `contour.js` and the editor in `index.html` draw the sung pitch line from Basic Pitch's contour and a live preview of the corrected line. Targets are dragged for pitch, resized at their edges, stepped with the arrow keys and deleted. A key/scale selection drives drags, steps, Snap notes to key and untargeted tuning. Keep vibrato is sent to `/api/tune` as `vibrato`. Vibrato fragments are merged into whole notes, and confidence shows on each target. Every change goes through the EDIT.1 history. Covered by Python, Node and browser tests (ADR-008); real-voice listening stays with VOX.2.
  - **Depends:** VOX.1, EDIT.1
  - **Acceptance:** edited targets drive `/api/tune` and go through the EDIT.1 history; covered by unit tests and the CI.2 browser tests.

### 6. Later
- [ ] **ARR.1** Better arrangement: richer instruments, harmony, swing and phrase-aware editing
  - **Depends:** CI.2
- [ ] **STORE.1** *(HUMAN)* Decide the account model and cloud storage for projects and recordings
- [ ] **STORE.2** Accounts, durable project/recording storage and per-user quotas
  - **Depends:** STORE.1, SEC.1
- [ ] **GEN.1** Optional generative music provider adapter, with explicit provenance
  - **Depends:** SEC.1, AI.2
- [ ] **SPEECH.1** Conversational speech: spoken chat and audio intent alongside text
  - **Depends:** AI.2

## History of decisions and fixes (2026-11-08 to 2026-11-09)
- Initial idea came from Akai MPC openness, but **no MPC hardware is needed** for Tandem.
- A basic sampler was rejected because the user already has Koala; the target became an interactive music collaborator.
- Named **Tandem**; user requested **full-stack**, not only a prototype.
- GitHub repository: `ogoldberg/tandem-music`; hosted on Vercel instead of split GitHub Pages/Render.
- Provider/model neutrality was explicitly required; text LLM adapters and capability metadata added.
- User requested automated tests; Python and Node workflows added (passing state must be verified).
- Security 503 initially blocked non-paid audio routes; fixed so only `/api/chat` requires an AI token on Vercel.
- Basic Pitch transcription failed at 48 kHz; explicit 22.05 kHz resampling added.
- Initial “polish” was just EQ/dynamics; users wanted **actual pitch correction**.
- Added an experimental proprietary-free pitch shifter, then replaced the active path with WORLD/PyWorld for formant-aware resynthesis.
- Original PyWorld distribution failed in Vercel Python 3.12; switched to a prebuilt wheel and observed a READY deployment. The new audio path still requires quality testing.
- Added simple detected vocal target note +/- controls; VOX.3 replaced them with a visual pitch-contour editor.

## Decisions still open
Provider choice for conversation and generation; user-account model; cloud storage; license audits for distribution; offline mode strategy; audio quality targets and sample library; monetization/hosting tier; whether to add a native Mac companion/plugin host.
