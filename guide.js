// UI.1: the guided steps and the automatic helpers. UX.5: the steps are Sing, Your song and Share; Your song is a hub
// with one change view per kind of change (VIEWS).
// Pure: what the guided view shows and does next, and its settings. The studio page wires it to the controls.
import { genreById } from "./genre.js";

export const GUIDE_KEY = "tandem-guide";

export const STEPS = Object.freeze([
  Object.freeze({ id: "sing", label: "Sing", title: "Sing your idea", next: "Next: your song" }),
  Object.freeze({ id: "song", label: "Your song", title: "Your song", next: "Next: finish and share" }),
  Object.freeze({ id: "share", label: "Share", title: "Finish and share", next: null }),
]);
// UX.5: the Notes and Song steps became Your song, so a step kept from before opens it.
const OLD_STEPS = Object.freeze({ notes: "song" });

// UX.5: the change views Your song opens, in the order Prev and Next walk them. group is the heading of the hub's
// tiles they sit under; plays is what the view's Play plays (PLAYS); roll marks the views the melody roll moves into.
export const VIEW_GROUPS = Object.freeze([
  Object.freeze({ id: "fix", label: "Fix your tune" }),
  Object.freeze({ id: "add", label: "Add to it" }),
  Object.freeze({ id: "more", label: "More" }),
  Object.freeze({ id: "ask", label: "Or ask for it" }),
]);
export const VIEWS = Object.freeze([
  Object.freeze({ id: "voice", name: "Voice", group: "fix", plays: "voice", roll: false }),
  Object.freeze({ id: "notes", name: "Notes", group: "fix", plays: "both", roll: true }),
  Object.freeze({ id: "timing", name: "Timing", group: "fix", plays: "both", roll: true }),
  Object.freeze({ id: "words", name: "Words", group: "fix", plays: "both", roll: true }),
  Object.freeze({ id: "chords", name: "Chords", group: "add", plays: "song", roll: false }),
  Object.freeze({ id: "voice2", name: "Second voice", group: "add", plays: "song", roll: false }),
  Object.freeze({ id: "beat", name: "Beat", group: "add", plays: "song", roll: false }),
  Object.freeze({ id: "sound", name: "Sound", group: "add", plays: "song", roll: false }),
  // UX.7: the song's sections on the Timeline, every take and layer, and practising the tune.
  Object.freeze({ id: "sections", name: "Sections", group: "more", plays: "song", roll: true }),
  Object.freeze({ id: "takes", name: "Takes", group: "more", plays: "song", roll: false }),
  Object.freeze({ id: "practise", name: "Practise", group: "more", plays: "both", roll: true }),
  Object.freeze({ id: "ask", name: "Ask Tandem", group: "ask", plays: "song", roll: false }),
]);
export const viewById = id => VIEWS.find(v => v.id === id) ?? null;

// UX.9: the desktop studio's part (its lane or rail entry, `showPart`) that holds each change view's controls (frame D of
// docs/design/tandem-flow-redesign.html). Sound is the melody's Sound group; Ask Tandem is the `song` panel.
export const VIEW_PARTS = Object.freeze({
  voice: "voice", notes: "melody", timing: "melody", words: "melody", chords: "harmony", voice2: "voice2", beat: "drums",
  sound: "melody", sections: "melody", takes: "voice", practise: "melody", ask: "song",
});
// The change view a part chosen in the studio comes back to, when it is not the part the studio was opened on.
export const PART_VIEWS = Object.freeze({
  voice: "voice", melody: "notes", harmony: "chords", voice2: "voice2", drums: "beat", band: "sound", timbre: "sound", song: "ask",
});
// The part Show every control opens on from a guided place {step, view}: a change view's own part, Your song's hub the melody,
// Share its panel, Sing (and Your take) the voice.
export function studioPart({ step, view } = {}) {
  if (step === "song" && VIEW_PARTS[view]) return VIEW_PARTS[view];
  return step === "share" ? "share" : step === "song" ? "melody" : "voice";
}
// Where Guided steps comes back to: the place the studio was opened from while its part is still the one chosen, else the
// change view (or step) that matches the part chosen in the studio.
export function guidedPlace(part, from = {}) {
  if (studioPart(from) === part) return from;
  if (part === "share") return { step: "share" };
  return PART_VIEWS[part] ? { step: "song", view: PART_VIEWS[part] } : { step: from.step ?? "sing" };
}
const viewIndex = id => VIEWS.findIndex(v => v.id === id);
export const nextView = id => { const i = viewIndex(id); return i >= 0 && i < VIEWS.length - 1 ? VIEWS[i + 1].id : null; };
export const previousView = id => { const i = viewIndex(id); return i > 0 ? VIEWS[i - 1].id : null; };

