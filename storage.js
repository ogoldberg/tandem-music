// On-device storage (STORE.2a, ADR-011): the browser draft and named versions live in IndexedDB.
// DOM-free so Node tests import it directly: the IndexedDB factory and the old localStorage are
// passed in. Values are stored as structured clones of plain JSON data.

export const DB_NAME = "tandem";
export const DB_VERSION = 1;
export const KV_STORE = "kv";
export const DRAFT_KEY = "draft";
export const VERSIONS_KEY = "versions";
// Where versions before STORE.2a kept the draft and versions.
export const LEGACY_DRAFT_KEY = "tandem-draft";
export const LEGACY_VERSIONS_KEY = "tandem-versions";

const done = req => new Promise((resolve, reject) => {
  req.onsuccess = () => resolve(req.result);
  req.onerror = () => reject(req.error);
});
const finished = tx => new Promise((resolve, reject) => {
  tx.oncomplete = () => resolve();
  tx.onabort = () => reject(tx.error ?? Error("The storage transaction was aborted."));
  tx.onerror = () => reject(tx.error);
});

const isQuota = err => err?.name === "QuotaExceededError" || /quota/i.test(err?.message ?? "");
export function storageError(err) {
  return isQuota(err) ? Error("Browser storage is full. Delete older versions or recordings, then try again.") : err;
}

// A small key-value store over one IndexedDB object store. Every call opens its own transaction
// synchronously, so writes land in the order they were made, and a transaction opened later
// (in this page or another) sees them.
export async function openKV(indexedDB, { name = DB_NAME } = {}) {
  if (!indexedDB?.open) throw Error("This browser has no IndexedDB, so work cannot be saved on this device.");
  const req = indexedDB.open(name, DB_VERSION);
  req.onupgradeneeded = () => {
    if (!req.result.objectStoreNames.contains(KV_STORE)) req.result.createObjectStore(KV_STORE);
  };
  req.onblocked = () => {};
  const db = await done(req);
  // Let a newer version of the app (or a test deleting the database) take over.
  db.onversionchange = () => db.close();

  const run = (mode, body) => {
    const tx = db.transaction(KV_STORE, mode);
    const result = body(tx.objectStore(KV_STORE));
    return finished(tx).then(() => result.value, err => { throw storageError(err); });
  };
  return {
    get(key) {
      return run("readonly", s => { const out = {}; s.get(key).onsuccess = e => { out.value = e.target.result; }; return out; });
    },
    set(key, value) {
      return run("readwrite", s => { s.put(value, key); return {}; });
    },
    // Read, change and write one key in a single transaction, so two tabs cannot lose each other's
    // change. fn gets the current value (undefined if none) and returns [next, result]; when it
    // throws, nothing is written and the error is passed on.
    update(key, fn) {
      const tx = db.transaction(KV_STORE, "readwrite");
      const store = tx.objectStore(KV_STORE);
      let result, failure;
      store.get(key).onsuccess = e => {
        try {
          const [next, out] = fn(e.target.result);
          result = out;
          store.put(next, key);
        } catch (err) {
          failure = err;
          tx.abort();
        }
      };
      return finished(tx).then(() => result, err => { throw failure ?? storageError(err); });
    },
    // Several keys at once, all or nothing.
    setMany(entries) {
      return run("readwrite", s => { for (const [k, v] of entries) s.put(v, k); return {}; });
    },
    close() { db.close(); },
  };
}

// Brings in what an older version of the app left in localStorage, then removes it there. It runs
// on every start, so data an old copy of the app (an old cached tab, say) writes later is also
// picked up. Versions are merged by id (ones already here win); a legacy draft replaces the
// stored draft, because only an older app could have written it after the last start. Data that
// cannot be parsed is left in localStorage untouched and reported, never deleted.
export async function migrateLegacy(kv, local) {
  const report = { draft: false, versions: 0, problems: [] };
  let rawDraft, rawVersions;
  try {
    rawDraft = local?.getItem(LEGACY_DRAFT_KEY) ?? null;
    rawVersions = local?.getItem(LEGACY_VERSIONS_KEY) ?? null;
  } catch {
    return report; // localStorage itself is unavailable: nothing to bring in.
  }
  const writes = [], clear = [];

  if (rawDraft !== null) {
    let draft;
    try { draft = JSON.parse(rawDraft); } catch { draft = undefined; }
    if (draft && typeof draft === "object" && Array.isArray(draft.notes) && Array.isArray(draft.drums)) {
      writes.push([DRAFT_KEY, draft]);
      report.draft = true;
    }
    // A draft the app could never open is dropped, as the old start-up code ignored it.
    clear.push(LEGACY_DRAFT_KEY);
  }

  let legacyVersions = null;
  if (rawVersions !== null) {
    try { legacyVersions = JSON.parse(rawVersions); } catch { legacyVersions = null; }
    if (!Array.isArray(legacyVersions)) {
      legacyVersions = null;
      report.problems.push("Versions saved by an older version of Tandem could not be read; they were left in this browser's localStorage.");
    }
  }

  if (legacyVersions) {
    // The merge reads and writes in one transaction, so a version another tab saves meanwhile is kept.
    // If the stored versions are unreadable, nothing is merged and both copies stay; the draft still moves.
    const unreadable = Error("Saved versions are unreadable in this browser's storage, so versions saved by an older version of Tandem were left in this browser's localStorage.");
    let versionsMoved = true;
    report.versions = await kv.update(VERSIONS_KEY, current => {
      const existing = current === undefined ? [] : current;
      if (!Array.isArray(existing)) throw unreadable;
      const ids = new Set(existing.map(e => e?.id).filter(id => typeof id === "string"));
      const added = legacyVersions.filter(e => !(typeof e?.id === "string" && ids.has(e.id)));
      // Newest first, as the version list keeps them.
      const merged = [...existing, ...added].sort((a, b) => (Number(b?.savedAt) || 0) - (Number(a?.savedAt) || 0));
      return [merged, added.length];
    }).catch(err => {
      if (err !== unreadable) throw err;
      versionsMoved = false;
      report.problems.push(err.message);
      return 0;
    });
    if (versionsMoved) clear.push(LEGACY_VERSIONS_KEY);
  }
  if (writes.length) await kv.setMany(writes);
  for (const key of clear) { try { local.removeItem(key); } catch { /* keep going */ } }
  return report;
}

// Whether the browser has promised to keep this site's storage (ADR-011). request() asks for it;
// browsers may grant it silently, prompt, or refuse.
export async function persistence(manager, { request = false } = {}) {
  if (!manager?.persisted) return "unsupported";
  if (await manager.persisted()) return "persisted";
  if (request && manager.persist && await manager.persist()) return "persisted";
  return "best-effort";
}

export const PERSISTENCE_TEXT = {
  persisted: "This browser will keep saved work until you clear it. Export a project file to move work to another device.",
  "best-effort": "This browser may clear saved work when space runs low. Export project files you want to keep.",
  unsupported: "This browser cannot promise to keep saved work. Export project files you want to keep.",
};
