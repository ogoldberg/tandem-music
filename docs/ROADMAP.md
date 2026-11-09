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

## Near-term priorities
1. Confirm CI tests pass; fix any failures and add browser e2e checks.
2. Test real microphone → transcribe → note edit → tune → playback/export on Mac and Android.
3. Investigate pitch shifts on real singing with blinded A/B and synthetic benchmark audio.
4. Add safe model configuration and test structured conversation without losing human melody.
5. Replace ad hoc note list with a continuous pitch editor and proper undo/versioning.
6. Make security/hosting costs predictable before opening the app to users.
7. Then add optional generative music providers, with backend abstraction and explicit provenance.

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
