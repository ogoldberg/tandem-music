# Tandem — Product vision

Last reviewed: 2026-11-13. Status: living specification.

## Vision
Tandem is a conversational musical collaborator. Hum a melody, sing imperfectly, beatbox a rhythm, or describe an idea; Tandem helps turn it into editable, playable music. Unlike one-shot prompt-to-song generation, **the person's original musical idea stays central**.

## Who it is for
Someone with a song idea who does not know the advanced tools and has little time (operator, 2026-11-13). The guided Sing / Notes / Song / Share flow (UI.1) comes before new features; every advanced control stays reachable but is not in the way.

## Principles
- Human idea first. Never silently overwrite a recording or the intended melody.
- Conversational **and** visual control: music should be approachable without DAW expertise.
- Structured, portable notes and rhythms, not only opaque rendered audio.
- Reversible edits, A/B comparisons, versioning and clear descriptions of changes.
- Capture on the phone, develop in the studio: the web app installed on the phone catches ideas the moment they come (ADR-013), and the Mac app (ADR-012) or a desktop browser is where they are developed; affordable, with no accounts.
- Models selected separately by capability; no provider lock-in. The operator's keys never reach the browser. In the Mac app a user's own key is kept in the macOS Keychain and used by the local backend, and goes only to the provider they chose (AI.4); a key held in the browser is only the later optional web-app path.
- Local-first (ADR-011): processing on the device where practical, the user's work stored on their device or in storage they bring, and no accounts. Model costs are paid with the user's own keys; the hosted AI path is optional.

## Primary experiences
1. **Hum → transcribe → arrange.** The user records humming, corrects detected notes/timing, chooses instruments, asks the assistant for accompaniment, auditions changes, and exports.
2. **Beatbox → drums.** Detect onset timing and drum categories, expose confidence and editable events, turn rough mouth percussion into a usable groove.
3. **Sing → tune.** Preserve the original recording, detect notes/pitch contour, optionally select targets, apply natural or stylized correction, compare, and export.
4. **Conversation → musical edits.** “Keep my melody, make the rhythm more playful, add harmony.” Produce an explicit edit plan, respect melody lock, audition and undo it.
5. **Generate professional sounds from the user's own material (planned, ADR-012).** Sampled instruments; in the Mac app, a backing band generated from the user's hummed melody, a voice separated from background music, and a voice turned into an instrument. Each result is an extra part the user can remove, never a replacement for their idea.
6. **Capture an idea on the go (planned, ADR-013).** Open Tandem from the phone's home screen, tap once and sing; the take is kept on the phone with no network or account, and later shared as a file to the studio to be developed.

## User interface requirements
- Record/import; transcription and processing progress/errors.
- Visual notes/timeline; eventually a true draggable pitch-contour editor.
- Beginning scope: two tracks (melody and drums), future multitrack and vocal stems.
- Original/processed playback; explicit correction-strength and instrument controls.
- Music-aware text conversation, eventually spoken conversation.
- Save/open/export portable projects and WAV/MIDI files.
- Hand work on to other music tools through standard files (planned, ROADMAP EXP): separate audio stems and multi-track MIDI for any DAW, MusicXML for notation apps, DAWproject for DAWs that import it, and Web MIDI for keyboards and synths where the browser supports it. Tandem stays a place to start ideas; finishing happens in the user's own tools.

## What currently exists
Browser recording/import, a phone capture page that keeps song ideas on the device and opens them in the studio, or shares one as a single `.tandem.zip` file (the project plus its recording as WAV) that the studio opens with its audio (MOB.1, MOB.3; not yet tried on a real phone), Basic Pitch on-device transcription and server fallback, heuristic beatbox analysis, elementary two-track synthesis, simple note/drum event editing, MIDI/WAV export, local JSON projects, undo/redo across all edits, text AI edit-plan endpoint (requires configured model), basic EQ/dynamics vocal polish, and experimental WORLD pitch correction with +/- semitone vocal note targets.

## What is NOT finished
Phone capture (planned, ADR-013), the Mac app and local AI audio models (planned, ADR-012), bring-your-own AI keys (planned, ADR-011/ADR-012), provider-integrated music generation, robust beatbox classification, studio-grade vocal correction, accurate continuous pitch-contour editor, real-time spoken assistant, high-quality (sampled) instrument sounds, saving projects as files in a synced folder (planned in the Mac app; there will be no Tandem accounts or cloud project storage for now), full Android/Mac end-to-end testing.

## Acceptance criteria
A feature is “working” only after an end-to-end test, not just a successful deployment. For the key journey: record → transcribe → correct → arrange → audition → undo → export, test real microphones, silence, pitch bends, clipping, browser reloads and provider failures. See TESTING.md and ROADMAP.md.
