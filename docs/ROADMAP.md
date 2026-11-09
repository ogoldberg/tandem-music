# Roadmap and change history

Last reviewed: 2026-11-09. This is a prioritized working plan, not a delivery promise.

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

This is the working task list, roughly in priority order (it replaces the earlier numbered priority list). Loopkit's `/next-task` reads it (see `.agent-workflow.yml`). Format: `- [ ]` pending, `- [~]` in progress, `- [x]` done; the bold token is the task ID. `*(HUMAN)*` marks work that needs the owner: real devices, listening judgement, credentials or product decisions. Mark a task `[x]` only with evidence (CI run, recorded device result, merged PR).

### Testing and CI
- [x] **CI.1** Confirm the GitHub Actions Python and Node suites pass on `main`
  - Verified 2026-11-09: run 42598992550 (`Tests`, success).
- [ ] **CI.2** Add browser end-to-end tests that run in CI
  - Headless browser (e.g. Playwright) against the real FastAPI app: load `/`, import a WAV fixture, transcribe with the server fallback, edit a note, play, export WAV/MIDI/JSON, save and reload a project.
  - **Acceptance:** runs in `.github/workflows/tests.yml`; fails on any uncaught page error or console error; covers the 48 kHz decode path.
- [ ] **QA.1** *(HUMAN)* Run the manual acceptance matrix in `docs/TESTING.md` on macOS Chrome, macOS Safari and Android Chrome
  - **Acceptance:** each matrix cell in `docs/TESTING.md` is updated from "Unverified" to a dated pass/fail, with notes for failures.

### Security and cost
- [ ] **SEC.1** Rate-limit the public CPU routes `/api/analyze`, `/api/polish` and `/api/tune`
  - Must work on serverless Vercel, where in-process memory does not persist between instances; document the limits chosen and where state is kept.
  - **Acceptance:** tests prove requests over the limit get 429; limits documented in `docs/SECURITY.md` and `docs/DEVELOPMENT.md`.
- [ ] **SEC.2** Add resource limits and stricter validation on audio and chat input
  - Review memory/CPU use under malicious or unexpected inputs (oversized, malformed, long, many-channel WAVs) and tighten the `/api/chat` project schema validation.
  - **Acceptance:** tests for each rejected input class; no route reads unbounded input.
- [ ] **SEC.3** Pin or self-host the Basic Pitch model and JS instead of loading unpinned CDN assets
  - **Acceptance:** exact versions (with integrity hashes, or served from this app); transcription still works; supply-chain note in `docs/SECURITY.md` updated.
- [ ] **SEC.4** *(HUMAN)* Configure GitHub branch protection on `main` (required PR review, required tests, no force pushes)
  - **Acceptance:** ruleset verified in GitHub settings and recorded in `docs/SECURITY.md`.

### Vocal quality
- [ ] **VOX.1** Build an automated vocal pitch-correction benchmark
  - Generate fixtures with known MIDI pitches and timing at several sample rates, with vibrato, noise and transitions; measure pitch error, duration and loudness change of `/api/tune`, and 0%-strength equivalence.
  - **Acceptance:** runs under `pytest`; records metrics; thresholds documented in `docs/AUDIO.md`.
- [ ] **VOX.2** *(HUMAN)* Blinded A/B listening test of WORLD tuning on real singing
  - **Depends:** VOX.1
  - **Acceptance:** recordings used with consent; results and artifacts noted in `docs/AUDIO.md`.
- [ ] **VOX.3** Continuous pitch-contour editor
  - Replace the +/- target note list with a visual contour: drag notes, keep vibrato, key/scale selection, per-note confidence.
  - **Depends:** VOX.1
  - **Acceptance:** edited targets drive `/api/tune`; covered by unit tests and the CI.2 browser tests.
- [ ] **EDIT.1** Proper undo/redo and project versioning
  - Replace ad hoc note-list edits with an edit history covering manual edits, AI actions and tuning targets.
  - **Acceptance:** undo/redo works across all edit types; tests cover history behavior.

### AI conversation
- [ ] **AI.1** *(HUMAN)* Choose the text provider and model; set `TANDEM_PROVIDER`, `TANDEM_MODEL`, `TANDEM_API_KEY` and `TANDEM_ACCESS_TOKEN` in Vercel with provider budget caps and alerts
  - Follow "Before enabling paid AI" in `docs/SECURITY.md`.
- [ ] **AI.2** Verify structured AI edits end to end on production
  - **Depends:** AI.1
  - **Acceptance:** a small authenticated edit succeeds on the deployed app; melody lock still blocks melody changes; result recorded in `docs/TESTING.md`.
- [ ] **AI.3** Replace the localStorage access token with a safer session model
  - **Acceptance:** the shared token is no longer stored in `localStorage`; `docs/SECURITY.md` updated.

### Later
- [ ] **ARR.1** Better arrangement: richer instruments, harmony, swing and phrase-aware editing
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
- Added simple detected vocal target note +/- controls; a real visual pitch-contour editor remains planned.

## Decisions still open
Provider choice for conversation and generation; user-account model; cloud storage; license audits for distribution; offline mode strategy; audio quality targets and sample library; monetization/hosting tier; whether to add a native Mac companion/plugin host.