// What a view's Play plays: the best take alone, the take with the notes (the song as mixed when there is no take),
// or the song as the mixer has it.
export function playsText(plays, recorded) {
  if (plays === "voice") return recorded ? "Plays your voice" : "Record yourself first to hear your voice";
  if (plays === "both") return recorded ? "Plays your voice with the notes" : "Plays the song";
  return "Plays the song";
}

// UX.6: the line under the player while Before is chosen (the view's controls are dimmed meanwhile). In Voice, Before is
// the take as sung; elsewhere it is the song as it was when the view was opened.
export function beforeText(view) {
  const v = viewById(view);
  if (!v) return "";
  if (v.plays === "voice") return "Before: your take as you sang it. Choose After to hear it as it is now.";
  return "Before: the song as it was when you opened " + v.name + ". Choose After to change it.";
}

// The automatic helpers, in the order the settings screen lists them.
export const HELPERS = Object.freeze([
  Object.freeze({ id: "cleanup", label: "Clean up the sound", detail: "Removes rumble and hiss from your voice and evens the level" }),
  Object.freeze({ id: "notes", label: "Turn recordings into notes", detail: "Right after you stop recording" }),
  Object.freeze({ id: "speed", label: "Find the speed", detail: "From your notes, for lining up with the beat and for chords" }),
  Object.freeze({ id: "fixpitch", label: "Fix pitch when I sing with words", detail: "At the amount set below" }),
  Object.freeze({ id: "lineup", label: "Line notes up with the beat", detail: "Off: keeps your timing as you sang it" }),
]);

export const PITCH_AMOUNTS = Object.freeze({ light: 50, natural: 85, perfect: 100 });

// Quantize settings for "Line up with the beat": division per beat (4 = sixteenths), strength 0..1, swing 0..1.
export const BEAT_STYLES = Object.freeze({
  gently: Object.freeze({ label: "Gently", division: 4, strength: 0.75, swing: 0 }),
  tightly: Object.freeze({ label: "Tightly", division: 4, strength: 1, swing: 0 }),
  swung: Object.freeze({ label: "Swung", division: 2, strength: 0.75, swing: 0.6 }),
});

export const CLEANUP_STYLES = Object.freeze({ natural: "Natural", studio: "Studio" });
export const TRANSCRIBERS = Object.freeze({ device: "This device", server: "Server" });

export const DEFAULTS = Object.freeze({
  view: "guided",
  step: "sing",
  helpers: Object.freeze({ cleanup: true, notes: true, speed: true, fixpitch: true, lineup: false }),
  cleanup: "natural",
  pitch: PITCH_AMOUNTS.natural,
  vibrato: true,
  beat: "gently",
  transcriber: "device",
});

const pick = (v, allowed, fallback) => (allowed.includes(v) ? v : fallback);

