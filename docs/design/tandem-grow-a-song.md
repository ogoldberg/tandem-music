# Tandem: from a few seconds to a whole song

Design plan, 2026-11-21. Nothing here is built. It is written through the flow redesign (`tandem-flow-redesign.md` in this folder, approved the same day), so each piece has its place in Sing / Your song / Share before it is built. The items are filed in `docs/ROADMAP.md` section 9d, after BEAT.4.

## What was asked

The operator: "How are we taking a brief hum or beat box and turning it into a whole song? Is there a looping or sequencing feature?" Then: "write it up through the lens of our recent redesign so we've already thought through the problems in advance as part of the plan." And, while this was being written: "We should probably also consider reworking the existing tooling if it would better facilitate this new scope of work."

The short answer today: Tandem turns a short take into a short arrangement, the same length as the take. There are tools that repeat notes, but none that repeats the recording, no pattern grid, no loop recording, and nothing that suggests a song's shape. A six-second hum stays six seconds unless the person finds the Timeline, drags a stretch, names it and presses Repeat, and then the voice does not repeat with it.

The person Tandem is for has a song idea, little time and no knowledge of music tools (`docs/PRODUCT.md`).

## How this was checked

- Read on main at 5e1619c: `sections.js`, `phrases.js`, `playhead.js`, `beats.js`, `groove.js` (`barOrigin`, `quantizeProject`, `estimateTempo`), `layers.js`, `takes.js`, `take.js`, `latency.js`, `practice.js` (`createPassSplitter`), `evolution.js` (`contentSeconds`), `daw.js` (`arrangementSeconds`, `sumStems`), `actions.js`, `actions.json`, `sw.js`, the pydantic models in `tandem_backend.py`, and in `index.html`: `edit`, `restore`, `songParts`, `scheduleSong`, `playback`, `renderParts`, the Record handler, `addLayerTake`, `addTakeRecording`, `checkProject`, the starter beat and section handlers. Read `guide.js` `VIEWS` on the UX.5 branch (not merged) to match its shape.
- Ran the pure modules in Node on a made-up six-second hum (nine notes at about 100 beats a minute, the first at 0.31 s, a few hundredths off the beat as a person sings). The numbers in the next two sections are from that run.
- Read `tandem-flow-redesign.md` in full, ROADMAP 9d and the entries for SONG.1, TAKE.1, TRACK.1, PLAY.1, BEAT.1, REC.2, REC.3, AI.6, AI.7, and `docs/DECISIONS.md`.
- Not done: the app was not run in a browser for this plan (the flow redesign walked it at 390 px the same day, and UX.5 is changing those screens now). No real voice, phone or headphones were used. Nothing here judges how a repeated voice, a loop seam or a layered beat sounds. The made-up hum is not singing.

## What exists today

Checked in the code; names are files and functions.

**From a take to notes.** A hum becomes melody notes (`transcription.js`, `contour.js` `sungNotes`). A beatbox becomes kick, snare and hat hits (`beatbox.js` `readBeats`, a port of `analyze_drums`). The speed is found from the onsets (`groove.js` `estimateTempo`; it needs four onsets, else the helper says "Too short to find the speed").

**Around the take.** Chords or a bass line from the melody (`harmony.js` `generateHarmony`), a second voice (HARM.1 to HARM.3), a starter beat (`beats.js` `grooveHits`), a band and voice as instrument in the Mac app, and recorded layers (`layers.js`, up to 8).

**Repeating.**

| Tool | What it repeats | What it leaves |
|---|---|---|
| SONG.1 `sections.js` `repeatSection`, `moveSection`, `deleteSection` | Melody, chords, harmony voice and drums in a marked section (`SECTION_PARTS`), as one edit | Every recording: the take, layers, band, voice as instrument, sung harmony stay where they are (operator decision, 2026-11-15) |
| `phrases.js` `copyPhraseToEnd` | One melody phrase, whole bars later | Every other part and every recording |
| BEAT.1 `grooveHits` | One bar of a groove, written out as hits for 4 to 32 bars or "as long as the song" (`barsToCover`, at least 4, at most `MAX_BARS` 64) | The pattern itself: once written the bar is only hits |
| PLAY.1 `playhead.js` `createPlan` | A marked stretch, in playback only, the recordings included (`scheduleSong` starts each buffer inside the segment) | The project: the loop is studio state |
| PRACTICE.1 `createPassSplitter` | A stretch goes round while the microphone records; each pass is cut out and scored | The passes: only the last can be kept, as a take |
| REC.3 capture page `grooveWindow` | A groove that repeats until Stop | - |

