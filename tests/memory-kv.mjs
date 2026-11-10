// In-memory stand-in for the IndexedDB key-value store in storage.js (same get/set/update/setMany
// contract). Values are copied in and out, like IndexedDB's structured clone. Set `failWrites` to
// an error to make every write fail the way a full IndexedDB does; nothing is written then.
import { storageError } from "../storage.js";

const clone = v => (v === undefined ? undefined : structuredClone(v));

export function memoryKV(initial = {}) {
  const data = new Map(Object.entries(initial).map(([k, v]) => [k, clone(v)]));
  const kv = {
    data,
    failWrites: null,
    writes: 0,
    async get(key) { return clone(data.get(key)); },
    async set(key, value) { kv.check(); data.set(key, clone(value)); kv.writes++; },
    async update(key, fn) {
      const [next, result] = fn(clone(data.get(key)));
      kv.check();
      data.set(key, clone(next));
      kv.writes++;
      return result;
    },
    async setMany(entries) { kv.check(); for (const [k, v] of entries) data.set(k, clone(v)); kv.writes++; },
    check() { if (kv.failWrites) throw storageError(kv.failWrites); },
  };
  return kv;
}

export function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: k => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => { data.set(k, String(v)); },
    removeItem: k => { data.delete(k); },
  };
}
