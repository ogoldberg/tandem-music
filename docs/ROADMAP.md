# Roadmap and change history

Last reviewed: 2026-11-10. This is a prioritized working plan, not a delivery promise.

## Milestones and status
| Status | Milestone | Notes |
|---|---|---|
| Implemented, needs device QA | Responsive browser studio | Mac/Android browser targets, recording/import, playback |
| Implemented, experimental | Humming-to-note transcription | Basic Pitch + 22,050 Hz resampling, fallback heuristic |
| Implemented, experimental | Beatbox-to-drum events | Onset and centroid heuristics |
| Implemented, limited | Two-track arrangement | Eight synthesized melody voices (layered oscillators, envelopes, filters), basic drums and simple editing |
| Implemented, limited | WAV/MIDI/JSON export | No embedded recorded audio in JSON |
| Backend implemented, not live-configured | Model-agnostic text conversation | OpenAI-compatible, Anthropic, Gemini; production AI credentials absent on last inspection. In the Mac app the user's own key in the Keychain (AI.4, implemented, real-key check pending); later optionally from the browser (ADR-011) |
| Implemented, experimental | EQ/dynamics vocal polish | Not tuning |
| Implemented, experimental | Vocal pitch correction | WORLD/PyWorld; semi-automatic note targets; not Melodyne-level |
| Implemented, experimental | Vocal contour editor | Drag notes, retain vibrato, key/scale UI, confidence (VOX.3); not yet judged by ear |
| Planned | Better vocal quality | Quality benchmark, artifact handling, phoneme preservation |
| Implemented, needs device QA | Better arrangement | Swing, richer voices, generated chord/bass harmony and phrase editing (ARR.1) |
| Planned (next) | Phone capture | Catch song ideas on the go: the web app installed on the phone, one tap to record, ideas kept on the phone and shared to the studio as files (MOB.1-MOB.4, ADR-013) |
| Implemented from source, needs QA | Mac app | The same studio in a native window with its own local backend (DESK.1, `python -m tandem_desktop`); no hosted limits (DESK.2) and projects as folders of files (DESK.3) implemented, needing the same QA; your own AI key in the Keychain (AI.4) implemented, needing a real-key check; next: a signed app (DESK.4), ADR-012 |
| Implemented, needs listening QA | Sampled instruments | Recorded General MIDI samples for melody, harmony and drums in playback and WAV export, with the oscillator voices as a fallback (SND.1); not yet judged by ear on real speakers |
| Planned | Local AI audio models | Voice separation (Demucs), a backing band generated from the hum (MusicGen-Melody), voice-to-instrument (RAVE), run on the Mac (SEP.1, GEN.2, TIMBRE.1); the runtime that downloads, verifies and runs them is implemented (MODEL.1) with no model in its catalog yet |
| Planned | Music generation | Capability-specific adapters for externally hosted or self-hosted audio models |
| Planned | Conversational speech | Spoken chat and audio intent alongside text |
| Implemented, needs device QA | Local-first storage | No accounts (ADR-011): the draft, versions and recordings in IndexedDB/OPFS (STORE.2a); in the Mac app projects are plain files (DESK.3); the browser folder and bucket options are parked |
| Planned | Hand-off to other music tools | Stems and multi-track MIDI, MusicXML, DAWproject, Web MIDI (EXP.1-EXP.4) |
| Planned | Production QA | Android/Mac e2e recording and audio quality evaluations |

## Task backlog

This is the working task list, in strategic order: protect the deployment, prove the core loop works on real devices, turn on the AI half of the product, then build a safety net before the larger editor work. Sections 1-5 are mostly done. Since ADR-013 (2026-11-10) phone capture comes first (section 5a): the web app installed on the phone catches song ideas and hands them to the studio as files. After it, since ADR-012 the open work is ordered for the biggest gain per unit of effort: first the quick audible win (sampled instruments), then the Mac app, which removes the hosted limits and is what lets Tandem run large audio models; then the AI half through the Mac app's own backend, hand-off to GarageBand and Logic, and the local audio models (sections 6 and 7). Since ADR-011 the product is local-first with the user's own storage and AI keys (section 8); the hosted AI path in section 3 is optional, and the web app stays as the zero-install and Android path. Loopkit's `/next-task` reads it (see `.agent-workflow.yml`). Format: `- [ ]` pending, `- [~]` in progress, `- [x]` done; the bold token is the task ID. `*(HUMAN)*` marks work that needs the owner: real devices, listening judgement, credentials, account settings or product decisions. Mark a task `[x]` only with evidence (CI run, recorded device result, merged PR). Real-device results (QA.1) may reorder the vocal and arrangement work.

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
- [ ] **AI.1** *(HUMAN)* Optional hosted AI: choose the text provider and model; set `TANDEM_PROVIDER`, `TANDEM_MODEL`, `TANDEM_API_KEY` and `TANDEM_ACCESS_TOKEN` in Vercel with provider budget caps and alerts
  - **Depends:** SEC.1, AI.5 (for the model choice)
  - Since ADR-011 this is only for a hosted mode with the operator's key; local use works with the user's own key (AI.4) and does not need it.
  - Follow "Before enabling paid AI" in `docs/SECURITY.md`.