**Recording over the song.** REC.3 plays every unmuted part from the take's zero (`scheduleSong(rc, c.zero, music, {from: 0, ...})`) and moves the take earlier by the round trip (`take.js` `takeStart`, `latency.js`). It always starts at the song's zero. TRACK.1 adds such a take as a layer; TAKE.1 adds it as another take of the voice.

**Missing.** No step or pattern grid (the drums are edited as single hits; `#addhit` adds one a quarter second after the last). No loop recording that keeps passes or layers them. Nothing that proposes a shape (intro, verse, chorus). The recorded voice cannot be repeated or moved. A recording can only start at zero.

## The problems, ranked

What the person with a six-second hum meets, in the guided view at phone width. Numbers are from the Node run on the made-up hum (tempo found: 100; one bar is 2.4 s).

1. **The song is as long as the hum, and nothing says how to make it longer.** After chords and a starter beat the song is 9.8 s (`contentSeconds`). The hub's suggested next (UX.5 `suggestNext`) goes chords, a beat, Share. There is no step between "it has a beat" and "send it" for "it is ten seconds long".
2. **Repeat leaves the voice behind.** Marking the hum as a section and pressing Repeat three times gives four copies of the notes (36 melody notes, 28.8 s of drums) and one copy of the voice, at the start. "My voice in it" then plays the voice once over the first quarter of the song. The status line says so; it does not help.
3. **The way to Repeat is five steps a new person will not find.** Open the Timeline fold, drag across it, pick a name, Mark section, Repeat. In UX.7's plan Sections sits under More. `copyPhraseToEnd` is under Notes: More tools and copies the melody alone, so chords and drums do not follow.
4. **The parts do not end together.** The hum ends at 5.6 s, the chords at 7.3 s (three bars from where the bar starts, 0.28 s) and the starter beat at 9.6 s (four bars, the least `barsToCover` gives). A section marked by hand is snapped to the beat, not the bar (`snapToBeat`), so a repeat can start mid-bar.
5. **A second idea has nowhere to go.** A chorus hummed after the verse can only be recorded from the song's zero. As a take it replaces what the voice is; as a layer it is not the voice (no clean-up, no pitch fixing, TRACK.1's open point). There is no "sing the next part here".
6. **A beat is one bar, or a take.** A person who wants the kick somewhere else has `+ Hit` and a number. A beatboxer cannot build a beat the way beatboxers do: kick and snare first, then the hat over it, round and round.
7. **The first try is the only try.** Recording a part means one pass after the count-in. Practise loops a stretch and records every pass, but for scoring, and keeps one.
8. **A grown song would hit limits no one meant for it.** Each part holds 1,024 notes or hits (`sections.js` `MAX_EVENTS`, the lists in `ChatProject`). A straight beat is 12 hits a bar, so the drums stop at 85 bars: 3:24 at 100 beats a minute, 2:26 at 140. A starter beat stops at 64 bars.
9. **The bar grid is worked out again on every use.** `barOrigin` reads the onsets each time. On a short free-time hum it is close to a toss-up (0.28 s here), and an edit that adds or moves notes can flip it, after which chords, beat and sections no longer agree.
10. **The files do not say where the verse is.** MIDI, MusicXML and DAWproject carry no section names (SONG.1's open point), so the shape is lost on the way to GarageBand.

What works and is kept: the whole path from take to notes; chords and the starter beat as ordinary notes and hits; one `edit` per action; sections as a list in seconds; playback as a plan of segments; the layer and take stores; the count-in and the round-trip measurement.

## What to change in today's tools

The operator asked that today's tools not be treated as fixed. Each one that touches growing a song, judged by whether changing it makes the new scope simpler and more reliable for the person and for the code.

| Tool | Verdict | Why |
|---|---|---|
| SONG.1 `sections.js`: the list, Repeat, Move, Delete | **Keep the model, rework the rule and the surface** | Sections as `{name, from, to}` over one line of notes is right (see "one line, not patterns" below). The rule "recordings stay where they are" is what breaks problem 2 and is replaced by "recordings are never changed; where they play is" (GROW.3). The surface (drag on the Timeline) moves under More; blocks become the everyday way (GROW.4). |
| The note-parts-only rule | **Replace** | With placement (below) a section edit moves the notes and where the recordings play, in one edit. No audio file is cut or rewritten, which is what the 2026-11-15 decision protected. |
| `phrases.js` `copyPhraseToEnd` | **Keep, stop offering it in the guided view** | It is a note tool for one part. In the guided view "repeat this" must mean every part, so Notes: More keeps move and transpose and loses Copy to end there; it stays under Show every control. No code change. |
| PLAY.1 loop (`createPlan`, `loopRegion`) | **Keep as is** | A playback loop that is not in the project is exactly what choosing a block needs. It becomes "play this part round" in the Song shape view. Loop recording reuses its segments. |
| BEAT.1 `grooveHits` | **Keep hits as the truth; add a reader** | A stored pattern beside the hits would be two truths, and every exporter and the chat read hits. Instead `barPattern(drums, bar)` reads any bar back into steps and `withPattern` writes steps into chosen bars (SEQ.1). `MAX_BARS` rises with the limits (GROW.2). |
| TRACK.1 `layers.js` | **Keep; add placement** | A layer stays a whole recording with its own strip. It gains where it plays (GROW.3), so a layer recorded in a part repeats with the part, and can start at a part instead of zero. |
| TAKE.1 `takes.js` comp | **Small rework** | A comp section is `{take, from, to}` and assumes the take's time is the comp's time. A part sung later is a short take that belongs later in the voice, so a section gains an optional `src` (where in the take it starts; left out when it equals `from`). Everything else stands (GROW.6). |
| `practice.js` `createPassSplitter` | **Move, unchanged** | It is the loop-recording core. It moves to `take.js` so Practise and loop recording share it (LOOP.1). |
| Beatbox reading (`beatbox.js`, `analyze_drums`) | **Keep** | Growing does not need a better reader, and BEAT.3 already reworks the kit and levels. The line-for-line port and its fixture stay untouched. |
| The bar grid (`barOrigin`, `BEATS_PER_BAR` in six modules) | **Rework** | One module owns bars (`bars.js`); once the song has blocks the grid is pinned in the project instead of guessed each time (GROW.1). 4/4 stays the only time (3/4 was left out on 2026-11-18 and still is). |
| The limits (1,024 a part, 64 bars of beat) | **Rework** | Raised for the studio; the chat keeps its own cap and says so (GROW.2). |
| REC.3 Record (always from zero) | **Extend** | Record gains a start time and a stop time, so a part is recorded where it goes after a bar of the song as the count-in (GROW.6). The latency path is unchanged. |

**Migration for every rework.** The format stays `"version": 1` and each new field is optional and written only when used, as `mix`, `layers`, `takes` and `sections` are, so a project, a version, a Tandem file or a DESK.3 folder saved today opens, saves and exports byte for byte as before (a fixture test per field, as `tests/fixtures/genre-none.json` does for the genre). Each field gets its `clean...` function in the pure module and its pydantic mirror with `extra="forbid"`, added to `ChatProject`. The other direction is new: `checkProject` and `projectFields` in an older shell drop an unknown top-level field without a word, and `cleanTakes` refuses an unknown key. A phone and a Mac can be on different versions (ADR-013's hand-over). So GROW.1 adds an optional `uses` list to the project (the names of the optional features a file needs: `grid`, `placed`, `comp-src`), and from then on a shell refuses a file whose `uses` names something it does not know, with "This song was made with a newer Tandem. Update, then open it again." Shells older than GROW.1 cannot be fixed; they will open such a file without its repeats, which is accepted for an alpha and said in `docs/TESTING.md`.

**Tests that pin today's behaviour and must change on purpose.** `tests/sections.test.mjs` and `e2e/test_sections.py` (recordings stay; the status line after an edit), `tests/takes.test.mjs` (comp keys), `tests/groove.test.mjs` and `e2e/test_bar_grid.py` (`barOrigin`), `tests/beats.test.mjs` (`MAX_BARS`), `tests/practice.test.mjs` (the splitter's import), `tests/actions.test.mjs` and `tests/test_actions.py` (the prompt held byte for byte; the list caps), `e2e/test_guided.py` and the control-inventory test (new controls). Each item names its own.

### One line, not patterns

The largest choice. Loop apps keep patterns and an arrangement that points at them (Koala's sequences, GarageBand's cells; see "What is borrowed"). Change the pattern and every use changes. Tandem keeps one line of notes per part, and every exporter, the chat, the rolls, undo and the melody lock read that line.

**Decision: the song stays one line. A repeat is a copy.** Reasons: nine consumers read flat lists today (playback, `renderParts`, MIDI, MusicXML, DAWproject, the chat, the rolls, Practise, Fit) and a pattern layer would put a flattening step in front of each, or two truths in the project. A person who sings usually wants the second verse a little different, which copies allow and pointers fight. What pointers give ("fix the chorus once") is given by an explicit edit: sections with the same name and length are the same part, and **Make every Chorus like this one** copies one over the others (GROW.5). No new field is needed for that: the name is the link.

For recordings the answer is the other way round, because copying audio costs storage and re-running clean-up and pitch fixing on every repeat costs minutes on a phone. **Recordings are placed, not copied** (next section).

## The proposed design

### In one paragraph

The song is a row of **blocks** (SONG.1's sections, each a whole number of bars). The first block is the idea. The person makes the song longer by repeating a block, adds a new part by singing into an empty block, and changes the order by moving blocks; everything in a block goes with it, the voice included. A beat can be edited as a grid of steps. A part can go round while the person tries it again, or builds it in layers. One button proposes a whole shape from the parts that exist. Nothing invents a tune the person did not sing.

### Recordings are placed, not cut

A new optional project field `placed`, keyed like `mix` (`voice`, `band`, `timbre`, `voice2_sung`, `layer-<id>`): for each recording, a list of clips `{from, to, at}`. `from` and `to` are times in the recording; `at` is where that stretch starts in the song. No entry means the whole recording at zero, which is today. A pure `placement.js` holds `cleanPlaced`, `placeSamples` (the recording laid out along the song with 20 ms equal-power crossfades at the joins, the maths `renderComp` uses), `placeSegments` (what `scheduleSong` must start inside a playback segment), `placeNotes` (notes read from a recording, carried to every place it plays) and the three section operations on clips, which `sections.js` calls beside its note edits.

- The voice is one channel: the take and what clean-up, pitch fixing and Separate make from it all share `placed.voice`, so the pitch-line editor, Tune's targets and the helpers keep working on the recording in its own time, once, however many times it plays.
- A recording made from the take (the sung harmony, voice as instrument, a band that follows the recording) starts with the voice's clips. A band played from the notes is made in song time and starts with none.
- Play, Export WAV, the stems, Hear how it grew and the DAWproject audio tracks all read recordings through one function, so they cannot disagree.
- Repeating costs no storage and no processing.

### Where it lives in the flow

**Your song (the hub).** Under Play, the player card shows the song's blocks as a thin strip (tap one to play from it). A new tile in Add to it, after Sound: **Song shape**, with the state line "One part, 0:10" or "Verse, Verse, Chorus, 1:12". `suggestNext` becomes: chords, then a beat, then Song shape while the song is one block, then Share. The Sections view planned in UX.7 under More is this view; its Timeline tools become the view's More. The views stay twelve.

**The Song shape view** (the same frame as every change view):

- Player: Play plays the song. With a block chosen, Play plays that block round ("Plays Verse, round and round"); this is PLAY.1's loop.
- Everyday controls: the blocks as a row of large chips with their names and lengths. Chosen block: **Play it again after this** (Repeat), **Earlier**, **Later**, **Remove**, a name menu (Verse, Chorus and the rest of `SECTION_NAMES`). Under the row: **Add a new part** and **Make it a song**.
- On first opening, with no sections, the view shows the whole song as one block, "Your idea", and nothing is written. The first action writes the block and pins the bar grid in the same edit.
- More: the Timeline (mark a stretch by dragging, unmark), Make every Verse like this one, Hear how it grew.
- Before / After (UX.6): Before is the project when the view opened. `placed` and `sections` are in the project, so `renderParts` on the snapshot plays the earlier shape with no extra work. Put it back undoes this view's edits. A part recorded in the view is one of those edits; its audio stays in `generated` by id until the clean-up collects it, so Redo finds it.

**Add a new part** (in Song shape). An empty block of 4 or 8 bars after the chosen one, with the beat carried on (the bar before it, read by `barPattern`) and, if asked, the chords of another part copied in. Then **Sing this part**: the bar before the block plays as the count-in with the song, the block is recorded once (or round and round, LOOP.1), and it plays back in the view at once: listen first, then **Keep it**, **Again** or **Throw it away**. Keeping it is one edit: the take joins the voice (a comp section with `src`), `placed.voice` gets its clip, the helpers the person has on run for that stretch (clean-up, notes, pitch fixing), and its notes go into the block. The record button in the view drives `#record`, as BEAT.4's does.

**Beat view.** Under the four starter beats, one bar as steps: three rows (kick, snare, hi-hat), sixteen steps drawn as two lines of eight so each is a full touch target at 390 px (a shuffle bar shows twelve). Tapping a step is one edit. A choice says where it is written: this bar, every bar of this part, the whole song. Hits that sit off the steps (a beatboxed bar) are drawn where they are and snap only when touched. Under More: **Build it in layers** (LOOP.2).

**Sing step and Your take.** Unchanged for a first take. Once the song has blocks, the Sing step's record button offers "Sing a part" (opens Song shape) beside singing the whole song through (see open question 4).

**Share.** "In your song" (UX.8) gains a first line with the shape, and its Change link opens Song shape.

**Ask Tandem.** "Play the verse twice, then the chorus" becomes possible (GROW.9); until then the chat reads the sections and says it cannot change them, as today.

**Desktop (Show every control, UX.9).** The Sections band under the Timeline is the same element as the guided row of blocks and carries the same buttons. The voice lane and each layer lane draw their clips, so a repeat is seen. The drums panel gets the step grid. In the wide two-pane guided layout the hub's strip stays on the left while Song shape is open on the right.

**Capture page.** No change. An idea opens in the studio as one block.

### What Play plays, view by view

| Where | Play |
|---|---|
| Your song | The song, from the block tapped on the strip |
| Song shape, nothing chosen | The song |
| Song shape, a block chosen | That block, round and round |
| Song shape, after recording a part | The new part with the song under it, round and round, until Keep it |
| Beat, step grid | The bar being edited with the other parts, round and round, so a step is heard on the next pass |
| Make it a song, before Keep it | The proposed shape (a trial project, as Create harmony's Try another is) |

## What is borrowed

Only from pages read for this plan on 2026-11-21.

- **GarageBand for iPhone, song sections** (support.apple.com/guide/garageband-iphone/extend-a-song-with-song-sections-chs3c3ef5dc/ios, read directly). "By default, the first section of a new song is 8 bars long"; a section can "automatically fit the length of your recording"; Duplicate adds the copy after the last section; sections are reordered by dragging in a list. Borrowed: sections in whole bars, a first block that fits what was recorded, 4 or 8 bars for a new part, and a list of blocks as the way to reorder. Changed: a copy goes right after the block it copies, as SONG.1 does, because that is where a second verse goes.
- **GarageBand for iPhone, Live Loops** (support.apple.com/guide/garageband-iphone/chs02aae0e6b/ios, read directly). A performance of tapped cells is recorded into Tracks view, each cell "from the beat (time position) when they start playing". Borrowed: whatever loops ends up as ordinary material on the song's line, not in a second place. Not borrowed: the cell grid. It is a second model of the song beside the tracks, built for loops from a library, which Tandem does not have.
- **Koala Sampler, sequences** (metawork-studio.github.io/koala-documentation/mobile/5-sequence, read directly). "Record mode overdubs sequences on top of previously recorded material"; DOUBLE UP "doubles the length of the selected sequence, duplicating all notes and settings"; quantize is to the nearest sixteenth and can be off; switching sequences waits for the beat, the bar or the sequence's end (SEQ SNAP); with auto-play "a row of sequences plays back as a song". Borrowed: layering while it goes round (LOOP.2), repeat as a doubling in one tap, changes taking hold at the next bar while a block loops, and a row of parts being the song. Not borrowed: pads and slots as the home screen.
- **Ableton Note** (ableton.com/en/note, read directly). "Note will restore what you played and create a loop - no need to press record beforehand"; "Double your loops to create variation within clips"; a section of a loop can be isolated to work on. Borrowed: the idea is a loop the moment it exists (the first block is there without marking), and varying a copy is the way to a second verse. Not borrowed: capture without Record; a microphone that is always listening is not what a person expects of a web page.
- **BandLab, Looper** (musicradar.com/news/bandlabs-looper-takes-mobile-beatmaking-to-the-next-level, read directly; BandLab's own help pages refused the fetch and are known only from search extracts). Loop packs triggered by tapping, where "everything automatically syncs up so that it's always in time and key". Not borrowed: it plays ready-made loops, and Tandem's rule is the person's own idea. The search extracts say BandLab's cycle bar loops a region while recording takes; that matches LOOP.1 but was not read first-hand, so it is not relied on.
- **Groovepad.** No source was found or read. Nothing is taken from it.

## The problems thought through in advance

Each with the decision.

1. **Undo.** One `edit` per action: Repeat, Move, Remove, Add a new part, Keep it (the take, its clip, its notes and its block together), a step tapped, Make every Verse like this one, Keep this shape. A loop-recording session is not an edit; keeping a pass is. In LOOP.2 each kept layer is one edit, so Undo takes layers off one at a time, and the audio stays in `generated` for Redo. `restore` already calls `syncComp`; it gains nothing new because `placed` is plain project data.
2. **Repeating recordings against SONG.1's rule.** The rule's purpose was that no recording is ever cut or spliced. That holds: files are never rewritten. What changes is that where a recording plays follows the section edits. This reverses the wording of an operator decision (2026-11-15), so it is recorded as ADR-018 and listed under the open questions as decided on the standing instruction. Old songs with sections and a recording do not change by themselves; the next section edit moves both.
3. **Takes and comps.** The comp stays the voice in its own time. `placed.voice` maps that time to the song. Use and Comp in keep working on the comp; the clips do not care which take is under them. Removing a take that a clip plays leaves silence there, said in the Takes view. A part sung later is a take comped in after the idea (`src`), so clean-up and pitch fixing run on new material only.
4. **Layers.** A layer recorded in a block is placed at that block and repeats and moves with it. A layer read into the melody, chords or drums has its notes carried to every place it plays (`placeNotes`).
5. **Audio by id.** No new store. Takes and layers are in `generated` by id and linked from the draft and versions as today; `placed` holds no audio. The recording clean-up keeps what the project lists, as now. Bundles and DESK.3 folders write the same files; only `project.json` grows.
6. **Recordings made from other things.** The sung harmony, voice as instrument and a band from the recording are in the take's time and start with the voice's clips. They are not re-made when the song is rearranged. Where a repeat's notes were changed afterwards, the voice in it is still the same audio; the view says "your voice is the same in each Verse" once, and singing that block again is how to change it.
7. **Bar grid and free-time takes.** The first block edit pins the grid: optional project field `grid` `{origin}` in seconds, the value `barOrigin` gives at that moment. From then on `barOrigin` returns it. Blocks are whole bars long. A tune with a pickup (notes starting less than a beat before a bar line) keeps it: the block starts at the pickup, so its edges sit that much before the bar lines and it is still whole bars long. Anything before the first block (silence before the first note) is a lead-in and is never repeated. A free-time hum repeats with the same small error against the beat in every copy, which is better than an error that grows; whether that error is acceptable to the ear is the operator's to judge (open question 7).
8. **The speed after growing.** Changing `bpm` does not move notes or audio (decided 2026-11-18), so a new speed would leave the blocks off the bars. Decision: once the grid is pinned the speed can only be doubled or halved (bar lines stay bar lines), and the Timing view says why. Undo back before the first block edit frees it. TEMPO.1 (tap the speed) is the way to get it right before singing.
9. **Parts that do not end together.** The last block always runs to the end of everything, rounded up to the bar, so nothing sits outside the blocks of a grown song. With a three-bar tune under a four-bar beat the first block is four bars. The view offers the shorter length as a choice ("3 bars, as sung"), which trims the beat's extra bar in the same edit.
10. **Latency in loop recording.** Passes are cut exactly as Practise cuts them: the splitter's zero is `takeStart(zero, round trip)`, with the round trip measured (REC.3 Measure) or estimated. In LOOP.2 a layer must be heard on the very next pass, but its last stretch (as long as the round trip) has not arrived when that pass starts. Decision: the layer is scheduled in two pieces, the body at the pass's start and the tail when it arrives, and a loop shorter than two seconds is refused for layering (the round trip is believed up to one second, `MAX_LATENCY`). Seams use the 20 ms crossfade.
11. **Phones and headphones.** Without headphones the song leaks into the microphone and every layer contains the ones before it (REC.3 already asks for headphones; echo cancelling stays off because it damages the voice). Decision: LOOP.2 asks the question plainly before starting ("Are you wearing headphones?"). No: it offers to build the beat with the click only, each layer recorded alone, and says the layers were not heard together while recording. Bluetooth works when measured, with a round trip the calibration window covers (0.7 s). None of this has been tried on a real phone.
12. **Exports stay aligned.** Recorded stems are rendered through `placeSamples` before `fitted`, so each stem is the length of the song from zero and Export WAV is still their sum (the test that sums the stems is extended with a placed voice). The MIDI file, MusicXML and DAWproject note tracks read the note lists, which repeats already wrote out. DAWproject audio tracks are written placed, from zero, as today's are. Section names go into all three files (GROW.8), with the fixtures regenerated and validated against the vendored schemas.
13. **Project schema.** New optional fields, each written only when used: `grid` `{origin}`, `placed`, `takes.comp[].src`, `uses`. Mirrors: `ProjectGrid`, `ProjectPlaced` and `PlacedClip`, `CompSection.src`, `ChatProject.uses`, all `extra="forbid"`. `placed` keys are checked like `ProjectMix`'s layer keys. Clips: at most 64 a recording, times within 600 s, `to` after `from`, clips of one recording not overlapping in the song. No AI action edits `grid`, `placed` or `takes`.
14. **Limits.** Studio caps rise to 4,096 notes or hits a part and 256 bars of starter beat; 600 s and 32 sections stay. The chat cannot carry that (262,144 bytes a request, and a long prompt is slow and costly on a small model), so `ChatProject`'s lists stay at 1,024 and a longer song is refused by the studio before sending, in words ("This song is too long for Ask Tandem to read yet"), never sent cut short. GROW.9 lifts that by sending each repeated part once with the shape.
15. **AI actions.** New registry entries only in GROW.9: `repeat_section {section, times}`, `move_section {section, to}`, `name_section {section, name}`, each one `actions.json` entry and one `actions.js` handler that calls the studio's own function (ADR-017's pattern). No action deletes a section. A reply stays one edit.
16. **The melody lock.** Repeating a section copies melody notes, so by ADR-016's rule (the parts an action changes) the lock would drop it. But the lock exists so that an instruction about accompaniment does not rewrite the tune, and a repeat rewrites nothing. Decision: an action may be declared `"arranges": true`, meaning it only copies or moves whole sections of every part alike; the lock keeps such actions, and `MELODY_LOCK_NOTE` says so. This amends ADR-004 and ADR-016 and is part of ADR-018. Outside the chat the lock never applied to the person's own edits.
17. **Service worker and routes.** New modules: `bars.js`, `placement.js`, `shape.js` (blocks and proposed shapes), `steps.js` (the step grid), `looprec.js` (pass and layer scheduling). Each needs its `FileResponse` route in `tandem_backend.py`, its entry in `sw.js` `ASSETS` (the page imports them statically and cannot start without them), its line in `CLAUDE.md` and its Node test in the list CI runs. No worker, no inline script, no `eval`: the capture worklet is the existing Blob URL one, which the Content-Security-Policy already allows.
18. **Performance on a phone.** Repeats add no audio and no processing. What grows is the note count: the rolls draw a DOM element a note and `update()` redraws on every edit, and each undo step is a JSON snapshot of the project (100 kept). A three-minute song is a few thousand events and a few hundred kilobytes a snapshot. Decision: GROW.2 measures `update()` and one undo step on a 4,096-event song under Playwright's CPU throttling and sets a budget in the test; drawing only the visible stretch of a roll is done only if the budget is missed. Before (UX.6) renders offline, and a placed voice adds one pass over the samples.
19. **Offline.** Everything here runs on the device. Nothing new calls the server. The Mac app's models are not used. Loop recording needs only the microphone.
20. **No mock, no fallback.** Make it a song arranges what exists and runs the studio's real generators (chords, starter beat, fills, intro, ending). It never writes a placeholder melody into an empty part and never fills a part with a canned tune. An empty block has a beat and silence where the tune goes, and the tile says "Chorus: not sung yet". If a generator cannot run (no tempo, no melody) the proposal leaves that piece out and says so.
21. **What a repeat sounds like at the seam.** A voice note held across the end of a block is cut with a 20 ms fade when the block repeats. Notes keep their length and may ring into the next block, as SONG.1 does now. Unverified by ear.
22. **Sing the whole song through.** After growing, a take from the song's zero is in the song's time, not the voice's. Decision for the first build: it is kept as a layer named "Whole song", heard beside or instead of the placed voice by the mixer. Making it the voice (one take, no clips) is a later choice; see open question 4.
23. **Read the notes again.** In a grown song Transcribe reads the recording in its own time and `placeNotes` carries the notes to every clip, in one edit, so the melody is not cut back to the idea.
24. **Hear how it grew.** The take stages are placed like every other recording, so each stage is as long as the song. A stage for "the idea, once" before "the idea, repeated" is not added.
25. **ADR.** One is needed, ADR-018, filed with GROW.3: the song stays one line of notes and a repeat is a copy; recordings are placed and never rewritten (amends SONG.1's rule of 2026-11-15); the bar grid is pinned once the song has blocks; `arranges` actions pass the melody lock (amends ADR-004 and ADR-016, takes effect with GROW.9).

## Open questions

Decided on the operator's standing instruction to take the recommendation (2026-11-21), unless marked as needing the operator.

1. **Should the recorded voice repeat and move with its section?** This reverses the wording of the 2026-11-15 decision. Recommended and taken: yes, by placement, with no file ever rewritten (ADR-018). The operator can stop this before GROW.3 is built; GROW.1 and GROW.2 do not depend on it.
2. **Patterns or one line?** Taken: one line; a repeat is a copy; "make them all alike" is an explicit edit.
3. **Where does it live?** Taken: a Song shape tile in Add to it, replacing the Sections view under More; the strip of blocks on the player card.
4. **Singing the whole song through after growing.** Taken for the first build: it becomes a layer. Left open until it has been used: whether it should instead become the voice.
5. **How long is a new part?** Taken: 4 bars, with 8 as the other choice, and the length follows the recording if the person sings past it (to the next whole bar).
6. **May the chat rearrange sections with the melody lock on?** Taken: yes, for whole-section copies and moves only; never delete.
7. **Does a repeated free-time hum sound right against the beat, and are the seams clean?** Needs the operator: a listening check on real singing, on the Pixel and on the Mac. If the answer is no, the first block edit should offer "line the tune up first" (the Timing view) before repeating.
8. **Does layering round a loop work on a phone?** Needs the operator: a physical test with the phone's speaker, wired headphones and Bluetooth headphones on the Pixel (and an iPhone under MOB.4). LOOP.2 is not to be called working before it.
9. **Is a first-time person helped by Make it a song, or does it feel like Tandem wrote the song?** Needs the operator, or someone new to Tandem (HUMAN), judging the proposal screen.
10. **The first block's length when the tune and the beat differ.** Taken: cover everything, offer "as sung" as a choice. Which default sounds right is part of question 7's listening.
11. **Shells older than GROW.1 opening newer files.** Taken: accepted and documented; the `uses` guard protects from GROW.1 on.
12. **3/4 and other times.** Taken: still out, as on 2026-11-18. `bars.js` is the one place it would go.

Nothing here needs money or a key.

## A split into buildable items

In build order. Each leaves the app working. GROW.1 to GROW.3 are the reworks and change nothing a person sees except that a section edit now carries the voice. The items are filed in `docs/ROADMAP.md` section 9d after BEAT.4, in the same words.

1. **GROW.1** One bar grid, pinned once the song has a shape. `bars.js`, `grid`, `uses`.
2. **GROW.2** Room for a whole song. The limits and the phone budget.
3. **GROW.3** Recordings follow the song: placed, never cut. `placement.js`, `placed`, ADR-018.
4. **GROW.4** Song shape: the song as blocks, and Play it again. Depends UX.7.
5. **GROW.5** Change one Verse, change them all.
6. **SEQ.1** The beat as a grid of steps. Depends UX.5.
7. **GROW.6** Add a new part and sing it. Record from a time; `src` in the comp.
8. **LOOP.1** Round and round until it is right: keep the best pass.
9. **LOOP.2** Build a part in layers while it goes round. Depends BEAT.4.
10. **GROW.7** Make it a song: a whole shape proposed in one tap. Depends SONG.3, BEAT.2.
11. **GROW.8** The shape in the files: section names in MIDI, MusicXML and DAWproject.
12. **GROW.9** Ask Tandem to shape the song. Depends AI.2.

## Risks

- **GROW.3 touches every reader of a recording.** Playback, `renderParts`, the stems, Hear how it grew, DAWproject, Record over the song, Practise's backing. The safety net is that no entry means today's behaviour, held by the existing tests unchanged, and one function all readers call.
- **Two time lines for the voice.** The take's time and the song's time differ once a block repeats. Every tool that shows the voice (the waveform, the pitch-line editor, the Takes view) must say which it shows. The plan keeps the editors in the take's time and draws the clips only in the voice lane.
- **Loop layering may not survive a phone's speaker.** If the physical test fails, LOOP.2 ships as headphones-only or not at all; LOOP.1 and the rest do not depend on it.
- **The hub gets a ninth tile.** The flow redesign's own risk ("twelve is still twelve") applies. Song shape replaces Sections, so the count of views does not rise.
- **This plan was made from the code, not from a person using it.** The ranking of problems is from reading and a made-up hum.