export function normalizeSettings(raw) {
  const r = raw && typeof raw === "object" ? raw : {};
  const h = r.helpers && typeof r.helpers === "object" ? r.helpers : {};
  const helpers = {};
  for (const { id } of HELPERS) helpers[id] = typeof h[id] === "boolean" ? h[id] : DEFAULTS.helpers[id];
  const pitch = Number.isFinite(r.pitch) && r.pitch >= 0 && r.pitch <= 100 ? Math.round(r.pitch / 5) * 5 : DEFAULTS.pitch;
  return {
    view: pick(r.view, ["guided", "all"], DEFAULTS.view),
    step: pick(OLD_STEPS[r.step] ?? r.step, STEPS.map(s => s.id), DEFAULTS.step),
    helpers,
    cleanup: pick(r.cleanup, Object.keys(CLEANUP_STYLES), DEFAULTS.cleanup),
    pitch,
    vibrato: typeof r.vibrato === "boolean" ? r.vibrato : DEFAULTS.vibrato,
    beat: pick(r.beat, Object.keys(BEAT_STYLES), DEFAULTS.beat),
    transcriber: pick(r.transcriber, Object.keys(TRANSCRIBERS), DEFAULTS.transcriber),
  };
}

// The settings are a convenience for this device: unreadable or blocked storage gives the defaults.
export function readSettings(storage) {
  try {
    const text = storage?.getItem(GUIDE_KEY);
    return normalizeSettings(text ? JSON.parse(text) : null);
  } catch {
    return normalizeSettings(null);
  }
}

export function writeSettings(storage, settings) {
  try {
    if (!storage) return false;
    storage.setItem(GUIDE_KEY, JSON.stringify(normalizeSettings(settings)));
    return true;
  } catch {
    return false;
  }
}

// What the guided view does when a take from the Sing step is ready, in order.
// mode is the studio's recording mode: melody (a tune), rhythm (a beat) or vocal (singing with words).
export function afterTake(mode, settings) {
  if (!["melody", "rhythm", "vocal"].includes(mode)) return [];
  const h = normalizeSettings(settings).helpers, plan = [];
  // The clean-up is a vocal band-pass, gate and compressor: on a beatbox it would cut drum hits, so it is for voices only.
  if (h.cleanup && mode !== "rhythm") plan.push({ action: "polish", label: "Clean up the sound" });
  if (h.fixpitch && mode === "vocal") plan.push({ action: "fixpitch", label: "Fix the pitch of your singing" });
  if (h.notes) {
    const label = mode === "rhythm" ? "Turn your beat into drum hits" : mode === "vocal" ? "Write down the notes you sang" : "Turn your tune into notes";
    plan.push({ action: "transcribe", label });
    if (h.speed) plan.push({ action: "tempo", label: "Find the speed" });
    if (h.lineup) plan.push({ action: "quantize", label: "Line the notes up with the beat" });
  }
  return plan;
}

export function pitchAmountName(amount) {
  for (const [k, v] of Object.entries(PITCH_AMOUNTS)) if (v === amount) return k[0].toUpperCase() + k.slice(1);
  return amount + "%";
}

export const speedText = bpm => Math.round(bpm) + " beats a minute";

export function isChords(harmony) {
  const starts = new Set();
  for (const n of harmony) { const t = Math.round(n.t * 1000); if (starts.has(t)) return true; starts.add(t); }
  return false;
}

const lower = s => s[0].toLowerCase() + s.slice(1);
const list = items => items.length < 2 ? items.join("") : items.slice(0, -1).join(", ") + " and " + items.at(-1);
const plural = (n, one, many = one + "s") => n + " " + (n === 1 ? one : many);
const clock = s => { const t = Math.round(s); return Math.floor(t / 60) + ":" + String(t % 60).padStart(2, "0"); };

