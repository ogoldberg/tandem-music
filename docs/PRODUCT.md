# Tandem — Product vision

Last reviewed: 2026-11-10. Status: living specification.

## Vision
Tandem is a conversational musical collaborator. Hum a melody, sing imperfectly, beatbox a rhythm, or describe an idea; Tandem helps turn it into editable, playable music. Unlike one-shot prompt-to-song generation, **the person's original musical idea stays central**.

## Principles
- Human idea first. Never silently overwrite a recording or the intended melody.
- Conversational **and** visual control: music should be approachable without DAW expertise.
- Structured, portable notes and rhythms, not only opaque rendered audio.
- Reversible edits, A/B comparisons, versioning and clear descriptions of changes.
- Mac and Android web access, ideally installable and affordable.
- Models selected separately by capability; no provider lock-in. The operator's keys never reach the browser; a user's own key stays in their browser and goes only to the provider they chose.
- Local-first (ADR-011): processing on the device where practical, the user's work stored on their device or in storage they bring, and no accounts. Model costs are paid with the user's own keys; the hosted AI path is optional.

## Primary experiences
1. **Hum → transcribe → arrange.** The user records humming, corrects detected notes/timing, chooses instruments, asks the assistant for accompaniment, auditions changes, and exports.
2. **Beatbox → drums.** Detect onset timing and drum categories, expose confidence and editable events, turn rough mouth percussion into a usable groove.
3. **Sing → tune.** Preserve the original recording, detect notes/pitch contour, optionally select targets, apply natural or stylized correction, compare, and export.
4. **Conversation → musical edits.** “Keep my melody, make the rhythm more playful, add harmony.” Produce an explicit edit plan, respect melody lock, audition and undo it.
5. **Eventually generate professional sounds.** Optional music generation and stems based on the user's material, not a replacement of it.

## User interface requirements
- Record/import; transcription and processing progress/errors.
- Visual notes/timeline; eventually a true draggable pitch-contour editor.
- Beginning scope: two tracks (melody and drums), future multitrack and vocal stems.
- Original/processed playback; explicit correction-strength and instrument controls.
- Music-aware text conversation, eventually spoken conversation.
- Save/open/export portable projects and WAV/MIDI files.

## What currently exists
Browser recording/import, Basic Pitch on-device transcription and server fallback, heuristic beatbox analysis, elementary two-track synthesis, simple note/drum event editing, MIDI/WAV export, local JSON projects, undo/redo across all edits, text AI edit-plan endpoint (requires configured model), basic EQ/dynamics vocal polish, and experimental WORLD pitch correction with +/- semitone vocal note targets.

## What is NOT finished
Bring-your-own AI keys and storage (planned, ADR-011), on-device tuning, provider-integrated music generation, robust beatbox classification, studio-grade vocal correction, accurate continuous pitch-contour editor, real-time spoken assistant, high-quality instrument sounds, durable on-device storage of projects and recordings (IndexedDB/OPFS) and a synced-folder option (there will be no Tandem accounts or cloud project storage for now), full Android/Mac end-to-end testing.

## Acceptance criteria
A feature is “working” only after an end-to-end test, not just a successful deployment. For the key journey: record → transcribe → correct → arrange → audition → undo → export, test real microphones, silence, pitch bends, clipping, browser reloads and provider failures. See TESTING.md and ROADMAP.md.
