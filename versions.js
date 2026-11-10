// Named project versions (EDIT.2): save, list, restore and delete snapshots of the project.
// Pure and DOM-free so Node tests import it directly; the studio passes window.localStorage.
// Versions live only in this browser (ADR-006: no server-side storage). Each stored version is a
// portable tandem-project object, the same shape as a saved project file, so it carries no audio.

export const VERSIONS_KEY = "tandem-versions";
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
  };
}

const isProject = p => !!p && typeof p === "object" && Array.isArray(p.notes) && Array.isArray(p.drums);
const isEntry = e => !!e && typeof e === "object" && typeof e.id === "string" && typeof e.name === "string"
  && Number.isFinite(e.savedAt) && isProject(e.project);

export function createVersionStore(storage, { now = () => Date.now(), limit = MAX_VERSIONS } = {}) {
  if (!storage || typeof storage.getItem !== "function" || typeof storage.setItem !== "function") {
    throw TypeError("Expected a Storage object");
  }

  // Every stored entry, newest first, including ones this version does not recognise (a newer
  // format or a hand edit): those are hidden from the list but written back untouched, never
  // deleted. Unparseable data is an error: overwriting it would destroy the user's versions.
  function readAll() {
    const raw = storage.getItem(VERSIONS_KEY);
    if (raw === null) return [];
    let parsed;
    try { parsed = JSON.parse(raw); } catch { throw Error("Saved versions are unreadable in this browser's storage."); }
    if (!Array.isArray(parsed)) throw Error("Saved versions are unreadable in this browser's storage.");
    return parsed;
  }
  const read = () => readAll().filter(isEntry);

  function write(entries) {
    try {
      storage.setItem(VERSIONS_KEY, JSON.stringify(entries));
    } catch (err) {
      if (err?.name === "QuotaExceededError" || /quota/i.test(err?.message ?? "")) {
        throw Error("Browser storage is full. Delete an older version, then try again.");
      }
      throw err;
    }
  }

  return {
    list() {
      return read().map(({ id, name, savedAt }) => ({ id, name, savedAt }));
    },

    save(name, project) {
      const clean = String(name ?? "").trim().slice(0, MAX_NAME_LENGTH);
      if (!clean) throw Error("Give the version a name.");
      if (!isProject(project)) throw Error("Only a project with note and drum lists can be saved.");
      const entries = readAll();
      const savedAt = now();
      let id = String(savedAt), n = 1;
      while (entries.some(e => e?.id === id)) id = `${savedAt}-${n++}`;
      const entry = { id, name: clean, savedAt, project: projectFromState(project) };
      // The limit counts recognised versions only; the oldest of those beyond it are dropped.
      let kept = 0;
      write([entry, ...entries].filter(e => !isEntry(e) || ++kept <= limit));
      return { id, name: clean, savedAt };
    },

    get(id) {
      const entry = read().find(e => e.id === id);
      return entry ? entry.project : null;
    },

    remove(id) {
      const entries = readAll();
      const kept = entries.filter(e => !(isEntry(e) && e.id === id));
      if (kept.length === entries.length) return false;
      write(kept);
      return true;
    },
  };
}