// One line under each step in the rail. versions is null when versions cannot be stored on this device.
// harmony is the harmony part's notes: it reads as chords when two of them start together, else as a harmony line.
// voice2 is how many notes the second voice in harmony holds.
export function stepSummaries({ duration = 0, notes = 0, drums = 0, harmony = [], voice2 = 0, versions = 0, tuned = false, polished = false }) {
  const sing = duration > 0 ? "Recorded " + clock(duration) + (polished ? ", cleaned up" : "") : "Nothing recorded yet";
  const notesLine = notes > 0 ? plural(notes, "note") + (tuned ? ", pitch fixed" : "") : "No notes yet";
  const parts = [];
  if (harmony.length) parts.push(isChords(harmony) ? "Chords" : "A harmony line");
  if (voice2 > 0) parts.push(parts.length ? "a second voice" : "A second voice");
  if (drums > 0) parts.push(parts.length ? "drums" : "Drums");
  const song = parts.length ? parts.slice(0, -1).join(", ") + (parts.length > 1 ? " and " : "") + parts.at(-1) + " added" : "Melody only";
  const share = versions === null ? "Versions not available" : versions > 0 ? plural(versions, "version") + " saved" : "No versions saved";
  // UX.5: the guided rail's Your song, every part in a few words.
  const all = [notes > 0 && plural(notes, "note"), ...parts.map(p => p.toLowerCase())].filter(Boolean);
  const yoursong = all.length ? all[0][0].toUpperCase() + list(all).slice(1) : "Nothing yet";
  return { sing, notes: notesLine, song, share, yoursong };
}

// UX.5: the state line on each of Your song's tiles, in plain words. project is the studio state (or a saved project);
// recorded, polished and tuned say which recordings there are; sounds names the melody's instrument as the menu shows it.
export function viewSummaries(project, { recorded = false, polished = false, tuned = false, sounds = {} } = {}) {
  const p = project ?? {}, notes = p.notes?.length ?? 0, harmony = p.harmony ?? [], voice2 = p.voice2?.length ?? 0;
  const drums = p.drums?.length ?? 0, words = String(p.lyrics ?? "").split(/\s+/).filter(w => /[\p{L}\p{N}]/u.test(w)).length;
  const sung = p.voice2_sung && !p.voice2_sung.muted, genre = genreById(p.genre);
  return {
    voice: recorded ? (polished ? "Cleaned up" : "Not cleaned up") + ", " + (tuned ? "pitch fixed" : "pitch as sung") : "Nothing recorded yet",
    notes: notes ? plural(notes, "note") : "No notes yet",
    timing: speedText(Number.isFinite(p.bpm) ? p.bpm : 100),
    words: words ? plural(words, "word") : "No words yet",
    chords: harmony.length ? (isChords(harmony) ? "Chords added" : "A line added") : "Not added",
    voice2: voice2 ? plural(voice2, "note") + (sung ? ", sung in your voice" : "") : "Not added",
    beat: drums ? plural(drums, "hit") : "Not added",
    sound: (genre ? genre.name : "No genre") + (sounds.melody ? ", melody on " + sounds.melody : ""),
    sections: p.sections?.length ? plural(p.sections.length, "section") : "No sections yet",
    takes: takesLine(p.takes?.list?.length ?? (recorded ? 1 : 0), p.layers?.length ?? 0),
    practise: notes ? "Sing along, note by note" : "Needs a tune first",
    ask: p.melody_locked !== false ? "Your melody is protected" : "Tandem may change your melody",
  };
}

// UX.8: Share's "In your song", one line per part the song has (in the views' order), each naming its view and saying its
// state in viewSummaries' words; a part the song does not have has no line. Same arguments as viewSummaries.
export function songLines(project, options = {}) {
  const p = project ?? {}, lines = viewSummaries(p, options);
  const has = {
    voice: !!options.recorded,
    notes: (p.notes?.length ?? 0) > 0,
    words: lines.words !== "No words yet",
    chords: (p.harmony?.length ?? 0) > 0,
    voice2: (p.voice2?.length ?? 0) > 0,
    beat: (p.drums?.length ?? 0) > 0,
  };
  return VIEWS.filter(v => has[v.id]).map(v => ({ view: v.id, name: v.name, text: lines[v.id] }));
}

function takesLine(takes, layers) {
  if (!takes && !layers) return "Nothing recorded yet";
  return [takes && plural(takes, "take"), layers && plural(layers, "layer")].filter(Boolean).join(", ");
}

// UX.5: the one tile marked Suggested next: chords once there is a tune without them, then a beat, then Share.
export function suggestNext(project) {
  const p = project ?? {};
  if ((p.notes?.length ?? 0) > 0 && !(p.harmony?.length)) return "chords";
  if (!(p.drums?.length)) return "beat";
  return "share";
}

