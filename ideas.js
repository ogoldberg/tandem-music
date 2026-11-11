// Song ideas caught on the phone (MOB.1, ADR-013): each idea is one recording plus when it was made,
// its length and an optional name. The list lives in the same IndexedDB key-value store as the draft
// and versions (storage.js) and the recordings in OPFS (recordings.js), so the capture page and the
// studio share them. DOM-free so Node tests import it directly.

import { cleanLinks, linkedIds } from "./recordings.js";

export const IDEAS_KEY = "ideas";
export const MAX_IDEA_NAME = 60;

const isEntry = e => !!e && typeof e === "object" && typeof e.id === "string" && typeof e.name === "string"
  && Number.isFinite(e.savedAt) && Number.isFinite(e.duration) && !!cleanLinks({ original: e.audio }).original;

export function createIdeaStore(kv, { now = () => Date.now() } = {}) {
  if (!kv || typeof kv.get !== "function" || typeof kv.update !== "function") {
    throw TypeError("Expected a key-value store with get and update");
  }
  // Every stored entry, newest first, including ones this version does not recognise: those are
  // hidden but written back untouched. Unreadable data is an error; overwriting it would lose ideas.
  function entriesOf(value) {
    if (value === undefined) return [];
    if (!Array.isArray(value)) throw Error("Saved ideas are unreadable in this browser's storage.");
    return value;
  }
  const read = async () => entriesOf(await kv.get(IDEAS_KEY)).filter(isEntry);
  const summary = ({ id, name, savedAt, duration }) => ({ id, name, savedAt, duration });

  return {
    async list() {
      return (await read()).map(summary);
    },

    // Store a new idea for a recording already kept by recordings.js. Call it inside recordings.hold()
    // with the put, so the recording cannot be collected before it is linked here.
    async add({ duration, audio }) {
      const link = cleanLinks({ original: audio }).original;
      if (!link) throw Error("An idea needs a kept recording.");
      if (!(Number.isFinite(duration) && duration >= 0)) throw Error("An idea needs a recording length.");
      return kv.update(IDEAS_KEY, value => {
        const entries = entriesOf(value);
        const savedAt = now();
        let id = String(savedAt), n = 1;
        while (entries.some(e => e?.id === id)) id = `${savedAt}-${n++}`;
        const entry = { id, name: "", savedAt, duration, audio: link };
        return [[entry, ...entries], summary(entry)];
      });
    },

    async get(id) {
      const entry = (await read()).find(e => e.id === id);
      return entry ? { ...summary(entry), audio: { ...entry.audio } } : null;
    },

    async rename(id, name) {
      const clean = String(name ?? "").trim().slice(0, MAX_IDEA_NAME);
      return kv.update(IDEAS_KEY, value => {
        const entries = entriesOf(value);
        let found = false;
        const next = entries.map(e => (isEntry(e) && e.id === id ? (found = true, { ...e, name: clean }) : e));
        return [next, found];
      });
    },

    async remove(id) {
      return kv.update(IDEAS_KEY, value => {
        const entries = entriesOf(value);
        const kept = entries.filter(e => !(isEntry(e) && e.id === id));
        return [kept, kept.length !== entries.length];
      });
    },

    // Every recording linked from any stored entry, recognised or not, so none of them is collected.
    async audioIds() {
      return linkedIds(entriesOf(await kv.get(IDEAS_KEY)).map(e => ({ original: e?.audio })));
    },
  };
}

// What to call an idea in a list: its name, or when it was recorded.
export function ideaTitle(idea, formatTime = ms => new Date(ms).toLocaleString()) {
  return idea.name || "Idea · " + formatTime(idea.savedAt);
}

export function formatDuration(seconds) {
  const s = Number.isFinite(seconds) && seconds > 0 ? Math.round(seconds) : 0;
  return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
}
