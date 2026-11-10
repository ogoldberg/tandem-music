# Architecture decision records (concise)

Last reviewed: 2026-11-10. Decisions are revisable.

## ADR-001: Browser-first rather than MPC hardware
**Decision:** Responsive web app for Mac and Android; no required Akai MPC. **Reason:** immediate access and low friction. **Trade-off:** browser audio/CPU/device differences require testing.

## ADR-002: Full-stack, not frontend-only
**Decision:** Python FastAPI backend on Vercel for DSP and AI orchestration, browser UI for recording/editing/export. **Reason:** safe server-only credentials and native DSP libraries. **Trade-off:** function CPU/runtime/bundle constraints.

## ADR-003: Capability-specific, provider-neutral models
**Decision:** Portable project schema; configurable text LLM, on-device Basic Pitch transcription, WORLD tuning, future independent music-generation adapters. **Reason:** no single model does every job well. **Trade-off:** adapters/evals must be maintained. The present music-generation slot is not functional.

## ADR-004: Preserve the user's melody
**Decision:** Default melody lock on structured LLM edits, with undo. **Reason:** accompaniment instructions must not erase the original idea. **Trade-off:** intentional melody edits require the user to unlock; lock does not constrain every timbral/tempo change.

## ADR-005: Prefer open-source vocal tuning
**Decision:** WORLD vocoder using `pyworld-prebuilt` rather than licensing/repackaging Melodyne or Antares. **Reason:** portability, cost and control. **Trade-off:** quality and note editing are currently experimental.

## ADR-006: Stateless initial storage
**Decision:** Browser draft and portable JSON files; no cloud project DB on ephemeral Vercel functions. **Reason:** minimizes cost and complexity. **Trade-off:** projects/audio do not roam seamlessly across devices.

## ADR-007: Tests and transparency
**Decision:** Python and Node CI suites plus real-device QA and explicit implemented-vs-planned documentation. **Reason:** READY deployments do not demonstrate audio quality. **Trade-off:** ongoing evaluation and fixture maintenance.

## ADR-008: Pitch-contour editor targets note centres
**Decision (VOX.3, 2026-11-10):** The editor stays note-based: one target pitch per detected note, drawn over the sung pitch line, with the server moving each note by its target minus its sung centre and keeping a chosen share of the vibrato (`vibrato`, editor default 100%, API default 0). Basic Pitch fragments are merged into whole notes in the browser; confidence stays client-side. **Reason:** dragging whole notes is what the roadmap asked for and what `/api/tune` can do statelessly; moving the note centre (not each frame) is what lets a target be dragged further than the old 250-cent cap and keep vibrato. **Trade-off:** no free-hand curve drawing or drift editing; the corrected line is a preview from Basic Pitch's contour, not WORLD's own analysis; the 100% default is unverified by ear until VOX.2.

## ADR-009: Access token lives for the tab only
**Decision (AI.3, 2026-11-10):** The browser keeps the shared access token in `sessionStorage` after a successful connection and deletes any `tandem-token` older versions left in `localStorage`. **Reason:** the token no longer outlives the tab or sits on disk for other users of the device, with no new server secret or session state. **Trade-off:** users re-enter it in each new tab; script on the page can still read it while the tab is open; an HttpOnly cookie session is deferred until there are real accounts.