const index = id => STEPS.findIndex(s => s.id === id);
export const nextStep = id => { const i = index(id); return i >= 0 && i < STEPS.length - 1 ? STEPS[i + 1].id : null; };
export const previousStep = id => { const i = index(id); return i > 0 ? STEPS[i - 1].id : null; };

// UX.4: the Sing step's one sentence about what happens when the take stops, from afterTake's plan.
export function planSentence(plan) {
  if (!plan.length) return "When you stop, Tandem lets you hear your take. Every helper for this kind of recording is off.";
  return "When you stop, Tandem will " + list(plan.map(a => lower(a.label))) + ", then let you hear it.";
}

// UX.4: What Tandem did, one line per helper of the plan after the take, from the states runHelpers gave each
// (done, skipped, failed; none when it never ran) and the sentence it left (notes[action]).
const PAST = Object.freeze({ Clean: "Cleaned", Fix: "Fixed", Turn: "Turned", Write: "Wrote", Find: "Found", Line: "Lined" });
export function pastTense(label) {
  const [verb, ...rest] = label.split(" ");
  return verb in PAST ? [PAST[verb], ...rest].join(" ") : label;
}
export function takeReport(plan, states = {}, notes = {}) {
  return plan.map(({ action, label }) => {
    const state = states[action] ?? "notrun", note = notes[action] ? String(notes[action]).trim() : "";
    const text = state === "done" ? pastTense(label) + (note ? ". " + note : "")
      : state === "skipped" ? "Skipped: " + lower(label) + (note ? ". " + note : "")
      : state === "failed" ? "Could not " + lower(label) + (note ? ": " + note : "")
      : "Not done: " + lower(label);
    return { action, state, text };
  });
}

// UX.5, UX.7: the studio's own elements the guided view shows, each moved into a slot of a guided screen while the guided view
// is shown and put back in its place for Show every control (the studio page's relocate). A selector, then the slot's id.
export const MOVES = Object.freeze([
  ["#transport", "slot-timeline"], ["#melodyroll", "slot-roll"], ["#melodytools", "slot-roll"], ["#melodymore", "slot-more"],
  ["#lyricsbox", "slot-words"], ["#wave", "slot-wave"], ["#whatsent", "slot-chat"], ["#chat", "slot-chat"], ["#chatform", "slot-chat"],
  // Sing: Recording options.
  ["#recoptions", "slot-recopts"],
  // Voice: Clean up the sound in view; hear it as recorded, the downloads, the pitch line and Separate under More.
  ["#polishgroup", "slot-voice"], ["#original", "slot-voice-hear"], ["#playtuned", "slot-voice-hear"], ["#downloadtuned", "slot-voice-hear"],
  ["#tunelinetools", "slot-voice-more"], ["#vocalnoteeditor", "slot-voice-more"], ["#vocalnoteinfo", "slot-voice-more"],
  ["#separaterow", "slot-voice-more"], ["#separateinfo", "slot-voice-more"],
  // Notes: More tools also holds + Note and Clear, the phrases and the MIDI keyboard.
  ["#notesbar", "slot-notes-more"], ["#phrasegroup", "slot-notes-more"], ["#miditrack", "slot-notes-more"],
  // Timing: the grid, swing and strength under More.
  ["#quantizeopts", "slot-timing-more"], ["#quantize", "slot-timing-more"],
  // Chords: the chord names and Change a chord in view, the chord notes under More.
  ["#chordstrip", "slot-chords"], ["#chordtools", "slot-chords"], ["#harmonyroll", "slot-chords-more"], ["#harmonyeditgroup", "slot-chords-more"],
  // Second voice: the sung harmony's own controls in view, the copy and its notes under More.
  ["#playvoice2sung", "slot-voice2sung"], ["#voice2sungmutebox", "slot-voice2sung"], ["#removevoice2sung", "slot-voice2sung"],
  ["#voice2copygroup", "slot-voice2-more"], ["#voice2roll", "slot-voice2-more"], ["#voice2editgroup", "slot-voice2-more"],
  // Beat: the drum roll in view, how long, keep and single hits under More.
  ["#drumroll", "slot-beat"], ["#grooveopts", "slot-beat-more"], ["#hitsgroup", "slot-beat-more"],
  // Sound: a mixer strip a part, the Mac app's band and voice as instrument, MIDI out under More.
  ...["voice", "melody", "harmony", "voice2", "voice2_sung", "drums"].map(part => ['.mixstrip[data-mix="' + part + '"]', "slot-mix-" + part]),
  ["#bandtrack", "slot-band"], ['.mixstrip[data-mix="band"]', "slot-band"], ["#timbretrack", "slot-timbre"], ['.mixstrip[data-mix="timbre"]', "slot-timbre"],
  ["#midioutbox", "slot-sound-more"],
  // Takes, Practise, Ask Tandem, Settings and Share.
  ["#takes", "slot-takes"], ["#layerlanes", "slot-layers"], ["#practicegroup", "slot-practise"], ["#lockgroup", "slot-ask"],
  ["#yourai", "slot-aiconn"], ["#connection", "slot-aiconn"], ["#versionlist", "slot-versions"],
].map(Object.freeze));

