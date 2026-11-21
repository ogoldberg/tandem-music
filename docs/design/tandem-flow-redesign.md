# Tandem: listen first, then one kind of change at a time

Design review of the whole guided flow, 2026-11-21. Canvas: `tandem-flow-redesign.html` in this folder (open it in a browser; its screenshots are embedded). The walk scripts, the raw screenshots under `shots/` and the measurements they name stayed with the review and are not in the repository; the numbers quoted here are from them. The operator approved this design with no changes on 2026-11-21 (see the end); the items are filed in `docs/ROADMAP.md` section 9d, ahead of MIX.2.

## What was asked

The operator tried the live guided view on an Android phone and said: "The current UX feels weird and hard to understand. After I record something I want to listen to it and then be given the opportunity to make changes. The way it is right now doesn't make it clear how to do that. And then maybe the editing piece should be broken into a view for each type of change with the ability to move back and forth between features just for the sake of simplicity." And: "Let's draw inspiration from other apps that break down complex processes into simple step by step flows without losing functionality."

The person Tandem is for has a song idea, little time and no knowledge of music tools.

## How this was checked

- Read `index.html` (the `#guide` element; `showStep`, `runHelpers`, `guideRefresh`, `relocate`; `<main id="allcontrols">`), `guide.js`, `docs/PRODUCT.md` and the UI.1, UI.2, UX.1, UX.2 and UX.3 entries in `docs/ROADMAP.md`.
- Ran the app from main (commit 5b1c1c7) and walked it in headless Chromium at 390 x 844 with touch and a fake microphone: first open, Try an example, each step, Settings, Show every control on the phone and the desktop studio at 1440 x 900 (`walk.py`), then a take with Singing with words chosen: the count-in, seven seconds of a hummed scale played into the fake microphone from a WAV file, Stop, the helpers, and each step after it (`walk2.py`). Screenshots are in `shots/`, measurements in `shots/log.json` and `shots/log2.json`. A first take with Chromium's own beeps gave "Nothing was heard in the take", which is the right answer to beeps.
- Listed every control with an id in `index.html` (246) with `inventory.py`, and mapped each to the new flow with `control_table.py`, which fails if an id has no row.
- Not done: no real phone was used (the operator's own test on the Pixel is the device evidence), and a fake microphone's tone is not singing, so nothing here judges how good the notes or the pitch fixing are.

## The problems, ranked

Measured at 390 x 844 in headless Chromium (numbers from `shots/log.json` and `shots/log2.json`). Screenshots with numbered marks are frame A of the canvas.

1. **After Stop nothing plays and nothing changes: there is no Play on the screen.** The take's whole result is one status line, "Done. Check your notes next." The record button says "Tap to record" again and the page is otherwise the one from before recording (`shots/31-after-take.png`). `index.html` says it in a comment: "the Sing step has no Play button". What Tandem did to the take (cleaned up, pitch fixed, 13 notes, speed found) is listed at 809 px of the 844 px screen, behind the fixed bottom bar. This is the operator's first sentence, exactly.
2. **Hearing is in a different place, with a different meaning, on every step.** Sing: none. Notes: "Listen to: My voice / The notes / Both" and a square, four small buttons under a label. Song: "Play the song", 1,052 px down a 1,577 px page, so chords are added at the top and heard more than a screen lower. Share: only "Hear how it grew", which is not the song. UX.2 has already moved the Notes buttons above the roll, and the operator still could not find how to listen: the trouble is not the order inside a step, it is that listening is not where the person is.
3. **Two long pages hold many unrelated kinds of change.** Notes is 1,464 px (1.7 screens; 2,143 px with its two folds open) and holds eight: key and speed, listening, note editing, More tools, words, the Timeline and sections, Fix my singing (at 1,021 px, on the second screen) and Line up with the beat. Song is 1,577 px (1.9 screens) and holds genre, melody sound, chords or bass, a second voice, drums, my voice in the song, Play and the chat. Neither order is an order of work. This is the operator's second sentence.
4. **There is no before and after.** PRODUCT.md promises "reversible edits, A/B comparisons". With Singing with words the pitch is fixed automatically, and the guided view then has no way to hear the take as it was sung (My voice plays the best take; the Original button is only under Show every control). After adding chords or lining up the timing the only comparison is Undo, play, Redo, play, with two small arrows at the top.
5. **The steps are named for Tandem's data, and the bar pushes a march.** "Notes" and "Song" are what the project file contains, not what a person wants to do. "Next: check your notes" is live before anything is recorded and while recording. Making a song is not a line: the views depend on each other, and people go back.
6. **102 of the studio's 186 controls cannot be reached from the guided view.** Changing a chord, every level and mute except the voice's, takes and comping, recorded layers, the pitch-line editor, the recording options (count-in, click, pitch guide, latency), phrases, the saved versions list, the AI connection. The two Mac app cards (band, voice as instrument) are buttons that leave the guided view. The way to these on a phone is Show every control: 4,031 px, 4.8 screens of the desktop studio stacked.
7. **The same choice is in two places, and neither is where its effect is heard.** How much pitch fixing: a slider on Notes and a menu in Settings. The beat style: buttons on Notes and a menu in Settings. The clean-up style: only in Settings. Settings is a tidy screen, but nothing on it can be listened to.
8. **Record a beat replaces the sung take.** The Song step's Record a beat warns that the beat take will replace the recording (the song is kept as a version first). Recorded layers (TRACK.1) made this unnecessary, but the guided view does not use them.
9. **Smaller things.** On first open the "When you stop, Tandem will" card is cut off by the bottom bar, so the promise is the part not seen. The three "What are you recording?" cards put the record button halfway down the first screen. On a phone the rail's one-line summaries are hidden, so the rail never says "Recorded 0:07". The Share step cannot play the song it is about to send. There is no elapsed time while recording.

What works and is kept: the record button with its count-in and live pitch; the plain words; the automatic helpers and their settings; the Share step's layout; the rule that guided controls drive the studio's own; Show every control as the complete surface.

## What the draft direction gets right, and what this changes

The draft (an earlier UX.4 / UX.5 roadmap draft, not filed) proposes a Your take screen after recording, then Make changes as a list of nine kinds with Back / Next / Done, and a rail of Sing, Change, Share. Its two main ideas are right and are kept: a listen-first screen, and one view per kind of change built from the studio's own controls. Five things are changed:

1. **A hub with spokes, not a nine-step line.** Back / Next through nine screens makes the changes look like a sequence. They are not: a new key changes the chords, an edited note changes what pitch fixing aims at, the speed changes the beat. Nielsen Norman Group's advice on step-by-step flows is exact on this: showing a few options a step "is useful when you can divide a task into distinct steps that have little interaction" and "problematic when the steps are interdependent and users must alternate between them". So the home is a screen (Your song) with Play and the kinds of change on it; a kind opens, and Done comes back. Prev / Next stay as a convenience, and the title of a view opens a menu to jump to any other.
2. **Listening is the home, not a moment.** The draft's Your take screen is passed once and left behind. Here the hub itself starts with Play, and every change view has the same player at the top. The operator's sentence has two halves, "listen to it" and "then make changes"; both should be true on every screen after recording.
3. **Before / After has a definition.** The draft says "Compare (before and after this view's changes)". This fixes what it means and how it is built: Before is the song as it was when the view was opened (the undo history already holds that snapshot, and `renderParts(p)` already renders any project), a switch and not press-and-hold, and Put it back undoes exactly this view's edits. In the Voice view Before is the take as sung.
4. **The kinds are grouped and two are renamed.** Eight kinds in two groups, by what the person wants: Fix your tune (Voice, Notes, Timing, Words) and Add to it (Chords, Second voice, Beat, Sound). "Pitch" becomes **Voice**, because clean-up, "my voice in the song" and taking the voice out of music had no home in the draft's list and are all about how the recording sounds. "Harmony" becomes **Second voice**, the words the guided view already uses, because "harmony" in the studio's code means the chords part. Ask Tandem is not a ninth kind of change: it is a second way to make any of them, so it sits across the bottom of the hub and gets the same view frame.
5. **No Undo per helper on the take screen.** The draft gives each line of "what the helpers did" its own Undo. The history is one line of edits, so undoing the clean-up but not the notes that were read after it cannot be offered honestly. Each line instead opens the view where that thing lives, with Before / After ready.

One thing the draft did not have and the control table exposed: **102 of the studio's 186 controls cannot be reached from the guided view at all today** (the pitch-line editor, changing a chord, every level and mute but the voice's, takes and comping, layers, the recording options, phrases, the saved versions list, the Mac app's band). One view per kind gives each of them an obvious place, under one More fold per view. So the redesign is also what makes "every advanced control stays reachable but is not in the way" (PRODUCT.md) true on a phone without leaving the guided view.

## The proposed flow

Three steps on the rail instead of four: **Sing**, **Your song**, **Share**.

**Sing.** What are you recording (a tune, a beat, with words) as one row; the record button; one line saying what Tandem will do when you stop, ending "and plays it back to you"; Use a recording, Open a saved song, Try an example, New song; a closed Recording options fold (count-in, click, hear the song while you sing, pitch guide, measure the delay, record as a layer).

**Your take** (the second face of the Sing step; opens by itself on Stop or after an import). One large Play and the waveform. Play works at once on the raw take while the helpers run, and their progress is on this screen. When they finish: Hear My voice / As notes / Both; "What Tandem did", each line a link to its view; then one decision: **Keep this take** (to Your song), **Sing it again** (the take stays in the takes list), or Share it as it is.

**Your song** (the hub). A player card: Play, the song's name and length, the key and the speed as chips, "My voice in it". Then the kinds of change as tiles, each saying its present state in plain words ("Cleaned up, pitch as sung", "14 notes", "Not added"), with a dot when it has been used and one marked Suggested next (the first of: chords missing, beat missing, else Share). Under them More (Sections, Takes, Practise) and Ask Tandem. Bottom bar: back to Sing, on to Share.

**A change view.** All twelve have the same frame: a way back to Your song, the view's name (tap to jump to another), Undo and Redo; a player with Play, what Play plays in this view, and Before / After; the view's two or three everyday controls; one closed More with the rest; a bottom bar with the previous view's name, Done and the next view's name.

| View | Everyday controls | Under More |
|---|---|---|
| Voice | Fix my singing (how much, keep my vibrato), Clean up the sound, My voice in the song | The pitch-line editor and its buttons, key and scale for fixing, hear it as recorded, downloads; in the Mac app, take my voice out of the music |
| Notes | The melody roll, Draw, Draw line, Select all, Delete, up and down a semitone, the key as a chip | Octaves, steps in the key, notes that fit the chords, move a phrase, add or clear notes, read the notes again from the recording, play it in on a keyboard |
| Timing | Speed and Find the speed, Line up Gently / Tightly / Swung, the roll showing where notes were | Grid, strength, swing |
| Words | The words box, the roll with the words under the notes | - |
| Chords | Add chords, Add a bass line, the key, the chord names (tap one to change it), Remove | Edit the chord notes |
| Second voice | Create a harmony (Try another, Keep it), Sing it in my voice, Remove | Copy my tune higher or lower, edit its notes, the sung harmony's own controls |
| Beat | The starter beats as four choices, Add this beat, Record a beat | How many bars, keep the hits, add or clear hits, Remove |
| Sound | Genre; one row a part: instrument, how loud, in the song or not | Solo, MIDI out; in the Mac app, the band and voice as instrument |
| Sections | The Timeline open: play from a time, loop a stretch, name, repeat, move and delete sections, Hear how it grew | - |
| Takes | Every take: play, use, remove; join the best bits; recorded layers and what each is read into; Record a part on top | - |
| Practise | Practise, the pass marks on the roll, Keep pass as a take, Ask about this pass, warm-ups, range and progress | - |
| Ask Tandem | Protect my melody, the chat, a few things to try | - |

The melody roll and the Timeline are one element each, so they travel into whichever view is open (Notes, Timing, Words, Practise, Sections). That is why one view at a time is not only simpler for the person but also what the no-duplicates architecture wants.

**Share.** Play (today the Share step cannot play the song it is about to send), "In your song" as a short list with a Change link per line, the name, Share the song, Keep it (the song file, a version, and the saved versions list, which the guided view lacks today), Hear how it grew, Open in other music apps.

**Settings** (the gear, on every screen): the automatic helpers and how each is done, as today; plus the Ask Tandem connection, which today is only under Show every control; Show every control; reset.

**The desktop studio** is unchanged in shape. Its rail takes the same three names; Show every control from a view opens the studio on the matching part, and Guided steps comes back to that view. Later, on a wide screen, the guided view can show the hub and the open view side by side. Frame D of the canvas has the table of which view is which lane and panel group.

## What is borrowed

Details and links are in frame E of the canvas. In short:

- **Voloco:** stopping a recording opens the edit view by itself, and effects stay changeable because they are not baked into the recording. Borrowed for Your take and for clean-up and pitch fixing as things laid over an untouched take. (Read through search extracts of help.voloco.com; the pages refuse automated fetches.)
- **Instagram's photo editor:** a list of named tools, one open at a time, Done to return, a dot under each tool that has been used. Borrowed for the hub, its tiles and the dot. (help.instagram.com/113650522126501, through search extracts.)
- **CapCut:** the preview stays on top while one tool has the lower part of the screen; only tools that apply are shown. Borrowed for the view frame. Not borrowed: icon bars with fine-print labels, which a TechRadar review found hard to read.
- **Lightroom for mobile:** edit panels by kind, and press-and-hold for Before. Borrowed: Before / After in every view; improved by scoping it to the open view, which Lightroom's own users have asked Adobe for; changed to a switch because sound takes seconds to judge. (helpx.adobe.com, community.adobe.com)
- **Apple Photos:** Done keeps, Cancel then Discard Changes drops, and the original is always kept. Borrowed for Put it back. (support.apple.com)
- **TurboTax:** one step in front of the person, plain English, a reason for each thing. Borrowed for the wording, "What Tandem did", the one suggested next tile and the review on Share. Not borrowed: its forced order. (appcues.com, fastcompany.com; the review-with-links screen is from knowing the product, not from those sources.)
- **Nielsen Norman Group:** when step-by-step works and when it does not, and progressive disclosure. The reason for the hub and for one More fold a view. (nngroup.com/articles/progressive-disclosure, read directly.)
- **BandLab:** pitch fixing as an effect with a key and an intensity, applied after recording. Borrowed for the Voice view's one button and one slider. (promo.bandlab.com/autopitch-free-pitch-correction)
- **GarageBand for iPhone:** quick edits inside the simple instrument view without switching to Tracks view, under one undo history. That is already Tandem's guided view and Show every control; the proposal leans on it harder. (support.apple.com/guide/garageband-iphone)
- **Moises:** each part a row with volume and mute. Borrowed for the Sound view.
- Left out, from knowing the apps and not from sources read here: Duolingo (one-task screens fit drills, which Practise already is, not open-ended editing), Suno (makes the song for you, against "the person's idea stays central"), Canva and Splice (template and loop libraries).

## Every control, and where it lives in the new flow

All 246 elements with an id that are buttons, inputs, selects, text boxes, folds, links or forms in `index.html` at 5b1c1c7, in page order. "How" says what has to be built: **guided control, kept** (it exists in the guided view and moves to a new screen), **guided mirror exists** (the studio control is already driven by a guided control), **studio control moved in** (the element itself is moved into the view while the guided view is shown and put back for Show every control, as `relocate()` does now), **button mirror (data-press)** (a guided button that presses the studio's, the mechanism the Share step uses now). Every studio control also stays exactly where it is under Show every control. One guided control is removed (`gkeyspeed`, a fold toggle with nothing left to unfold).

| Control id | What it is | Where it is today | Where it lives in the new guided flow | How | Note |
|---|---|---|---|---|---|
| `grecord` | button: Record | guided step sing | Sing | guided control, kept | Stop now opens Your take |
| `gimport` | button: Use a recording I already have | guided step sing | Sing | guided control, kept |  |
| `gopen` | button: Open a saved song | guided step sing | Sing | guided control, kept |  |
| `gdemo` | button: Try an example | guided step sing | Sing | guided control, kept | opens Your song with Play in view |
| `gnewsong` | button: Start a new song | guided step sing | Sing | guided control, kept |  |
| `gchange` | button: Change | guided step sing | Sing (the "When you stop" line) and Your take | guided control, kept | opens Settings |
| `gkeyspeed` | button: Change | guided step notes | Removed: its job is gone | removed | It only unfolded the key and speed row. Speed is in view in Timing, key in Chords; the two chips on Your song link there |
| `gbpm` | number: - | guided step notes | Timing | guided control, kept |  |
| `gfindspeed` | button: Find the speed | guided step notes | Timing | guided control, kept |  |
| `gkeysel` | select: - | guided step notes | Chords | guided control, kept | Notes shows the key as a chip that links here |
| `gvoice` | button: My voice | guided step notes | Your take ("Hear: My voice / As notes / Both") | guided control, kept | the same three ways of playing are what Play does in the Voice, Notes and other views |
| `gnotes` | button: The notes | guided step notes | Your take ("Hear: My voice / As notes / Both") | guided control, kept | the same three ways of playing are what Play does in the Voice, Notes and other views |
| `gboth` | button: Both | guided step notes | Your take ("Hear: My voice / As notes / Both") | guided control, kept | the same three ways of playing are what Play does in the Voice, Notes and other views |
| `gstopnotes` | button: | guided step notes | Your take | guided control, kept | Play turns into Stop while playing |
| `gmoretools` | details: Octaves, steps in the key, which notes fit t | guided step notes | Notes: More tools | guided control, kept |  |
| `gtimeline` | details: Play from a time, loop a stretch and name th | guided step notes | Travels with the melody roll: a closed fold in Notes, Timing, Words and Practise, open in Sections | guided control, kept |  |
| `gpitch` | range: - | guided step notes | Voice | guided control, kept |  |
| `gvibrato` | checkbox: - | guided step notes | Voice | guided control, kept |  |
| `gfix` | button: Fix my singing | guided step notes | Voice | guided control, kept |  |
| `ggenre` | select: Genre | guided step song | Sound | guided control, kept | one row a part |
| `ginstrument` | select: Melody sound | guided step song | Sound | guided control, kept | one row a part |
| `gchords` | button: Add chords | guided step song | Chords | guided control, kept |  |
| `gbass` | button: Add a bass line | guided step song | Chords | guided control, kept |  |
| `gnoharm` | button: Remove | guided step song | Chords | guided control, kept |  |
| `gharminst` | select: Sound of the chords or bass line | guided step song | Sound | guided control, kept | one row a part |
| `gvoice2create` | button: Create a harmony | guided step song | Second voice | guided control, kept |  |
| `gsingvoice2` | button: Sing it in my voice | guided step song | Second voice | guided control, kept |  |
| `gnovoice2` | button: Remove | guided step song | Second voice | guided control, kept |  |
| `gvoice2inst` | select: Sound of the second voice | guided step song | Sound | guided control, kept | one row a part |
| `gvoice2next` | button: Try another | guided step song | Second voice | guided control, kept |  |
| `gvoice2keep` | button: Keep it | guided step song | Second voice | guided control, kept |  |
| `gvoice2cancel` | button: Cancel | guided step song | Second voice | guided control, kept |  |
| `gbeat` | button: Record a beat | guided step song | Beat | guided control, kept | gbeat: see open question 4 |
| `ggroove` | select: Starter beat | guided step song | Beat | guided control, kept | gbeat: see open question 4 |
| `ggrooveadd` | button: Add this beat | guided step song | Beat | guided control, kept | gbeat: see open question 4 |
| `gnodrums` | button: Remove | guided step song | Beat | guided control, kept | gbeat: see open question 4 |
| `gbeatdownload` | button: Download your voice | guided step song | Beat | guided control, kept | removed by BEAT.4: Record a beat records a layer (open question 4) |
| `gbeatyes` | button: - | guided step song | Beat | guided control, kept | removed by BEAT.4: Record a beat records a layer (open question 4) |
| `gbeatno` | button: Cancel | guided step song | Beat | guided control, kept | removed by BEAT.4: Record a beat records a layer (open question 4) |
| `gvoicein` | checkbox: - | guided step song | Your song (the player card: "My voice in it") | guided control, kept | a second mirror of the same switch sits in Voice, as gsharevoice does on Share |
| `gplay` | button: Play the song | guided step song | Your song (the player card) | guided control, kept |  |
| `gstop` | button: Stop | guided step song | Your song (the player card) | guided control, kept |  |
| `gsongname` | text: - | guided step share | Share | guided control, kept |  |
| `gsharevoice` | checkbox: - | guided step share | Share | guided control, kept |  |
| `gsharesong` | button: Share the song | guided step share | Share | guided control, kept |  |
| `gsavebundle` | button: Save | guided step share | Share | guided control, kept |  |
| `gversionname` | text: Version name | guided step share | Share | guided control, kept |  |
| `gsaveversion` | button: Save version | guided step share | Share | guided control, kept |  |
| `gmoreapps` | details: Song as an audio file Download it to play an | guided step share | Share | guided control, kept |  |
| `gshareall` | button: Show every control | guided step share | Share | guided control, kept |  |
| `gback` | button: | guided bottom bar | Bottom bar of Sing, Your song and Share | guided control, kept | between the three steps; the change views have their own Prev / Done / Next |
| `gnext` | button: - | guided bottom bar | Bottom bar of Sing, Your song and Share | guided control, kept | between the three steps; the change views have their own Prev / Done / Next |
| `ghelpersback` | button: | guided Settings | Settings | guided control, kept |  |
| `gcleanup` | select: Natural Studio (stronger) | guided Settings | Settings | guided control, kept |  |
| `gpitchname` | select: Light Natural Perfect Custom | guided Settings | Settings | guided control, kept |  |
| `gtuneengine` | select: This device Server | guided Settings | Settings | guided control, kept |  |
| `gtranscriber` | select: This device Server | guided Settings | Settings | guided control, kept |  |
| `gbeatstyle` | select: Gently Tightly Swung | guided Settings | Settings | guided control, kept |  |
| `gshowall` | button: Show every control | guided Settings | Settings | guided control, kept |  |
| `greset` | button: Put the helpers back to the defaults | guided Settings | Settings | guided control, kept |  |
| `songname` | text: The song's name, kept on this device; a vers | top bar | Share (gsongname); shown as the title on Your song | guided mirror exists |  |
| `genre` | select: A genre sets better starting choices: the ch | top bar | Sound (ggenre) | guided mirror exists |  |
| `play` | button: Play | top bar | Your song (gplay, gstop) and Play in every change view | guided mirror exists |  |
| `stop` | button: Stop | top bar | Your song (gplay, gstop) and Play in every change view | guided mirror exists |  |
| `record` | button: Record | top bar | Sing (grecord) | guided mirror exists |  |
| `finish` | button: Stop recording | top bar | Sing (grecord) | guided mirror exists |  |
| `undo` | button: Undo | top bar | Top bar of every guided screen (gundo, gredo) | guided mirror exists |  |
| `redo` | button: Redo | top bar | Top bar of every guided screen (gundo, gredo) | guided mirror exists |  |
| `showguide` | button: Guided steps | top bar | All controls only | as today | comes back to the change view that matches the chosen part |
| `capturelink` | a: Capture | top bar | Sing: a link "Quick capture" beside Open a saved song | new link | all controls only today |
| `newsong` | button: New song | top bar | Sing (gnewsong) | guided mirror exists |  |
| `savebundle` | button: Save song | top bar | Share (gsavebundle) | guided mirror exists |  |
| `save` | button: Save notes only | top bar | Share: Open in other music apps | button mirror (data-press) | as today |
| `load` | button: Open project | top bar | Sing (gopen) | guided mirror exists |  |
| `savefolder` | button: Save to folder… | top bar | Share: Keep it (Mac app) | button mirror (data-press) | all controls only today |
| `openfolder` | button: Open folder… | top bar | Sing, beside Open a saved song (Mac app) | button mirror (data-press) | all controls only today |
| `projectfile` | file: - | top bar | Hidden file input behind Open a saved song | as today |  |
| `loop` | button: Loop | Timeline track | Sections (inside #transport, which moves as it does now) | studio control moved in |  |
| `clearloop` | button: Clear loop | Timeline track | Sections (inside #transport, which moves as it does now) | studio control moved in |  |
| `evolution` | button: Hear how it grew | Timeline track | Sections; and Share: Hear how it grew | studio control moved in + button mirror (data-press) | as today |
| `sectionname` | select: - | Timeline track | Sections (inside #transport, which moves as it does now) | studio control moved in |  |
| `marksection` | button: Mark section | Timeline track | Sections (inside #transport, which moves as it does now) | studio control moved in |  |
| `sectionrepeat` | button: Repeat | Timeline track | Sections (inside #transport, which moves as it does now) | studio control moved in |  |
| `sectionearlier` | button: Move earlier | Timeline track | Sections (inside #transport, which moves as it does now) | studio control moved in |  |
| `sectionlater` | button: Move later | Timeline track | Sections (inside #transport, which moves as it does now) | studio control moved in |  |
| `sectiondelete` | button: Delete | Timeline track | Sections (inside #transport, which moves as it does now) | studio control moved in |  |
| `sectionunmark` | button: Unmark | Timeline track | Sections (inside #transport, which moves as it does now) | studio control moved in |  |
| `mode` | select: Humming → melody Beatbox → drums Singing → v | panel voice > group Record | Sing (the three choices) | guided mirror exists |  |
| `countin` | checkbox: - | panel voice > group Record | Sing: Recording options | studio control moved in | all controls only today |
| `recclick` | checkbox: - | panel voice > group Record | Sing: Recording options | studio control moved in | all controls only today |
| `recsong` | checkbox: - | panel voice > group Record | Sing: Recording options | studio control moved in | all controls only today |
| `reclayer` | checkbox: - | panel voice > group Record | Sing: Recording options; Takes has "Record a part on top", which ticks it and opens Sing | studio control moved in | all controls only today |
| `calibrate` | button: Measure | panel voice > group Record | Sing: Recording options | studio control moved in | all controls only today |
| `pitchguide` | checkbox: - | panel voice > group Record | Sing: Recording options | studio control moved in | all controls only today |
| `import` | button: Import audio | panel voice > group Record | Sing (gimport) | guided mirror exists |  |
| `audiofile` | file: - | panel voice > group Record | Hidden file input behind Use a recording I already have | as today |  |
| `original` | button: Original | panel voice > group Record | Voice: More ("Hear it as recorded"); it is also what Before plays in Voice | studio control moved in | all controls only today |
| `comptake` | select: Take to comp in | panel voice > group Record | Takes | studio control moved in | all controls only today |
| `compfrom` | number: Section start, seconds of the song | panel voice > group Record | Takes | studio control moved in | all controls only today |
| `compto` | number: Section end, seconds of the song | panel voice > group Record | Takes | studio control moved in | all controls only today |
| `compin` | button: Comp in | panel voice > group Record | Takes | studio control moved in | all controls only today |
| `comploop` | button: Use the Timeline section | panel voice > group Record | Takes | studio control moved in | all controls only today |
| `polishstyle` | select: Studio (stronger) Natural (subtle) | panel voice > group Clean up the sound | Voice: Clean up the sound | studio control moved in | today only the helper runs it in the guided view |
| `polish` | button: Polish vocal | panel voice > group Clean up the sound | Voice: Clean up the sound | studio control moved in | today only the helper runs it in the guided view |
| `polished` | button: Polished | panel voice > group Clean up the sound | Voice: More | studio control moved in | all controls only today |
| `downloadvocal` | button: Download polished vocal | panel voice > group Clean up the sound | Voice: More | studio control moved in | all controls only today |
| `transcriber` | select: Basic Pitch (on device) Server (fallback) | panel voice > group Turn into notes | Settings (gtranscriber) | guided mirror exists |  |
| `analyze` | button: Transcribe recording | panel voice > group Turn into notes | Notes: More tools ("Read the notes from the recording again") | button mirror (data-press) | today only the helper runs it in the guided view |
| `tunestrength` | range: - | panel voice > group Fix my singing | Voice (gpitch) | guided mirror exists |  |
| `vibrato` | range: - | panel voice > group Fix my singing | Voice (gvibrato) | guided mirror exists |  |
| `tuneengine` | select: This device Server | panel voice > group Fix my singing | Settings (gtuneengine) | guided mirror exists |  |
| `tune` | button: Correct singing pitch | panel voice > group Fix my singing | Voice (gfix) | guided mirror exists |  |
| `playtuned` | button: Tuned | panel voice > group Fix my singing | Voice: it is what After plays; the button itself under More | studio control moved in | all controls only today |
| `downloadtuned` | button: Download tuned voice | panel voice > group Fix my singing | Voice: More | studio control moved in | all controls only today |
| `tunekey` | select: - | panel voice > group Fix my singing | Voice: More, with the pitch-line editor | studio control moved in | all controls only today |
| `tunescale` | select: Scale | panel voice > group Fix my singing | Voice: More, with the pitch-line editor | studio control moved in | all controls only today |
| `detectvocal` | button: Detect sung notes | panel voice > group Fix my singing | Voice: More, with the pitch-line editor | studio control moved in | all controls only today |
| `snapvocal` | button: Snap notes to key | panel voice > group Fix my singing | Voice: More, with the pitch-line editor | studio control moved in | all controls only today |
| `resetvocal` | button: Reset note edits | panel voice > group Fix my singing | Voice: More, with the pitch-line editor | studio control moved in | all controls only today |
| `separate` | button: Separate voice from music | panel voice > group Separate the voice from music | Voice: On the Mac app ("Take my voice out of the music") | studio control moved in | all controls only today |
| `playvocal` | button: Vocal | panel voice > group Separate the voice from music | Voice: On the Mac app ("Take my voice out of the music") | studio control moved in | all controls only today |
| `playband` | button: Music | panel voice > group Separate the voice from music | Voice: On the Mac app ("Take my voice out of the music") | studio control moved in | all controls only today |
| `downloadband` | button: Download music | panel voice > group Separate the voice from music | Voice: On the Mac app ("Take my voice out of the music") | studio control moved in | all controls only today |
| `usefull` | button: Use the full recording | panel voice > group Separate the voice from music | Voice: On the Mac app ("Take my voice out of the music") | studio control moved in | all controls only today |
| `addnote` | button: + Note | panel melody > group Notes | Notes: More tools | studio control moved in | all controls only today |
| `clearnotes` | button: Clear | panel melody > group Notes | Notes: More tools | studio control moved in | all controls only today |
| `melodydraw` | button: Draw | panel melody > group Notes > #melodytools | Notes (#melodytools, which moves as it does now) | studio control moved in |  |
| `melodyline` | button: Draw line | panel melody > group Notes > #melodytools | Notes (#melodytools, which moves as it does now) | studio control moved in |  |
| `linekeep` | button: Keep line | panel melody > group Notes > #melodytools | Notes (#melodytools, which moves as it does now) | studio control moved in |  |
| `linecancel` | button: Cancel | panel melody > group Notes > #melodytools | Notes (#melodytools, which moves as it does now) | studio control moved in |  |
| `melodyall` | button: Select all | panel melody > group Notes > #melodytools | Notes (#melodytools, which moves as it does now) | studio control moved in |  |
| `melodydelete` | button: Delete | panel melody > group Notes > #melodytools | Notes (#melodytools, which moves as it does now) | studio control moved in |  |
| `melodysemidown` | button: Down a semitone | panel melody > group Notes > #melodytools | Notes (#melodytools, which moves as it does now) | studio control moved in |  |
| `melodysemiup` | button: Up a semitone | panel melody > group Notes > #melodytools | Notes (#melodytools, which moves as it does now) | studio control moved in |  |
| `melodyoctdown` | button: Down an octave | panel melody > group Notes > #melodytools > #melodymore | Notes: More tools (#melodymore, as now) | studio control moved in |  |
| `melodyoctup` | button: Up an octave | panel melody > group Notes > #melodytools > #melodymore | Notes: More tools (#melodymore, as now) | studio control moved in |  |
| `melodykeydown` | button: Down a note in the key | panel melody > group Notes > #melodytools > #melodymore | Notes: More tools (#melodymore, as now) | studio control moved in |  |
| `melodykeyup` | button: Up a note in the key | panel melody > group Notes > #melodytools > #melodymore | Notes: More tools (#melodymore, as now) | studio control moved in |  |
| `melodyfit` | button: Show which notes fit the chords | panel melody > group Notes > #melodytools > #melodymore | Notes: More tools (#melodymore, as now) | studio control moved in |  |
| `practice` | button: Practise | panel melody > group Notes > #melodytools > #melodymore | Practise | studio control moved in | split out of #melodytools / #melodymore into a group of their own so they can move alone; ids unchanged |
| `warmup` | select: Warm-up exercise | panel melody > group Notes > #melodytools > #melodymore | Practise | studio control moved in | split out of #melodytools / #melodymore into a group of their own so they can move alone; ids unchanged |
| `addwarmup` | button: Add warm-up | panel melody > group Notes > #melodytools > #melodymore | Practise | studio control moved in | split out of #melodytools / #melodymore into a group of their own so they can move alone; ids unchanged |
| `practiceforget` | button: Forget range and progress | panel melody > group Notes > #melodytools > #melodymore | Practise | studio control moved in | split out of #melodytools / #melodymore into a group of their own so they can move alone; ids unchanged |
| `practicestop` | button: Stop | panel melody > group Notes > #melodytools | Practise | studio control moved in | split out of #melodytools / #melodymore into a group of their own so they can move alone; ids unchanged |
| `practicekeep` | button: Keep pass as a take | panel melody > group Notes > #melodytools | Practise | studio control moved in | split out of #melodytools / #melodymore into a group of their own so they can move alone; ids unchanged |
| `practiceask` | button: Ask about this pass | panel melody > group Notes > #melodytools | Practise; it opens Ask Tandem | studio control moved in |  |
| `lyrics` | textarea: - | panel melody > group Words | Words (#lyricsbox, which moves as it does now) | studio control moved in |  |
| `instrument` | select: - | panel melody > group Sound | Sound (ginstrument) | guided mirror exists |  |
| `bpm` | number: - | panel melody > group Speed and lining up | Timing (gbpm) | guided mirror exists |  |
| `grid` | select: 1/4 1/8 1/16 | panel melody > group Speed and lining up | Timing: More | studio control moved in | today only reachable through Gently / Tightly / Swung in the guided view |
| `swing` | range: - | panel melody > group Speed and lining up | Timing: More | studio control moved in | today only reachable through Gently / Tightly / Swung in the guided view |
| `qstrength` | select: 100% 75% 50% | panel melody > group Speed and lining up | Timing: More | studio control moved in | today only reachable through Gently / Tightly / Swung in the guided view |
| `detecttempo` | button: Detect tempo | panel melody > group Speed and lining up | Timing (gfindspeed) | guided mirror exists |  |
| `quantize` | button: Quantize | panel melody > group Speed and lining up | Timing: More | studio control moved in | today only reachable through Gently / Tightly / Swung in the guided view |
| `phraseearlier` | button: Beat | panel melody > group Phrases | Notes: More tools ("Move a phrase") | studio control moved in | all controls only today |
| `phraselater` | button: Beat | panel melody > group Phrases | Notes: More tools ("Move a phrase") | studio control moved in | all controls only today |
| `phrasedown` | button: −1 | panel melody > group Phrases | Notes: More tools ("Move a phrase") | studio control moved in | all controls only today |
| `phraseup` | button: +1 | panel melody > group Phrases | Notes: More tools ("Move a phrase") | studio control moved in | all controls only today |
| `phraseoctdown` | button: −8ve | panel melody > group Phrases | Notes: More tools ("Move a phrase") | studio control moved in | all controls only today |
| `phraseoctup` | button: +8ve | panel melody > group Phrases | Notes: More tools ("Move a phrase") | studio control moved in | all controls only today |
| `phrasecopy` | button: Copy to end | panel melody > group Phrases | Notes: More tools ("Move a phrase") | studio control moved in | all controls only today |
| `midiconnect` | button: Connect MIDI | panel melody | Notes: More tools ("Play it in on a keyboard") | studio control moved in | all controls only today; shown only where the browser has Web MIDI |
| `midiinput` | select: MIDI input | panel melody | Notes: More tools ("Play it in on a keyboard") | studio control moved in | all controls only today; shown only where the browser has Web MIDI |
| `midirecord` | button: Record from keyboard | panel melody | Notes: More tools ("Play it in on a keyboard") | studio control moved in | all controls only today; shown only where the browser has Web MIDI |
| `midioutput` | select: MIDI output | panel melody | Sound: More ("Play it on my synth") | studio control moved in | all controls only today |
| `midichannel` | select: MIDI channel of the melody | panel melody | Sound: More ("Play it on my synth") | studio control moved in | all controls only today |
| `harmonystyle` | select: Chords Bass line | panel harmony > group Make chords or a bass line | Chords (gchords, gbass set the style and press Generate) | guided mirror exists |  |
| `harmonykey` | select: Harmony key | panel harmony > group Make chords or a bass line | Chords (gkeysel) | guided mirror exists |  |
| `harmonyinstrument` | select: - | panel harmony > group Make chords or a bass line | Sound (gharminst) | guided mirror exists |  |
| `genharmony` | button: Generate | panel harmony > group Make chords or a bass line | Chords (gchords, gbass set the style and press Generate) | guided mirror exists |  |
| `clearharmony` | button: Clear | panel harmony > group Make chords or a bass line | Chords (gnoharm) | guided mirror exists |  |
| `chordroot` | select: - | panel harmony > group Change a chord | Chords, under the chord names (#chordstrip) | studio control moved in | all controls only today |
| `chordquality` | select: - | panel harmony > group Change a chord | Chords, under the chord names (#chordstrip) | studio control moved in | all controls only today |
| `harmonydraw` | button: Draw | panel harmony > group Edit the notes | Chords: More, with #harmonyroll | studio control moved in | all controls only today |
| `harmonyall` | button: Select all | panel harmony > group Edit the notes | Chords: More, with #harmonyroll | studio control moved in | all controls only today |
| `harmonydelete` | button: Delete | panel harmony > group Edit the notes | Chords: More, with #harmonyroll | studio control moved in | all controls only today |
| `harmonyoctdown` | button: −8ve | panel harmony > group Edit the notes | Chords: More, with #harmonyroll | studio control moved in | all controls only today |
| `harmonyoctup` | button: +8ve | panel harmony > group Edit the notes | Chords: More, with #harmonyroll | studio control moved in | all controls only today |
| `harmonykeydown` | button: Key | panel harmony > group Edit the notes | Chords: More, with #harmonyroll | studio control moved in | all controls only today |
| `harmonykeyup` | button: Key | panel harmony > group Edit the notes | Chords: More, with #harmonyroll | studio control moved in | all controls only today |
| `harmonysemidown` | button: −1 | panel harmony > group Edit the notes | Chords: More, with #harmonyroll | studio control moved in | all controls only today |
| `harmonysemiup` | button: +1 | panel harmony > group Edit the notes | Chords: More, with #harmonyroll | studio control moved in | all controls only today |
| `voice2interval` | select: Interval of the copy | panel voice2 > group Copy the melody | Second voice: More ("Copy my tune higher or lower") | studio control moved in | all controls only today |
| `voice2dup` | button: Duplicate melody | panel voice2 > group Copy the melody | Second voice: More ("Copy my tune higher or lower") | studio control moved in | all controls only today |
| `clearvoice2` | button: Clear | panel voice2 > group Copy the melody | Second voice (gnovoice2) | guided mirror exists |  |
| `voice2create` | button: Create harmony | panel voice2 > group Let Tandem write one | Second voice (gvoice2create and the try row) | guided mirror exists |  |
| `voice2next` | button: Try another | panel voice2 > group Let Tandem write one | Second voice (gvoice2create and the try row) | guided mirror exists |  |
| `voice2keep` | button: Keep | panel voice2 > group Let Tandem write one | Second voice (gvoice2create and the try row) | guided mirror exists |  |
| `voice2cancel` | button: Cancel | panel voice2 > group Let Tandem write one | Second voice (gvoice2create and the try row) | guided mirror exists |  |
| `singvoice2` | button: Sing it in my voice | panel voice2 > group Sing it in my voice | Second voice (gsingvoice2) | guided mirror exists |  |
| `playvoice2sung` | button: Sung | panel voice2 > group Sing it in my voice | Second voice, shown once it has been sung | studio control moved in | all controls only today |
| `voice2sungmute` | checkbox: - | panel voice2 > group Sing it in my voice | Second voice, shown once it has been sung | studio control moved in | all controls only today |
| `removevoice2sung` | button: Remove | panel voice2 > group Sing it in my voice | Second voice, shown once it has been sung | studio control moved in | all controls only today |
| `voice2instrument` | select: - | panel voice2 > group Sound | Sound (gvoice2inst) | guided mirror exists |  |
| `voice2draw` | button: Draw | panel voice2 > group Edit the notes | Second voice: More, with #voice2roll | studio control moved in | all controls only today |
| `voice2all` | button: Select all | panel voice2 > group Edit the notes | Second voice: More, with #voice2roll | studio control moved in | all controls only today |
| `voice2delete` | button: Delete | panel voice2 > group Edit the notes | Second voice: More, with #voice2roll | studio control moved in | all controls only today |
| `voice2octdown` | button: −8ve | panel voice2 > group Edit the notes | Second voice: More, with #voice2roll | studio control moved in | all controls only today |
| `voice2octup` | button: +8ve | panel voice2 > group Edit the notes | Second voice: More, with #voice2roll | studio control moved in | all controls only today |
| `voice2keydown` | button: Key | panel voice2 > group Edit the notes | Second voice: More, with #voice2roll | studio control moved in | all controls only today |
| `voice2keyup` | button: Key | panel voice2 > group Edit the notes | Second voice: More, with #voice2roll | studio control moved in | all controls only today |
| `voice2semidown` | button: −1 | panel voice2 > group Edit the notes | Second voice: More, with #voice2roll | studio control moved in | all controls only today |
| `voice2semiup` | button: +1 | panel voice2 > group Edit the notes | Second voice: More, with #voice2roll | studio control moved in | all controls only today |
| `groove` | select: - | panel drums > group Starter beat | Beat (ggroove, drawn as four choices) | guided mirror exists |  |
| `groovebars` | select: As long as the song 4 bars 8 bars 16 bars 32 | panel drums > group Starter beat | Beat: More | studio control moved in | all controls only today |
| `groovekeep` | checkbox: - | panel drums > group Starter beat | Beat: More | studio control moved in | all controls only today |
| `addgroove` | button: Add the beat | panel drums > group Starter beat | Beat (ggrooveadd) | guided mirror exists |  |
| `drum` | select: Kick Snare Hi-hat | panel drums > group Add hits | Beat: More, with #drumroll | studio control moved in | all controls only today |
| `addhit` | button: + Hit | panel drums > group Add hits | Beat: More, with #drumroll | studio control moved in | all controls only today |
| `clearhits` | button: Clear | panel drums > group Add hits | Beat: More (gnodrums) | guided mirror exists |  |
| `bandstyle` | text: Band style | panel band | Sound: On the Mac app (#bandtrack moved in) | studio control moved in | today a button that leaves the guided view |
| `bandfollows` | select: Play my notes Follow the melody Follow the r | panel band | Sound: On the Mac app (#bandtrack moved in) | studio control moved in | today a button that leaves the guided view |
| `banddrums` | checkbox: - | panel band | Sound: On the Mac app (#bandtrack moved in) | studio control moved in | today a button that leaves the guided view |
| `genband` | button: Generate band | panel band | Sound: On the Mac app (#bandtrack moved in) | studio control moved in | today a button that leaves the guided view |
| `playbandtrack` | button: Band | panel band | Sound: On the Mac app (#bandtrack moved in) | studio control moved in | today a button that leaves the guided view |
| `bandmute` | checkbox: - | panel band | Sound: On the Mac app (#bandtrack moved in) | studio control moved in | today a button that leaves the guided view |
| `removeband` | button: Remove | panel band | Sound: On the Mac app (#bandtrack moved in) | studio control moved in | today a button that leaves the guided view |
| `timbreinstrument` | select: Soprano saxophone Electric guitar Church org | panel timbre | Sound: On the Mac app (#timbretrack moved in) | studio control moved in | today a button that leaves the guided view |
| `gentimbre` | button: Play my voice on it | panel timbre | Sound: On the Mac app (#timbretrack moved in) | studio control moved in | today a button that leaves the guided view |
| `playtimbretrack` | button: Instrument | panel timbre | Sound: On the Mac app (#timbretrack moved in) | studio control moved in | today a button that leaves the guided view |
| `timbremute` | checkbox: - | panel timbre | Sound: On the Mac app (#timbretrack moved in) | studio control moved in | today a button that leaves the guided view |
| `removetimbre` | button: Remove | panel timbre | Sound: On the Mac app (#timbretrack moved in) | studio control moved in | today a button that leaves the guided view |
| `melodylock` | checkbox: - | panel song > group Protect my melody | Ask Tandem ("Protect my melody") | studio control moved in | today the guided view only says which way it is set |
| `chatform` | form: - | panel song | Ask Tandem (#chat and #chatform, which move as they do now) | studio control moved in |  |
| `prompt` | text: - | panel song > #chatform | Ask Tandem (#chat and #chatform, which move as they do now) | studio control moved in |  |
| `aiprovider` | select: - | panel song | Settings: Ask Tandem connection (Mac app) | studio control moved in | all controls only today |
| `aimodel` | text: - | panel song | Settings: Ask Tandem connection (Mac app) | studio control moved in | all controls only today |
| `aibaseurl` | url: - | panel song | Settings: Ask Tandem connection (Mac app) | studio control moved in | all controls only today |
| `aikey` | password: - | panel song | Settings: Ask Tandem connection (Mac app) | studio control moved in | all controls only today |
| `aisave` | button: Save | panel song | Settings: Ask Tandem connection (Mac app) | studio control moved in | all controls only today |
| `aiforget` | button: Remove key | panel song | Settings: Ask Tandem connection (Mac app) | studio control moved in | all controls only today |
| `api` | url: - | panel song | Settings: Ask Tandem connection | studio control moved in | all controls only today |
| `token` | password: - | panel song | Settings: Ask Tandem connection | studio control moved in | all controls only today |
| `connect` | button: Test connection | panel song | Settings: Ask Tandem connection | studio control moved in | all controls only today |
| `sharesong` | button: Share the song | panel share > group Export | Share (gsharesong) | guided mirror exists |  |
| `exportwav` | button: Export WAV | panel share > group Export | Share: Open in other music apps | button mirror (data-press) | as today |
| `exportevolution` | button: Export how it grew | panel share > group Export | Share: Hear how it grew | button mirror (data-press) | as today |
| `exportstems` | button: Export stems | panel share > group Export | Share: Open in other music apps | button mirror (data-press) | as today |
| `exportmidi` | button: Export MIDI | panel share > group Export | Share: Open in other music apps ("MIDI only") | button mirror (data-press) | all controls only today |
| `exportdawproject` | button: Export DAWproject | panel share > group Export | Share: Open in other music apps | button mirror (data-press) | as today |
| `exportmusicxml` | button: Export MusicXML | panel share > group Export | Share: Open in other music apps | button mirror (data-press) | as today |
| `demo` | button: Load example | panel share > group Export | Sing (gdemo) | guided mirror exists |  |
| `versionname` | text: Version name | panel share > group Keep | Share (gversionname, gsaveversion) | guided mirror exists |  |
| `saveversion` | button: Save version | panel share > group Keep | Share (gversionname, gsaveversion) | guided mirror exists |  |
| `versionreplace` | button: Remove it and save | panel share > group Keep | Share | button mirror (data-press) | as today |
| `versionkeep` | button: Cancel | panel share > group Keep | Share | button mirror (data-press) | as today |

Controls and interactive areas without a fixed id in the page source:

| Control | Where it is today | Where it lives in the new guided flow |
|---|---|---|
| `#gundo`, `#gredo`, `#gsettings` (guided top bar) | every guided screen | every guided screen, including the change views |
| `#steps [data-step]` (the four step buttons) | guided rail | three buttons: Sing, Your song, Share. A stored step of `notes` or `song` opens Your song |
| `[data-mode]` (A tune / A beat / Singing with words) | guided Sing | Sing, as one row |
| `[data-beat]` (Gently / Tightly / Swung) | guided Notes | Timing |
| `[data-helper]` switches | guided Settings | Settings |
| `[data-press]` buttons on Share (evolution, stop, exports, versionreplace, versionkeep) | guided Share | Share |
| `[data-goto=bandtrack]`, `[data-goto=timbretrack]` | guided Song; they leave the guided view | replaced by the panels themselves under Sound: On the Mac app |
| `.gsingfirst` (Go to Sing) | guided Notes and Song when empty | Your song when empty |
| `#mute-<part>`, `#solo-<part>`, `#level-<part>` (the mixer strips, MIX.1) | under each lane's name, all controls only; the voice's mute through `gvoicein` | Sound: level and in-the-song per row; solo under More |
| `#playtake-<id>`, `#usetake-<id>`, `#removetake-<id>` (`#takes`) | Your voice panel, all controls only | Takes |
| `#layerplay-<id>`, `#layerinto-<id>`, `#layertranscribe-<id>`, `#layerremove-<id>` and each layer's strip (`#layerlanes`) | layer lanes, all controls only | Takes |
| `#versionlist` (open or delete a saved version) | Share panel, all controls only | Share: Keep it |
| `#timeline`, `#sections` (inside `#transport`) | Timeline track; guided Notes fold | travel with the melody roll; open in Sections |
| `#melodyroll` | melody lane; guided Notes | Notes, Timing, Words, Practise, Sections (whichever is open) |
| `#chordstrip`, `#harmonyroll` | chords lane, all controls only | Chords |
| `#voice2roll` | harmony voice lane, all controls only | Second voice: More |
| `#drumroll` | drums lane, all controls only | Beat |
| `#wave` | voice lane, all controls only | Your take |
| `#vocalnoteeditor`, `#vocalnoteinfo` (the pitch-line editor) | voice lane, all controls only | Voice: More |
| `#vocalrange`, `#practiceprogress`, `#practiceinfo` | melody tools | Practise |
| `#swupdate`, `#audiorescue` (fixed buttons) | both views | both views, unchanged |
| `.lanehead[data-part]`, `.railstep[data-rail]` | all controls navigation | all controls only; the rail takes the three new names |
| New controls this design adds | - | Your take: Keep this take, Sing it again, Share it as it is. Hub: the tiles. View frame: back, jump menu, Play, Before / After, Put it back, Prev, Done, Next. Share: Play, the Change links |

## Open questions for the operator

1. **Names.** Step 2 is "Your song" here; the draft says "Change". The kinds "Voice" (draft: Pitch) and "Second voice" (draft: Harmony). Are these the words you would look for?
2. **Is "Keep this take" worth its tap?** The take screen asks one question (keep, sing again, share as it is) and then shows the hub. The alternative is to put the tiles straight under Play on the take screen: one tap fewer, a busier first screen. Recommended: the one-question screen, checked with a first-time person.
3. **Should the take play by itself when Tandem has finished?** Recommended: no. A phone that starts playing your own singing aloud in a quiet room is a surprise, and with the speaker on it can feed into the next take. One large Play instead.
4. **Record a beat.** Today, in the guided view, a beat take replaces the sung take (after a warning and keeping the song as a version). Recorded layers (TRACK.1) can already record over the song and read the layer into the drums. Recommended: Beat's Record a beat uses a layer, and the warning goes. It is the one place this design changes what a button does.
5. **Fix my singing: still automatic for singing with words?** With listen-first the person hears the fixed voice first and may never know what was changed. Recommended: keep it automatic (it is the flattering default), and make My voice on the take screen offer "as I sang it" beside it, which is what Before / After in Voice does. The other choice is to leave pitch alone until asked.
6. **Prev / Next order.** Through all twelve views in hub order (Voice ... Sound, Sections, Takes, Practise, Ask Tandem), or only the eight main kinds? Recommended: all twelve, so there is one rule.
7. **The example.** Try an example has no take, so it opens Your song with Play in view. Agreed, or should it show a take screen for the example's melody?
8. **Wide screens.** Is the two-pane guided layout (hub left, open view right) wanted soon, or is the desktop person served by Show every control for now? Recommended: later (UX.9 below).
9. **Who judges it.** UX.5's acceptance in the draft says "judged by a first-time person (HUMAN)". Is that you on the Pixel again, or someone who has not seen Tandem?

## A split into buildable items

In the order to build them. Each leaves the app working and the all-controls view untouched. UX.4 alone answers the first half of what the operator said; UX.5 the second half.

- [ ] **UX.4** Listen first: a take opens on its own playback
  - Asked for by the operator on 2026-11-21. Today Stop leaves the person on the Sing step with "Done. Check your notes next." and no Play; hearing the take is on the next step. After a take recorded or imported from the Sing step the guided view shows **Your take**, a second panel of the Sing step (`data-panel="take"`; the rail still shows Sing): the waveform (`#wave`, moved in), one large Play that plays the raw take until the helpers finish and the best take after, the helpers' list (`#gplan`, moved here from Sing) while they run, then Hear My voice / As notes / Both (`#gvoice`, `#gnotes`, `#gboth`, `#gstopnotes`, moved from Notes), "What Tandem did" (one line per helper that ran, from `planStates`, skipped and failed ones said plainly), and **Keep this take** (to the next step), **Sing it again** (back to Record; once there is a take, a new one is added to `takes`, TAKE.1) and Share it as it is. The Sing panel's "When you stop, Tandem will" card becomes one sentence with Change. `afterTake` and `runHelpers` are unchanged except that the closing status line no longer says "Check your notes next". The four steps stay until UX.5. All-controls view unchanged.
  - **Acceptance:** `e2e/test_guided.py` with the fake microphone at 390 px: after Stop the take panel is shown before the helpers finish and its Play plays (the playhead's `data-t` moves) while a helper is still marked running; after they finish Hear As notes plays the melody; Keep this take opens the next step; Sing it again then a second take leaves two takes in `takes`; an import opens the same panel; a failed helper is named on the panel; no sideways scroll; the control-inventory test passes; screenshots in the PR.
- [ ] **UX.5** Your song: the hub and one view per kind of change
  - **Depends:** UX.4
  - Asked for by the operator on 2026-11-21. The guided Notes and Song steps are two long pages (1,464 and 1,577 px at phone width) holding sixteen kinds of thing. The rail becomes Sing, Your song, Share (`guide.js` `STEPS`; a stored step of `notes` or `song` opens Your song). **Your song** is a player card (`#gplay`, `#gstop`, the key and speed chips, `#gvoicein`) and a tile per kind from a new `VIEWS` list in `guide.js` (id, name, group, what Play plays), each with a state line from a pure `viewSummaries(project)` beside `stepSummaries`, a used mark, and one Suggested next (`suggestNext`: chords, then a beat, then Share). A tile opens its **change view**: one frame (back to Your song, the name with a menu of the views, Undo and Redo, Play/Stop, Prev / Done / Next) and the view's controls. This item builds the nine views made only of what the guided view already has: Voice (`#gfixcard`), Notes (`#slot-roll`, `#gmoretools`), Timing (speed, Find the speed, `[data-beat]`), Words (`#slot-words`), Chords (`#gchords`, `#gbass`, `#gnoharm`, `#gkeysel`), Second voice, Beat, Sound (`#ggenre` and the three instrument menus) and Ask Tandem (`#slot-chat`). `relocate` takes the open view, so the roll, its tools and the Timeline fold move into whichever view shows them. Every control keeps its id and handler; `#gkeyspeed` goes.
  - **Acceptance:** Node tests for `VIEWS`, `viewSummaries` and `suggestNext`; an e2e test per view at 390 px (its controls are in it and work: one edit made from each), Prev / Next order and the jump menu, Done returns to the hub with the tile's state line changed, the roll is in exactly one view at a time and back in its lane under Show every control; the control-inventory test; no sideways scroll; phone and desktop screenshots; judged by a first-time person (HUMAN).
- [ ] **UX.6** Before / After and Put it back in every change view
  - **Depends:** UX.5
  - PRODUCT.md asks for "reversible edits, A/B comparisons"; today the only comparison is the three separate play buttons for the recording. Opening a change view notes where the undo history stands. Once the view has made an edit, the frame's **Before / After** switch chooses what Play plays: After is the song now; Before is the project as it was when the view opened, rendered with `renderParts` from the history's snapshot and played from the same time, with the view's controls dimmed and a line saying so. In Voice, Before is the take as recorded and After the best take. **Put it back** undoes this view's edits (as many Undo steps as the view made) and can itself be undone. Switching while playing keeps the place in the song. Nothing in the project changes by comparing.
  - **Acceptance:** Node tests for the view's edit count across undo, redo and edits made by the chat; e2e: in Timing, line up Tightly, switch to Before, and the notes scheduled are the ones from before (read from the page as the playback tests do), switch to After and they are the lined-up ones; Put it back restores the project byte for byte and Redo brings the change back; Before is disabled until the view has changed something; in Voice, Before plays the original recording.
- [ ] **UX.7** Nothing left behind: every studio control has a place in the guided view
  - **Depends:** UX.5
  - 102 of the studio's 186 controls can be reached only under Show every control today (table in this document). Each view gets one closed **More** that the studio's own groups move into: Voice (the pitch-line editor and Detect / Snap / Reset, key and scale, hear it as recorded, downloads; Separate in the Mac app), Notes (phrases, + Note and Clear, Transcribe again, the MIDI keyboard), Timing (grid, strength, swing), Chords (the chord names and change a chord in view; the chord notes' tools under More), Second voice (interval copy, its notes, the sung harmony's controls), Beat (bars, keep, single hits), Sound (the mixer strips as level and in-the-song a row, solo and MIDI out under More; the Band and Voice as instrument panels in the Mac app, replacing the two buttons that leave the guided view). Three more views: **Sections** (the Timeline open), **Takes** (the takes list, comp, the layers, Record a part on top), **Practise** (the practice and warm-up controls, split out of `#melodymore` into a group of their own). Sing gets Recording options (`#countin`, `#recclick`, `#recsong`, `#pitchguide`, `#calibrate`, `#reclayer`); Settings gets the Ask Tandem connection; Share gets the saved versions list. The groups in `#partpanel` get ids so they can be moved; no control id or handler changes.
  - **Acceptance:** the control-inventory test is extended with a table (`guide.js`) from every control id in `index.html` to the guided screen or fold that shows it, and fails for an id with no entry; an e2e test opens each view and fold at 390 px and finds its listed controls visible and inside the guided view; each is back in its panel under Show every control; one edit made through a More fold in each view.
- [ ] **UX.8** Share: hear it and check it before sending
  - **Depends:** UX.5
  - The Share step cannot play the song it is about to send. Add Play/Stop at the top, and "In your song": one line per part present (from `viewSummaries`), each with a Change link that opens its view and whose Done returns to Share.
  - **Acceptance:** e2e at 390 px: Play on Share plays the mix (`data-mix`), each line names a part that is in the project and none that is not, Change opens the right view and Done comes back to Share.
- [ ] **UX.9** The desktop studio keeps your place, and the guided view uses a wide screen
  - **Depends:** UX.7
  - The desktop rail takes the names Sing, Your song, Share. Show every control from a change view opens the studio with the matching part chosen (`showPart`), and Guided steps comes back to that view. At 1100 px and wider the guided view shows the hub on the left and the open view on the right.
  - **Acceptance:** e2e in `e2e/test_studio_layout.py`: the round trip from three views lands on the matching lane and back; at 1440 px the hub and a view are side by side with no control duplicated; the control-inventory test; screenshots at desktop and tablet widths.
- [x] **BEAT.4** Record a beat over the song (open question 4, agreed)
  - The guided Record a beat replaces the sung take after a warning. Make it record a layer over the song (TRACK.1) that is read into the drums as one edit, and drop the warning and `#gbeatwarn`'s buttons from the path.
  - **Acceptance:** e2e with the fake microphone: after Record a beat from the Beat view the first take is still the song's take, there is one layer, and the drums hold its hits; Undo removes the hits.

## Risks

- **Moving many elements.** UX.7 moves about a hundred controls between the panels and the views. The existing `relocate` pattern and the inventory test are the safety net; the item extends the test before it moves anything.
- **Before playback.** Rendering the snapshot with `renderParts` is the offline path Export uses, so Before may take a moment to start on a long song on a phone. The first build can render on first use and keep the buffer until the view's next edit. Built (UX.6): Before is played live through Play's own scheduling from the snapshot's project (`playback({src})`), so it starts at once and there is no buffer to keep.
- **Twelve views is still twelve.** The hub shows eight tiles and three small buttons. If the first-time person still hesitates, the next cut is to show only the Suggested next and "Fix something" / "Add something" as two doors; the views under them would not change.
- **This was judged from a desktop emulation.** Tap sizes and scroll feel need the Pixel.


## Operator decisions (2026-11-21)

- Record a beat in the guided view records a layer over the song instead of replacing the sung take (agreed).
- 2026-11-21: operator approved the design as proposed, with no changes: take every recommended answer to the open questions; file UX.4 onward from the roadmap split here and build them in order.
- Open questions with no recommendation in the text, decided on the operator's standing instruction to take the recommendation (2026-11-21):
  - 1, names: the design's names stay: Your song, Voice, Second voice.
  - 7, the example: from UX.5 Try an example opens Your song with Play in view, with no take screen. In UX.4 it still opens the Notes step, since Your song does not exist yet.
  - 9, who judges it: the operator on the Pixel first, then someone new to Tandem when one is available (HUMAN).