- [ ] **AI.2** Verify structured AI edits end to end with a real model
  - **Depends:** AI.4 (or AI.1 for the hosted mode)
  - **Acceptance:** a small edit succeeds on the deployed app with a real key (the user's own from the browser; the hosted `/api/chat` too if AI.1 is done); melody lock still blocks melody changes; result recorded in `docs/TESTING.md`.
- [x] **AI.3** Replace the localStorage access token with a safer session model
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

### 5a. Next: capture song ideas on the phone (ADR-013)
The phone catches ideas; the studio (the Mac app or a desktop browser) develops them. Built as the existing web app installed to the home screen, so no second codebase. Comes before the rest of section 6 (DESK.2-DESK.4).
- [~] **MOB.1** Capture screen: one tap to record an idea on the phone, kept on the device
  - A screen in the same app (same origin, so ideas share its storage) with one large record button, built for a phone held in one hand. Every take is saved on the device as soon as it stops (the recording in OPFS through `recordings.js`, its entry in IndexedDB through `storage.js`) as an idea with its time and an optional name; a failed save is reported, never silent. Ideas are listed newest first and can be played, renamed, deleted (with undo or confirmation) and opened in the studio, which loads the recording into the draft as a new project without touching the current one unless the user agrees. Reachable from the home-screen icon (a manifest shortcut or start URL) without scrolling through the studio.
  - **Depends:** STORE.2a
  - Done: `capture.html` at `/capture` (own `capture.webmanifest`, studio manifest shortcut) records in one tap, keeps each take at once through `recordings.js` and the new `ideas.js` (IndexedDB key `ideas`), lists ideas newest first, plays, renames, deletes with a second tap and opens them in the studio (`./?idea=<id>`), which first saves a non-empty draft as the version "Before <idea>". A take ends and is kept when the page is hidden; a failed save offers the take as a download. The studio's recording clean-up keeps ideas' recordings. Covered by `tests/ideas.test.mjs`, route tests in `tests/test_api.py` and `e2e/test_capture.py` (Chromium, phone-sized touch context, fake microphone). Remaining: Playwright's WebKit refuses OPFS in its test profiles, so the WebKit run named in the acceptance could not be done; iOS Safari is checked on a real phone in MOB.4.
  - **Acceptance:** browser tests in Chromium with phone emulation and in Playwright's WebKit record with a fake microphone, find the idea after a reload, play it, rename it, delete it and open it in the studio; Node unit tests for the idea list; the studio keeps working unchanged.
- [~] **MOB.2** Works offline and installs on iPhone and Android
  - The service worker precaches the capture screen and everything it imports, so the app opens and records with no network; Basic Pitch's model and the instrument samples are cached on first use. The manifest gets real icons (and an `apple-touch-icon`), so the app installs to the home screen on iOS and Android. Persistent storage is requested when the first idea is saved, and the capture screen shows whether it was granted.
  - **Depends:** MOB.1
  - **Acceptance:** a browser test loads the app, goes offline, reloads, records and keeps an idea; the manifest passes an installability check in Chromium; the icons are in the repo with their source.
  - Done in Chromium: `sw.js` precaches the studio, the capture page, their modules, manifests and icons; `/vendor/` files go to their own `tandem-vendor-1` cache on first use, are served from it first and survive `CACHE` bumps; an offline page opened with a query string (`./?idea=`) gets its cached page, stored once without the query; cache lookups ignore `Vary: Origin`. Icons are drawn in `icons/icon.svg` and `icons/icon-maskable.svg` and rendered by `tools/icons/build.py`; both manifests list them and both pages link the `apple-touch-icon`. The capture page asks for persistent storage once per visit, when an idea is first kept, and shows the answer. Open: iOS Safari and Android Chrome on real phones (MOB.4); Playwright's WebKit cannot run these tests here.
- [x] **MOB.3** Share an idea out and open it in the studio
  - An idea is shared as one file (the project and its recording) through the Web Share API with files where the browser supports it (AirDrop, Files, iCloud Drive), and downloaded elsewhere. The studio opens the file with its audio. The format matches what DESK.3 saves (`project.json` plus the recording as WAV), so the Mac app reads ideas from a synced folder too; agree the format here and reuse it in DESK.3.
  - **Depends:** MOB.1
  - **Acceptance:** Node tests write and read the file format round trip; a browser test shares (with `navigator.share` mocked) and opens the file in a fresh profile with its audio; the format is documented in `docs/ARCHITECTURE.md`.
  - Done: `bundle.js` writes and reads the Tandem file, `<name>.tandem.zip`: `tandem.json` (name, time recorded), `project.json` (the project as Save project writes it) and `original.wav`, plus `polished.wav` and `tuned.wav` when there are any; these are the DESK.3 folder's file names, so DESK.3 reuses the module. Written uncompressed; read stored or deflated, at the top or inside one folder, ignoring `__MACOSX`. The capture page's Share converts the take to WAV and uses `navigator.share` with the file where the browser accepts it, otherwise downloads it (Android Chrome does not share zip files, so it downloads there); a share refused because building the file outlasted the tap is offered again. The studio's Open project opens it with its recordings, first saving a non-empty draft as a version. Format documented in `docs/ARCHITECTURE.md`; covered by `tests/bundle.test.mjs` and `e2e/test_share.py` (Chromium, `navigator.share` replaced by a stand-in). Open: the real share sheets and opening a shared file on the Mac (MOB.4).
- [ ] **MOB.4** *(HUMAN)* Capture QA on a real iPhone and an Android phone
  - Install to the home screen, grant the microphone, record ideas, quit and reopen, use it offline (airplane mode), come back after several days and check the ideas are still there, share one to the Mac and open it. Check what happens when the screen locks or another app comes to the front during a take.
  - **Depends:** MOB.1, MOB.2, MOB.3
  - **Acceptance:** results recorded in `docs/TESTING.md` for iOS Safari and Android Chrome.

### 6. Biggest boost for least effort: sampled instruments and the Mac app (ADR-012)
Ordered by gain per unit of effort. SND.1 helps the web app and the Mac app alike and depends on nothing. DESK.1 reuses `index.html` and `tandem_backend.py` unchanged. Every later item builds on it.
- [~] **SND.1** Sampled instruments: play melody, harmony and drums with recorded General MIDI instruments instead of synthesized tones
  - Effort: about a day or two. Load a General MIDI sample set (for example through the `smplr` library, or a SoundFont such as GeneralUser GS played by a SoundFont synth) for live playback and the offline WAV export, so both sound alike, as `voices.js` does now. The current oscillator voices stay as a fallback for an instrument whose samples are missing or still loading, and the project's `instrument` names map onto General MIDI programs. Self-host the samples with hashes like Basic Pitch (SEC.3), so nothing loads from a third-party CDN at play time. Check the sample set's license before adding it (GeneralUser GS's terms allow use in your own music, private or commercial; confirm the exact set used) and record it in `docs/SECURITY.md`.
  - Done: `samples.js` plays recorded General MIDI samples for the melody, the harmony and the drums, in live playback and in the offline WAV export through the same `playSample`/`playDrumSample` functions. `tools/gm-samples/build.py` (needs FluidSynth and LAME; `--check` rebuilds in a temp directory and diffs) renders FluidR3_GM.sf2 (Frank Wen, MIT license, from Debian's `fluid-soundfont-gm_3.1-6_all.deb`, whose SHA-256 the script checks) into `vendor/gm-samples-1/`: 179 mono 22,050 Hz 64 kbps MP3s (about 3.7 MB), one root note every 3 semitones per instrument, dry, velocity 100, with crossfaded loop points for the sustained instruments (strings, chip, organ, flute) and kick/snare/hat from the standard drum kit, plus `manifest.json`, `LICENSES.txt` and `SHA256SUMS`. The route `/vendor/gm-samples-1/{name}` serves only files listed in `SHA256SUMS`, immutable. Samples for the parts a project uses are preloaded when it changes, Play waits up to 3 s for them and the WAV export up to 15 s (issue #44). A part whose samples are missing or still loading plays its oscillator voice from `voices.js`, and the status line says so. A decaying note held longer than its 2-4 s recording fades over the voice's release time and ends with it. Covered by `tests/samples.test.mjs`, the route, hash and license tests in `tests/test_api.py`, and the e2e tests `test_instruments_play_from_samples_and_fall_back_to_oscillators` and `test_export_wav_does_not_hang_when_sample_requests_stall`. Remaining: the first listen on real speakers, including whether held strings, chip, organ and flute notes loop without a click in Safari and Firefox *(HUMAN)*.
  - **Acceptance:** every instrument in `INSTRUMENTS` plays from samples in playback and in the WAV export; a browser test exports each instrument and checks the WAV is distinct, unclipped and different from the oscillator voice; the samples load from this app only, with hashes checked; a first listen on real speakers is recorded as manual QA.
- [~] **DESK.1** Mac app: run the studio in a native window with its own local backend
  - Effort: a few days. A small launcher (pywebview first; Tauri or Electron if pywebview cannot do what is needed) starts `tandem_backend:app` on `127.0.0.1` only, on a fixed local port chosen once and kept across launches (not a random free port), and opens the studio in a native window. The port must be stable because IndexedDB and OPFS belong to the origin (scheme, host and port): a different port on the next launch would hide the user's draft, versions and recordings. The web view must use persistent storage (pywebview with `private_mode=False`; check the equivalent if the shell changes). The server checks the `Host` header and refuses any other (this belongs here, not in DESK.2, so the loopback-only guarantee holds from the first launch). The UI and the backend are the same code as the web app; `/api/config` reports that it is running locally. Risk first: before anything else, prove that microphone recording (`getUserMedia`), Web Audio playback, IndexedDB/OPFS storage and file downloads work in the chosen web view on macOS (WKWebView needs a microphone usage description and permission handling). If they do not, switch shells before building more.
  - Runs from source first (`python -m tandem_desktop`); a signed, notarized `.app` is DESK.4.
  - Done: risk check on macOS 27 with pywebview 6.2.1 (WKWebView) passed: `getUserMedia` gets a microphone track once the app answers WebKit's capture request (without that, WebKit asks on every launch), and OfflineAudioContext, IndexedDB, OPFS `createWritable`, Web Locks, MediaRecorder and downloads through the native Save panel work; IndexedDB and OPFS data survive a relaunch on the same port; `navigator.storage.persist()` returns false. `tandem_desktop/` keeps the port in `~/Library/Application Support/Tandem/desktop.json`, binds `127.0.0.1` only, answers 421 to any Host but `127.0.0.1:<port>`, grants the microphone only to its own origin and stops the server when the window closes; `/api/config` reports `"runtime": "desktop"`. Covered by `tests/test_desktop.py` and `e2e/test_desktop.py`. Remaining: the operator's manual QA on their Mac *(HUMAN)*.
  - **Acceptance:** on the operator's Mac, the app opens, records from the microphone, transcribes, plays, tunes and exports, and keeps the draft across a quit and relaunch (same port, persistent storage), recorded as manual QA; tests show a request with a foreign `Host` is refused; an automated test starts the launcher's server and loads the page; the web app keeps working unchanged.
- [~] **DESK.2** Lift the hosted limits when running locally, safely
  - **Depends:** DESK.1
  - In local mode: no per-IP rate limits, and recordings longer than the hosted 90 s / 25 s per-request caps are tuned and analysed in one request (chunking stays for the hosted mode). The local server must not be a door for web pages: DESK.1 already binds it to `127.0.0.1` only and checks the `Host` header, and DESK.2 adds a per-launch secret that the launcher injects into its window and that every request carries in a request header (never in a query string, a cookie or a command-line argument, where it would reach logs, history or the process list). The secret keeps out web pages in the user's browser, including through DNS rebinding; it does not keep out other processes running as the same user, which can read the secret and are outside this threat model. In local mode CORS allows only the app's own origin: the default list in `tandem_backend.py` (`origins`) includes `https://ogoldberg.github.io`, which local mode must drop.
  - **Acceptance:** tests show a request without the per-launch secret is refused in local mode, a cross-origin request from any origin but the app's own gets no CORS approval (including `https://ogoldberg.github.io`), and the secret is accepted only in the header, and the hosted mode's limits and tests are unchanged; a 3-minute vocal tunes in one request in the Mac app (manual QA).
  - Done: per-launch secret (`tandem_desktop.new_launch_secret`) given only to the window's own-origin page by a WebKit user script; `guarded_app` refuses `/api/` without it in the `x-tandem-launch` header (query string and cookie ignored) and any request from another origin, before CORS runs; requests it passes are marked local and get no rate limit and 600 s / 4096 targets / 240 MB per audio request, reported by `/api/config` as `limits`; the page tunes in one request when those limits allow it. Covered by `tests/test_desktop.py`, `tests/tuning.test.mjs` and `e2e/test_desktop.py` (a 70 s take tuned in one request, twice, with the rate limit set to 1). Remaining (HUMAN QA): a 3-minute vocal tuned in one request in the real Mac app window, which also proves the secret reaches WKWebView.
- [~] **DESK.3** Projects as files on disk in the Mac app
  - **Depends:** DESK.1
  - Save and Open use native file dialogs and write a project folder (`project.json` plus its recordings as WAV files) wherever the user picks, including a folder synced by iCloud Drive, Dropbox or Google Drive. This replaces STORE.2b in the Mac app. The web app keeps export/import and its on-device storage (STORE.2a).
  - **Acceptance:** a project with its original, polished and tuned recordings saved to a folder opens again with its audio after a relaunch, and the same folder opens on a second Mac through a synced folder (manual QA); unit tests for the folder format.
  - Done: in the Mac app's own window the studio shows **Save to folder…** and **Open folder…**. The page sends the project as the MOB.3 Tandem file (`bundle.js` `writeBundle`, recordings converted to WAV) to `/api/desktop/project/save`; `tandem_desktop/projects.py` opens the window's native save dialog (pywebview `FileDialog.SAVE`, suggesting the project's name) and unpacks it into that folder: `project.json`, `tandem.json` (named after the folder) and `original.wav`/`polished.wav`/`tuned.wav`, each written beside its name and moved into place, recordings it no longer has removed, every other file left alone; a folder holding other files is refused. `/api/desktop/project/open` opens the native folder dialog and answers the folder's files as a Tandem file, which the studio opens like one (a non-empty draft is first kept as a version). The routes exist only behind `guarded_app` (the launch secret), never on the hosted app; one dialog at a time; a recording still in iCloud is named instead of left out; a link in place of one of the five files is refused rather than followed (#61). Covered by `tests/test_desktop_projects.py` (folder format, refusals, routes, dialogs) and `e2e/test_desktop.py` (save, then a relaunch with a new server and a fresh browser profile opens the folder with its recording and tempo). Remaining (HUMAN QA): the native dialogs in the real Mac app window, a project with polished and tuned recordings reopened after a relaunch, and the same folder opened on a second Mac through iCloud Drive or Dropbox.
- [~] **AI.4** Bring your own AI key
  - **Depends:** SEC.1, DESK.2
  - Mac app first (the main path; the browser-held key rules in `docs/SECURITY.md` apply only to the later web path): the user's key is kept in the macOS Keychain and used by the local backend's existing `invoke_llm`, `normalize_actions` and melody lock, so no validation is ported to JS and no key sits in the page. Providers: OpenAI, Anthropic, Gemini, OpenRouter, and a local Ollama (no key). A settings screen sets the provider, model and key.
  - Web app (later, optional): the browser path described in ADR-011 (the key kept in the browser, a JS port of the validation checked against the Python version on shared fixtures, and a strict Content Security Policy before any key is stored).
  - **Acceptance:** with a real key for at least one provider, an edit applies in the Mac app and melody lock blocks a melody change; the key is read from the Keychain and never written to project files, logs or the page; `docs/SECURITY.md` records where the key is kept.
  - Done (Mac app path): **Your AI**, under Compose together, shows only in the Mac app's window: choose OpenAI, Anthropic, Google Gemini, OpenRouter, Ollama on this Mac (no key) or another OpenAI-compatible server (its address, key optional), name the model, paste the key, Save; **Remove key** deletes it. `tandem_desktop/ai_keys.py` keeps the provider and model in `ai.json` and the key in the Keychain (`keyring`, added to `requirements-desktop.txt`), and `guarded_app` gives these settings to `/api/chat` and `/api/config` for the window's own requests, so `invoke_llm`, `normalize_actions` and melody lock are unchanged; with nothing saved the server's own `TANDEM_*` configuration still applies, and a saved provider without its key is an error that says so, never a switch to another provider. Covered by `tests/test_desktop_ai.py` (each provider gets the saved model and key in its own header and melody lock strips the melody edit; the key is in the key store and in no answer, file or log; the real macOS Keychain stores, reads and deletes a key on a Mac) and the browser test `e2e/test_desktop.py::test_your_own_ai_key_is_kept_out_of_the_page_and_an_edit_uses_it` (a stand-in OpenAI-compatible server receives the chat with the key; the tempo edit applies and the melody is unchanged). Remaining (HUMAN QA, needs the operator's own key): in the real Mac app window, save a real key for one provider, ask for an edit, and check it applies and that melody lock blocks a melody change.
- [~] **EXP.1** Export stems and multi-track MIDI for any DAW
  - **Depends:** STORE.2a (the recorded and tuned vocal must be kept to export it)
  - One WAV per part (melody, harmony, drums, and the original, polished and tuned vocal when present), all the same length and starting at zero so they line up when dropped into a DAW, offered as one zip. A type-1 MIDI file with one named track per part (melody, harmony, drums on channel 10) plus tempo and key signature, alongside the existing single-track export or replacing it. Later parts made by section 7's models (separated stems, the generated band) are added as stems when they exist.
  - **Acceptance:** the melody, harmony and drum stems line up sample-exactly with the mixed WAV (their sum matches it within rounding; vocal stems are not part of the mix); the MIDI parses with a standard parser into named tracks with the right tempo, key and notes; checked by importing into a real DAW, GarageBand first and then Logic (others such as Ableton Live, Reaper or BandLab later), and recorded as manual QA; Node unit tests and a browser test.
  - Done: **Export stems** (`daw.js`, pure) downloads `tandem-stems.zip`: `mix.wav`, `melody.wav`, `harmony.wav`, `drums.wav` for the parts that have notes, and `vocal-original.wav`, `vocal-polished.wav`, `vocal-tuned.wav` for the recordings the studio holds, all mono 16-bit at 44.1 kHz, starting at zero and as long as the longest, plus `tandem.mid`. Each part renders on its own from time zero; `mix.wav` and **Export WAV** are the sum of the part stems (Export WAV moved from 22,050 Hz with a 0.1 s lead-in to 44.1 kHz from zero, so the notes, the MIDI and the vocal line up). Vocals are decoded at 44.1 kHz and placed at zero, where the notes transcribed from them start. **Export MIDI** now writes the type-1 file (it replaces the single-track export, whose header said 480 ticks per beat while its events used 960, so DAWs played it at half speed): a `Tandem` conductor track with tempo, 4/4 and the key signature (the harmony key chosen in the studio, else the key detected from the melody, else from the harmony, else none), then `Melody` (channel 1) and `Harmony` (channel 2) with their General MIDI programs and `Drums` (channel 10, kick 36, snare 38, hat 42), at 960 ticks per beat. Covered by `tests/daw.test.mjs` and the browser test `e2e/test_studio.py::test_stems_line_up_with_the_mix_and_the_midi_has_a_track_per_part` (stems sum to the mix within one 16-bit step per stem; the MIDI read with `mido`). Remaining (HUMAN QA): import the stems zip and `tandem.mid` into GarageBand, then Logic, and record whether the parts line up and the tempo, key, track names and instruments come through.
- [ ] **DESK.4** *(HUMAN)* Package the Mac app: a signed, notarized `.app` with auto-update
  - **Depends:** DESK.1
  - Needs an Apple Developer account (paid) and the operator's signing identity. Until then the app runs from source.
  - **Acceptance:** the `.app` opens on a Mac that has never run Tandem, without Gatekeeper warnings; the build steps are in `docs/DEVELOPMENT.md`.

### 7. Local AI audio models on the Mac (ADR-012)
These models are too large and slow for Vercel's serverless functions, which is why they wait for the Mac app. They run in the Mac app's backend on Apple silicon (PyTorch with the MPS backend, or an MLX/Core ML port where one exists) and never in the hosted mode. Each one adds to the user's idea and never replaces it (ADR-004): its output is a new part the user can mute, delete or undo.
- [ ] **LIC.1** *(HUMAN)* Decide whether Tandem will be sold or distributed to others, and so which model weights it may use and ship
  - MusicGen's weights (GEN.2) are licensed CC-BY-NC 4.0: non-commercial use only. The Demucs v4 (HTDemucs) weights are tagged MIT on Hugging Face, but other sources describe them as non-commercial; check the official repository. RAVE's and the sample sets' licenses still need checking. For the operator's own use, none of this blocks building; for any distribution, it decides which models ship and which are a download the user opts into.
  - **Acceptance:** decision and each model's license recorded in `docs/DECISIONS.md` and `docs/SECURITY.md`.
- [x] **MODEL.1** Local model runtime: download, verify and run large audio models in the Mac app
  - **Depends:** DESK.2
  - Optional Python dependencies (PyTorch and friends) installed only for the Mac app, never in `requirements.txt` for Vercel. Weights download on first use into the app's data folder, pinned by URL and SHA-256 and verified before loading, with the size shown before the download starts. A small background-job API runs a model with progress and cancel, so a minute-long generation does not block the UI. `/api/config` reports which models are installed.
  - **Acceptance:** tests with a tiny stand-in model cover download, a bad hash being refused, progress, cancel and a job error being reported; the hosted mode does not import any of it (checked by a test).
- [ ] **SEP.1** Separate the voice from background music (Demucs)
  - **Depends:** MODEL.1
  - Effort: a couple of days. A Separate button splits a recording into vocals and accompaniment (HTDemucs). The vocal becomes the recording that Transcribe, Polish and Tune work on, so a user can sing along to a song playing in the room, or start from an existing track; the original stays available (ADR-004). The stems are kept like any other recording and exported by EXP.1.
  - **Acceptance:** on a fixture mixing a known sung melody with an accompaniment, transcription after separation finds the melody's notes within a documented tolerance, and finds clearly fewer of them without separation; a 3-minute song separates on the operator's Mac within a documented time (manual QA).
- [ ] **GEN.2** A backing band from the hum (MusicGen-Melody)
  - **Depends:** MODEL.1, LIC.1 (only before any distribution)
  - Effort: about a week. Generate full-band audio that follows the user's own melody: MusicGen-Melody takes a melody (the original or tuned vocal, or the transcribed melody rendered as audio) and a text style ("lo-fi band with brushed drums"), plus the project tempo and key in the prompt. The result is a new optional audio part of the project, stored as a recording link and kept like the harmony part (ADR-010: older projects stay valid, no AI action changes it). It plays in time with the project, can be regenerated, muted or removed (undoable), and is labelled as generated (provenance). Generation runs as a MODEL.1 job with progress.
  - **Acceptance:** a test with a stand-in model checks the part is added, aligned to zero, saved, undone and exported as a stem; on the operator's Mac a 30-second band is generated from a real hum and judged by ear (manual QA, recorded in `docs/AUDIO.md` with the time it took).
- [ ] **TIMBRE.1** Turn the voice into an instrument (RAVE timbre transfer)
  - **Depends:** MODEL.1
  - Effort: about a week; results vary by model. A sung or hummed line is resynthesized through a pretrained RAVE model (for example a violin or saxophone model), so the user hears their own phrasing played by an instrument. The result is a new recording; the original stays. Check RAVE's and each model's license before adding it (LIC.1).
  - **Acceptance:** a test with a stand-in model covers the job, the new recording and undo; at least two instrument models are judged by ear on real singing (manual QA in `docs/AUDIO.md`).

### 8. Local-first: your device, your storage, your keys (ADR-011)
- [x] **STORE.1** *(HUMAN)* Decide the account model and cloud storage for projects and recordings
  - Decided 2026-11-10 (ADR-011): no accounts for now; local-first, with the user's own storage and AI keys.
- [ ] **STORE.2** Local storage plus bring-your-own storage
  - Split into the parts below; STORE.2 is done when STORE.2a and DESK.3 are (STORE.2b and STORE.2c are parked and can stay open). No Tandem server storage and no per-user quotas (there are no users to give them to).
- [x] **STORE.2a** Keep projects, versions and recordings on the device in IndexedDB and OPFS
  - Projects, the draft and named versions move from `localStorage` to IndexedDB, with existing `localStorage` data migrated once and left readable if the migration fails. Recordings (original and processed audio) are saved in OPFS and linked from the project, so reopening a project brings its audio back. Request persistent storage and show whether it was granted; report a full quota instead of losing data.
  - Done: the draft and named versions are in IndexedDB (`storage.js`), migrated from `localStorage` on start, with persistent storage requested on Save version and its state shown in the Versions panel. Recordings (original, polished, tuned) are kept in OPFS by `recordings.js` and linked from the draft and each version; they come back after a reload, unlinked files are collected, and a full quota is reported. Evidence: Node tests (`tests/storage.test.mjs`, `tests/versions.test.mjs`, `tests/recordings.test.mjs`) and Chromium browser tests in `e2e/test_studio.py`, including a full browser restart. Not verified: Safari's OPFS `createWritable` and any real-device QA.
  - **Acceptance:** a project with a recording, its versions and the draft survive a reload and a browser restart in a real browser; old `localStorage` versions and draft appear after the upgrade; covered by Node unit tests (with an in-memory stand-in for the IndexedDB store) and browser tests against Chromium's IndexedDB.
- [ ] **STORE.2b** Save to folder: read and write projects in a folder the user picks
  - **Parked by ADR-012 (2026-11-10):** the Mac app saves projects as files directly (DESK.3). Take this up only if the web app becomes a main way to use Tandem again.
  - **Depends:** STORE.2a
  - File System Access API (Chromium desktop only; hidden elsewhere, where export/import stays). A folder synced by Dropbox, iCloud Drive or Google Drive syncs projects between devices with no Tandem server. The folder handle is kept in IndexedDB and permission is asked for again when the browser requires it.
  - **Acceptance:** a project with its recording saved to a folder opens in a fresh browser profile pointed at the same folder; browsers without the API show export/import only; browser test with a mocked directory handle.
- [ ] **STORE.2c** Optional: the user's own S3-compatible bucket (R2, B2) with their own keys
  - **Parked by ADR-012:** in the Mac app a synced folder does this job (DESK.3).
  - **Depends:** STORE.2a, AI.4 (shares the key storage and CSP work)
  - **Acceptance:** save and open through a real bucket the operator provides; keys never reach the Tandem server; CORS setup documented for users.
- [ ] **AI.5** Compare small models on the real chat prompt and choose the default
  - **Depends:** AI.4
  - Run the real `/api/chat` prompt over a fixed set of test projects and requests on 3-4 small models (Claude Haiku 5.5, a Gemini Flash, a GPT mini or nano, and a local Qwen through Ollama), scoring valid JSON, valid actions, melody-lock respect and whether the edit did what was asked, plus latency and cost. Running it spends money on real keys: ask the operator before each run.
  - **Acceptance:** results table and the chosen default recorded in `docs/DECISIONS.md` or `docs/TESTING.md`; the harness is in the repo and rerunnable.
- [ ] **VOX.4** On-device pitch correction: WORLD compiled to WebAssembly
  - **Depends:** VOX.1
  - **Parked by ADR-012, planned again by ADR-013:** the Mac app runs WORLD natively, but the phone has no local backend, so tuning on the phone without the network needs this. Take it up after MOB.1-MOB.3.
  - Compile WORLD (C++) with Emscripten, self-hosted with hashes like Basic Pitch (SEC.3), and port `world_tuning.py` to a JS module so `tuning.js` can tune without `/api/tune`. With it the app can run as a static offline PWA; the server path stays for the hosted mode until this is proven.
  - **Acceptance:** the VOX.1 benchmark fixtures give results within documented tolerances of the server version; a long recording tunes in a real browser offline with no API call.

### 9. Hand work on to other music tools
Tandem is where an idea starts; people finish it in their own DAW or notation app. Interchange is through standard files, not plugins or third-party cloud accounts (ADR-011). EXP.1 (stems and multi-track MIDI) moved up to section 6 because it is cheap and GarageBand and Logic are where the operator finishes work. Each export carries the tempo, key and part names where the format allows (a WAV stem cannot).
- [ ] **EXP.2** Export the melody (and harmony) as MusicXML for notation apps
  - Quantized to the project grid with the detected or chosen key, time signature 4/4, tempo, and a chord-symbol or second staff for the harmony. Notes are split into tied, notatable durations.
  - **Acceptance:** the file validates against the MusicXML 4.0 schema; a fixture melody round-trips (pitches and durations) through a MusicXML parser; opened in MuseScore and recorded as manual QA.
- [ ] **EXP.3** Export a DAWproject file
  - **Depends:** EXP.1
  - The open DAWproject format (zip with `project.xml`, `metadata.xml` and audio) with one track per part, note clips for melody, harmony and drums, audio clips for the vocal, and the tempo.
  - **Acceptance:** the XML validates against the DAWproject schema; the project opens with its tracks and audio in at least one DAW that imports DAWproject (Bitwig Studio, Studio One or Cubase), recorded as manual QA.
- [ ] **EXP.4** Web MIDI: play and record from a MIDI keyboard, and send playback to MIDI outputs
  - Only where the browser has Web MIDI (Chromium and Firefox on desktop, not Safari); hidden elsewhere. Input records notes into the melody as one undoable edit at the project tempo; output plays melody, harmony and drums to a chosen device and channel.
  - **Acceptance:** browser test with a mocked `MIDIAccess`; recording with a real keyboard and playing to a real synth recorded as manual QA.

### 10. Later
- [x] **ARR.1** Better arrangement: richer instruments, harmony, swing and phrase-aware editing
  - **Depends:** CI.2
  - Split into the parts below; ARR.1 is done when all four are.
- [x] **ARR.1a** Groove: detect tempo and quantize with swing
  - Done: `groove.js` estimates the tempo from note and drum onsets and quantizes them to a 1/4, 1/8 or 1/16 grid with swing and strength; Detect tempo and Quantize in the Arrange panel are undoable edits. Covered by Node unit tests and a browser test that checks the swung timing in the MIDI export.
  - **Acceptance:** tempo detection within 2 bpm on jittered fixtures without doubling; quantize/swing timing verified in the exported MIDI; both undoable.
- [x] **ARR.1b** Richer instrument voices (layered oscillators, filters and envelopes) and more instruments, in playback and WAV export
  - **Depends:** ARR.1a
  - Done: `voices.js` gives each instrument layered oscillators, an ADSR envelope, an optional swept low-pass filter and vibrato, used by both playback and WAV export; adds organ, guitar and flute. The instrument list is shared by the UI, project open, `/api/chat` validation, the AI action filter and the prompt. Covered by Node unit tests (envelope, Nyquist, graph wiring, list sync) and a browser test that exports every instrument and checks each WAV is distinct and unclipped. Not yet judged by ear on real devices.
- [x] **ARR.1c** Harmony: generate an editable chord or bass accompaniment from the melody's key
  - **Depends:** ARR.1a
  - Done: `harmony.js` detects the melody's key (or takes a chosen one) and generates one diatonic chord per 4/4 bar, as voiced triads or a root-and-fifth bass line. The part is stored as the project's optional `harmony` notes with its own instrument; Generate, Clear, instrument changes and note taps are undoable, and playback, WAV/MIDI export (channel 2), project files, versions and the draft include it. Covered by Node unit tests and a browser test. Not yet judged by ear on real devices.
- [x] **ARR.1d** Phrase-aware editing: detect phrases and move, copy or transpose a whole phrase
  - **Depends:** ARR.1a
  - Done: `phrases.js` splits the melody into phrases at rests of a beat or more at the project tempo. In the Melody track a chosen phrase moves a beat earlier or later, transposes by a semitone or an octave, or is copied to the end a whole number of bars later; each is one undoable edit, and out-of-range edits are refused. The harmony is left alone (generate it again). Covered by Node unit tests and a browser test. Not yet tried by users on real devices.
- [ ] **GEN.1** Optional generative music provider adapter, with explicit provenance
  - **Depends:** AI.4, AI.2
  - Since ADR-012, the local MusicGen-Melody band (GEN.2) comes first; a hosted provider is for users without a capable Mac, or for higher quality than the local model gives.
  - Uses the user's own key for the provider (candidates: Lyria, ElevenLabs Music, Stable Audio), called from the browser where the provider allows it; check each provider's output licensing before adding it.
- [ ] **SPEECH.1** Conversational speech: spoken chat and audio intent alongside text
  - **Depends:** AI.2
  - Speech-to-text on the device (Whisper in the browser) or with the user's own key for a hosted Whisper.

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
Default model for conversation (AI.5) and provider choice for generation; license audits for distribution; audio quality targets and sample library; monetization/hosting tier; whether Tandem will be distributed commercially, which decides the model weights it may ship (LIC.1). Decided in ADR-012: a native Mac app with its own local backend comes next, and a DAW plugin or a C++ audio engine such as Tracktion Engine is not planned. The account model, cloud storage and offline strategy were decided in ADR-011 (local-first, no accounts, the user's own storage and keys).