// UX.7: the views with a closed More fold holding the rest of their kind's controls.
export const MORE_VIEWS = Object.freeze(["voice", "notes", "timing", "chords", "voice2", "beat", "sound"]);
// UX.7: the guided screens and folds, each by the element that holds it.
export const PLACES = Object.freeze({
  top: ".gtop", nav: ".gnav", fixed: "body", sing: '[data-panel="sing"]', "sing:options": "#grecopts", take: '[data-panel="take"]',
  song: '[data-panel="song"]', frame: '[data-panel="view"]', share: '[data-panel="share"]', "share:apps": "#gmoreapps",
  settings: "#ghelpers", "settings:ai": "#gaiconn",
  ...Object.fromEntries(VIEWS.map(v => ["view:" + v.id, '.gview[data-view="' + v.id + '"]'])),
  ...Object.fromEntries(MORE_VIEWS.map(id => ["view:" + id + ":more", id === "notes" ? "#gmoretools" : "#gmore-" + id])),
  // Only in the studio's layout (its own header and rail), and the file pickers behind their buttons.
  studio: "#allcontrols", file: "#allcontrols",
});

// UX.7: every control of index.html (a button, input, select, text box, fold, form or link with an id) and the guided screen
// or fold that shows it. "a=b" is a studio control the guided view drives from b (a selector) instead of showing it.
const PLACE_IDS = {
  fixed: "swupdate audiorescue",
  top: "gundo gredo gsettings undo=#gundo redo=#gredo",
  nav: "gback gnext gviewprev gviewdone gviewnext",
  sing: "grecord gimport gopen gdemo gnewsong gchange gcapture gopenfolder record=#grecord finish=#grecord load=#gopen newsong=#gnewsong " +
    "demo=#gdemo import=#gimport openfolder=#gopenfolder capturelink=#gcapture mode=[data-mode=melody]",
  "sing:options": "grecopts countin recclick recsong reclayer calibrate pitchguide",
  take: "gtakeplay gvoice gnotes gboth gstopnotes gtakekeep gtakeagain gtakeshare",
  song: "gplay gstop gkey gspeed gvoicein play=#gplay stop=#gstop",
  frame: "gviewback gviewjump gviewplay gviewstop gbefore gafter gputback",
  "view:voice": "gpitch gvibrato gfix gmore-voice polishstyle polish polished downloadvocal tunestrength=#gpitch vibrato=#gvibrato tune=#gfix",
  "view:voice:more": "original playtuned downloadtuned tunekey tunescale detectvocal snapvocal resetvocal separate playvocal playband downloadband usefull",
  "view:notes": "gmoretools melodydraw melodyline linekeep linecancel melodyall melodydelete melodysemidown melodysemiup",
  "view:notes:more": "melodyoctdown melodyoctup melodykeydown melodykeyup melodyfit ganalyze addnote clearnotes phraseearlier phraselater " +
    "phrasedown phraseup phraseoctdown phraseoctup phrasecopy midiconnect midiinput midirecord analyze=#ganalyze",
  "view:timing": "gbpm gfindspeed gmore-timing bpm=#gbpm detecttempo=#gfindspeed",
  "view:timing:more": "grid swing qstrength quantize",
  "view:words": "lyrics",
  "view:chords": "gkeysel gchords gbass gnoharm gmore-chords chordroot chordquality harmonystyle=#gchords genharmony=#gchords " +
    "harmonykey=#gkeysel clearharmony=#gnoharm",
  "view:chords:more": "harmonydraw harmonyall harmonydelete harmonyoctdown harmonyoctup harmonykeydown harmonykeyup harmonysemidown harmonysemiup",
  "view:voice2": "gvoice2create gsingvoice2 gnovoice2 gvoice2next gvoice2keep gvoice2cancel gmore-voice2 playvoice2sung voice2sungmute " +
    "removevoice2sung voice2create=#gvoice2create voice2next=#gvoice2next voice2keep=#gvoice2keep voice2cancel=#gvoice2cancel singvoice2=#gsingvoice2",
  "view:voice2:more": "voice2interval voice2dup clearvoice2 voice2draw voice2all voice2delete voice2octdown voice2octup voice2keydown voice2keyup " +
    "voice2semidown voice2semiup",
  "view:beat": "gbeat ggroove ggrooveadd gnodrums gmore-beat groove=#ggroove addgroove=#ggrooveadd",
  "view:beat:more": "groovebars groovekeep drum addhit clearhits",
  "view:sound": "ggenre ginstrument gharminst gvoice2inst gmore-sound bandstyle bandfollows banddrums genband playbandtrack bandmute removeband " +
    "timbreinstrument gentimbre playtimbretrack timbremute removetimbre genre=#ggenre instrument=#ginstrument harmonyinstrument=#gharminst " +
    "voice2instrument=#gvoice2inst",
  "view:sound:more": "midioutput midichannel",
  "view:sections": "gtimeline loop clearloop evolution sectionname marksection sectionrepeat sectionearlier sectionlater sectiondelete sectionunmark",
  "view:takes": "grecordlayer comptake compfrom compto compin comploop",
  "view:practise": "practice warmup addwarmup practiceforget practicestop practicekeep practiceask",
  "view:ask": "melodylock whatsent chatform prompt",
  settings: "ghelpersback gcleanup gpitchname gtuneengine gtranscriber gbeatstyle gshowall greset transcriber=#gtranscriber tuneengine=#gtuneengine",
  "settings:ai": "aiprovider aimodel aibaseurl aikey aisave aiforget connection api token connect",
  share: "gshareplay gsharestop gsongname gsharevoice gsharesong gsavebundle gsavefolder gversionname gsaveversion gmoreapps gshareall songname=#gsongname " +
    "sharesong=#gsharesong savebundle=#gsavebundle savefolder=#gsavefolder versionname=#gversionname saveversion=#gsaveversion " +
    "versionreplace=[data-press=versionreplace] versionkeep=[data-press=versionkeep] exportevolution=[data-press=exportevolution]",
  "share:apps": "exportwav=[data-press=exportwav] exportstems=[data-press=exportstems] exportmusicxml=[data-press=exportmusicxml] " +
    "exportdawproject=[data-press=exportdawproject] exportmidi=[data-press=exportmidi] save=[data-press=save]",
  studio: "showguide shortcuts backtotracks",
  file: "audiofile projectfile",
};
export const CONTROL_PLACES = Object.freeze(Object.fromEntries(Object.entries(PLACE_IDS).flatMap(([place, ids]) =>
  ids.split(" ").map(entry => {
    const i = entry.indexOf("=");
    return i < 0 ? [entry, Object.freeze({ place, via: null })] : [entry.slice(0, i), Object.freeze({ place, via: entry.slice(i + 1) })];
  }))));
