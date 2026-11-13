// VOX.4: a module worker that tunes one section at a time with the WORLD WebAssembly build, so the
// page keeps drawing while it runs. The page posts {id, samples, sampleRate, strength, notes,
// scale, vibrato} (samples transferred) and gets back {id, samples, corrected} or {id, error}.
import { bindWorld, worldTune, WORLD_URL } from "./worldtune.js";

let world = null;
// A failed load (offline before the files were cached) is tried again on the next section.
const ready = () => world ??= import(WORLD_URL).then(m => m.default()).then(bindWorld).catch(e => { world = null; throw e; });

self.onmessage = async ({ data }) => {
  const { id, samples, sampleRate, strength, notes, scale, vibrato } = data;
  try {
    const result = worldTune(await ready(), samples, sampleRate, { strength, notes, scale, vibrato });
    self.postMessage({ id, samples: result.samples, corrected: result.corrected }, [result.samples.buffer]);
  } catch (e) {
    self.postMessage({ id, error: String(e?.message || e) });
  }
};
