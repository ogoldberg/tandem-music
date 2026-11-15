// Named project versions (EDIT.2): save, list, restore and delete snapshots of the project.
// DOM-free so Node tests import it directly. The studio passes the IndexedDB key-value store from
// storage.js (STORE.2a); before that, versions lived in localStorage under "tandem-versions" and
// storage.js migrates them. Versions live only on this device (ADR-011). Each stored version is a
// portable tandem-project object, the same shape as a saved project file, so it carries no audio;
// the entry next to it may link the recordings (recordings.js) that were loaded when it was saved.

export { VERSIONS_KEY } from "./storage.js";
import { VERSIONS_KEY } from "./storage.js";
import { cleanLinks, linkedIds } from "./recordings.js";
export const MAX_VERSIONS = 50;
export const MAX_NAME_LENGTH = 60;

export function projectFromState(state) {
  return {
    format: "tandem-project",
    version: 1,
    bpm: state.bpm,
    instrument: state.instrument,
    melody_locked: state.melody_locked !== false,
    notes: state.notes,
    drums: state.drums,
    // ARR.1c: the optional accompaniment part; a project from before it has none.
    harmony: Array.isArray(state.harmony) ? state.harmony : [],
    harmony_instrument: state.harmony_instrument || "piano",
    // HARM.1: the harmony voice, when it has notes.
    ...(Array.isArray(state.voice2) && state.voice2.length ? { voice2: state.voice2, voice2_instrument: state.voice2_instrument || "piano" } : {}),
    // GEN.2: the generated band, when there is one (its audio is the "band" recording, never in the project).
    ...(state.band ? { band: state.band } : {}),
    // TIMBRE.1: the voice played as an instrument, when there is one (its audio is the "timbre" recording).
    ...(state.timbre ? { timbre: state.timbre } : {}),
    // HARM.3: the take sung on the harmony voice, when there is one (its audio is the "voice2_sung" recording).
    ...(state.voice2_sung ? { voice2_sung: state.voice2_sung } : {}),
    // TRACK.1: the recorded layers, when there are any (their audio is the layer recordings, never in the project).
    ...(Array.isArray(state.layers) && state.layers.length ? { layers: state.layers } : {}),
    // TAKE.1: the kept takes and the comp of them the song uses, once there is a second take (their audio is
    // the take recordings; the comp is the "original" recording).
    ...(state.takes && typeof state.takes === "object" ? { takes: state.takes } : {}),
    // SONG.1: the song's named sections, when there are any (sections.js cleanSections).
    ...(Array.isArray(state.sections) && state.sections.length ? { sections: state.sections } : {}),
    // LYR.1: the words for the melody, when there are any (lyrics.js cleanLyrics).
    ...(typeof state.lyrics === "string" && state.lyrics.trim() ? { lyrics: state.lyrics } : {}),
    // MIX.1: the mixer, when anything in it differs from the defaults (mixer.js cleanMix).
    ...(state.mix && typeof state.mix === "object" && Object.keys(state.mix).length ? { mix: state.mix } : {}),
  };
}

const isProject = p => !!p && typeof p === "object" && Array.isArray(p.notes) && Array.isArray(p.drums);
const isEntry = e => !!e && typeof e === "object" && typeof e.id === "string" && typeof e.name === "string"
  && Number.isFinite(e.savedAt) && isProject(e.project);

export function createVersionStore(kv, { now = () => Date.now(), limit = MAX_VERSIONS } = {}) {
  if (!kv || typeof kv.get !== "function" || typeof kv.update !== "function") {
    throw TypeError("Expected a key-value store with get and update");
  }

  // Every stored entry, newest first, including ones this version does not recognise (a newer
  // format or a hand edit): those are hidden from the list but written back untouched, never
  // deleted. Unreadable data is an error: overwriting it would destroy the user's versions.
  function entriesOf(value) {
    if (value === undefined) return [];
    if (!Array.isArray(value)) throw Error("Saved versions are unreadable in this browser's storage.");
    return value;
  }
  const read = async () => entriesOf(await kv.get(VERSIONS_KEY)).filter(isEntry);
  const copy = x => JSON.parse(JSON.stringify(x));

  return {
    async list() {
      return (await read()).map(({ id, name, savedAt }) => ({ id, name, savedAt }));
    },

    // Read-modify-write in one transaction, so a version saved in another tab at the same time is kept.
    async save(name, project, audio = null) {
      const clean = String(name ?? "").trim().slice(0, MAX_NAME_LENGTH);
      if (!clean) throw Error("Give the version a name.");
      if (!isProject(project)) throw Error("Only a project with note and drum lists can be saved.");
      const stored = copy(projectFromState(project));
      const links = cleanLinks(audio);
      return kv.update(VERSIONS_KEY, value => {
        const entries = entriesOf(value);
        const savedAt = now();
        let id = String(savedAt), n = 1;
        while (entries.some(e => e?.id === id)) id = `${savedAt}-${n++}`;
        const entry = { id, name: clean, savedAt, project: stored };
        if (Object.keys(links).length) entry.audio = links;
        // The limit counts recognised versions only; the oldest of those beyond it are dropped.
        let kept = 0;
        return [[entry, ...entries].filter(e => !isEntry(e) || ++kept <= limit), { id, name: clean, savedAt }];
      });
    },

    async get(id) {
      const entry = (await read()).find(e => e.id === id);
      return entry ? copy(entry.project) : null;
    },

    // The recording links saved with a version, or null if it has none.
    async audio(id) {
      const entry = (await read()).find(e => e.id === id);
      const links = cleanLinks(entry?.audio);
      return Object.keys(links).length ? links : null;
    },

    // Every recording linked from any stored entry, recognised or not, so none of them is collected.
    async audioIds() {
      return linkedIds(entriesOf(await kv.get(VERSIONS_KEY)).map(e => e?.audio));
    },

    async remove(id) {
      return kv.update(VERSIONS_KEY, value => {
        const entries = entriesOf(value);
        const kept = entries.filter(e => !(isEntry(e) && e.id === id));
        return [kept, kept.length !== entries.length];
      });
    },
  };
}
