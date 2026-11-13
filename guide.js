// UI.1: the guided steps (Sing / Notes / Song / Share) and the automatic helpers.
// Pure: what the guided view shows and does next, and its settings. The studio page wires it to the controls.

export const GUIDE_KEY = "tandem-guide";

export const STEPS = Object.freeze([
  Object.freeze({ id: "sing", label: "Sing", title: "Sing your idea", next: "Next: check your notes" }),
  Object.freeze({ id: "notes", label: "Notes", title: "Check your notes", next: "Next: make it a song" }),
  Object.freeze({ id: "song", label: "Song", title: "Make it a song", next: "Next: finish and share" }),
  Object.freeze({ id: "share", label: "Share", title: "Finish and share", next: null }),
]);

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
    step: pick(r.step, STEPS.map(s => s.id), DEFAULTS.step),
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

const plural = (n, one, many = one + "s") => n + " " + (n === 1 ? one : many);
const clock = s => { const t = Math.round(s); return Math.floor(t / 60) + ":" + String(t % 60).padStart(2, "0"); };

// One line under each step in the rail. versions is null when versions cannot be stored on this device.
// harmony is the harmony part's notes: it reads as chords when two of them start together, else as a harmony line.
export function stepSummaries({ duration = 0, notes = 0, drums = 0, harmony = [], versions = 0, tuned = false, polished = false }) {
  const sing = duration > 0 ? "Recorded " + clock(duration) + (polished ? ", cleaned up" : "") : "Nothing recorded yet";
  const notesLine = notes > 0 ? plural(notes, "note") + (tuned ? ", pitch fixed" : "") : "No notes yet";
  const parts = [];
  if (harmony.length) parts.push(isChords(harmony) ? "Chords" : "A harmony line");
  if (drums > 0) parts.push(parts.length ? "drums" : "Drums");
  const song = parts.length ? parts.join(" and ") + " added" : "Melody only";
  const share = versions === null ? "Versions not available" : versions > 0 ? plural(versions, "version") + " saved" : "No versions saved";
  return { sing, notes: notesLine, song, share };
}

const index = id => STEPS.findIndex(s => s.id === id);
export const nextStep = id => { const i = index(id); return i >= 0 && i < STEPS.length - 1 ? STEPS[i + 1].id : null; };
export const previousStep = id => { const i = index(id); return i > 0 ? STEPS[i - 1].id : null; };
