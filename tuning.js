// Chunked pitch correction (PERF.2). The server's /api/tune accepts one short clip per request
// (25 s cap, Vercel's 4.5 MB body limit), so long recordings are split into overlapping chunks,
// each tuned by the server, and stitched back with linear crossfades. Pure functions: the network
// call is injected, so tests run without a server. The Mac app's own server (DESK.2) takes up to
// 10 minutes per request; the page passes its limits from /api/config as chunkSeconds/maxNotes.

export const CHUNK_SECONDS = 16;
export const OVERLAP_SECONDS = 1;
export const MAX_NOTES_PER_REQUEST = 128;
export const MIN_NOTE_SECONDS = 0.05;

// Split `total` samples into chunks of `chunk` samples that overlap by `overlap` samples.
// Every chunk is at most `chunk` long and the last one is always longer than `overlap`.
export function planChunks(total, sampleRate, chunkSeconds = CHUNK_SECONDS, overlapSeconds = OVERLAP_SECONDS) {
  if (!(total > 0)) throw Error("Empty recording");
  const chunk = Math.round(chunkSeconds * sampleRate), overlap = Math.round(overlapSeconds * sampleRate);
  if (!(overlap >= 0 && overlap < chunk)) throw Error("Overlap must be shorter than a chunk");
  if (total <= chunk) return [{ start: 0, end: total }];
  const step = chunk - overlap, count = Math.ceil((total - overlap) / step), plan = [];
  for (let k = 0; k < count; k++) plan.push({ start: k * step, end: k === count - 1 ? total : k * step + chunk });
  return plan;
}

// Note targets for one chunk, in the chunk's own time base: keep notes that overlap
// [startSec, endSec), clip them to the chunk and shift them to start at 0.
export function notesForChunk(notes, startSec, endSec, maxNotes = MAX_NOTES_PER_REQUEST) {
  const out = [];
  for (const n of notes || []) {
    const t0 = Math.max(n.t, startSec), t1 = Math.min(n.t + n.d, endSec);
    if (t1 - t0 < MIN_NOTE_SECONDS) continue;
    out.push({ m: n.m, t: round3(t0 - startSec), d: round3(t1 - t0) });
  }
  if (out.length > maxNotes)
    throw Error(`Too many note targets (${out.length}) in one ${Math.round(endSec - startSec)} s section; the limit is ${maxNotes}`);
  return out;
}

const round3 = x => Math.round(x * 1000) / 1000;

export const SEAM_SECONDS = 0.04;
export const SEAM_MARGIN_SECONDS = 0.15;

// Choose where to cross from chunk k to chunk k+1: a short window at the quietest point of
// the input inside their overlap (a breath or consonant in real singing), away from the
// overlap's edges so WORLD has context on both sides. WORLD resynthesis starts each chunk at
// its own phase, so a long crossfade between two chunks partly cancels; a short one at a quiet
// point keeps that dip brief and soft.
export function chooseSeams(samples, plan, sampleRate, seamSeconds = SEAM_SECONDS, marginSeconds = SEAM_MARGIN_SECONDS) {
  const seams = [];
  for (let k = 1; k < plan.length; k++) {
    const lo = plan[k].start, hi = plan[k - 1].end, overlap = hi - lo;
    const len = Math.max(1, Math.min(Math.round(seamSeconds * sampleRate), overlap));
    const margin = Math.min(Math.round(marginSeconds * sampleRate), Math.floor((overlap - len) / 2));
    const first = lo + margin, last = hi - margin - len, hop = Math.max(1, Math.round(len / 4));
    let best = first, bestEnergy = Infinity;
    for (let at = first; at <= last; at += hop) {
      let e = 0;
      for (let i = at; i < at + len; i++) e += samples[i] * samples[i];
      if (e < bestEnergy) { bestEnergy = e; best = at; }
    }
    seams.push({ at: best, length: len });
  }
  return seams;
}

// Join the chunk outputs at the seams: chunk k plays alone up to its seam, the two chunks
// crossfade linearly across the seam (weights sum to 1, so identical chunks reproduce the
// input exactly) and chunk k+1 plays alone after it.
export function stitchChunks(outputs, plan, total, seams = defaultSeams(plan)) {
  if (outputs.length !== plan.length) throw Error("One output per chunk is required");
  if (seams.length !== plan.length - 1) throw Error("One seam per chunk boundary is required");
  const out = new Float32Array(total);
  for (let k = 0; k < plan.length; k++) {
    const { start, end } = plan[k], y = outputs[k];
    if (y.length !== end - start) throw Error(`Chunk ${k + 1} came back with ${y.length} samples, expected ${end - start}`);
    const inSeam = seams[k - 1], outSeam = seams[k];
    if (inSeam && (inSeam.at < start || inSeam.at + inSeam.length > plan[k - 1].end)) throw Error(`Seam ${k} lies outside the overlap`);
    const from = inSeam ? inSeam.at : start, to = outSeam ? outSeam.at + outSeam.length : end;
    for (let s = from; s < to; s++) {
      let w = 1;
      if (inSeam && s < inSeam.at + inSeam.length) w = (s - inSeam.at + 1) / (inSeam.length + 1);
      else if (outSeam && s >= outSeam.at) w = (outSeam.at + outSeam.length - s) / (outSeam.length + 1);
      out[s] += w * y[s - start];
    }
  }
  return out;
}

// Crossfade across each whole overlap.
const defaultSeams = plan => plan.slice(1).map((c, k) => ({ at: c.start, length: plan[k].end - c.start }));

export function encodeWav16(samples, sampleRate) {
  const buf = new ArrayBuffer(44 + samples.length * 2), v = new DataView(buf);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); str(8, "WAVE"); str(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, sampleRate, true);
  v.setUint32(28, sampleRate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); str(36, "data");
  v.setUint32(40, samples.length * 2, true);
  // Same 32768 scale as decodeWav16, so an untouched chunk round-trips exactly; clip to the int16 range.
  for (let i = 0; i < samples.length; i++) v.setInt16(44 + i * 2, Math.max(-32768, Math.min(32767, Math.round(samples[i] * 32768))), true);
  return buf;
}

// Parse a mono 16-bit PCM WAV (what /api/tune returns) without resampling, so the samples
// line up with the chunk plan. decodeAudioData would resample to the AudioContext rate.
export function decodeWav16(arrayBuffer) {
  const v = new DataView(arrayBuffer), tag = o => String.fromCharCode(v.getUint8(o), v.getUint8(o + 1), v.getUint8(o + 2), v.getUint8(o + 3));
  if (arrayBuffer.byteLength < 12 || tag(0) !== "RIFF" || tag(8) !== "WAVE") throw Error("Tuned audio is not a WAV file");
  let fmt = null, o = 12;
  while (o + 8 <= arrayBuffer.byteLength) {
    const id = tag(o), size = v.getUint32(o + 4, true), body = o + 8;
    if (id === "fmt ") fmt = { format: v.getUint16(body, true), channels: v.getUint16(body + 2, true), sampleRate: v.getUint32(body + 4, true), bits: v.getUint16(body + 14, true) };
    else if (id === "data") {
      if (!fmt || fmt.format !== 1 || fmt.channels !== 1 || fmt.bits !== 16) throw Error("Tuned audio must be mono 16-bit PCM");
      const n = Math.floor(Math.min(size, arrayBuffer.byteLength - body) / 2), samples = new Float32Array(n);
      for (let i = 0; i < n; i++) samples[i] = v.getInt16(body + i * 2, true) / 32768;
      return { sampleRate: fmt.sampleRate, samples };
    }
    o = body + size + (size % 2);
  }
  throw Error("Tuned audio has no data chunk");
}

// Tune a whole recording. `send({wav, notes, strength})` posts one chunk and resolves to
// {wav: ArrayBuffer, corrected: number}; it rejects with an error carrying `retryAfter`
// (seconds) when the server rate-limits, and the chunk is retried after that wait.
// VOX.4: `tune({samples, sampleRate, notes, strength})` tunes one chunk on the device instead,
// resolving to {samples: Float32Array, corrected: number}; the chunk is never encoded as a WAV.
// With note targets set, a chunk that has none keeps its original audio: the server snaps
// every voiced frame of a request without targets, but leaves audio outside the targets of a
// request that has them alone, so sending it would tune one take two different ways.
export async function tuneInChunks(samples, sampleRate, { strength, notes, send, tune = null, sleep = ms => new Promise(r => setTimeout(r, ms)), onProgress = () => {}, maxRetries = 4, chunkSeconds = CHUNK_SECONDS, maxNotes = MAX_NOTES_PER_REQUEST }) {
  const plan = planChunks(samples.length, sampleRate, chunkSeconds), outputs = [];
  let corrected = 0;
  for (let k = 0; k < plan.length; k++) {
    const { start, end } = plan[k];
    const chunkNotes = notes?.length ? notesForChunk(notes, start / sampleRate, end / sampleRate, maxNotes) : null;
    if (chunkNotes && !chunkNotes.length) { outputs.push(samples.slice(start, end)); continue; }
    onProgress({ index: k, count: plan.length });
    const own = (k < plan.length - 1 ? plan[k + 1].start : end) - start;
    if (tune) {
      const res = await tune({ samples: samples.slice(start, end), sampleRate, notes: chunkNotes, strength });
      if (res.samples.length !== end - start) throw Error(`Chunk ${k + 1} came back with ${res.samples.length} samples, expected ${end - start}`);
      outputs.push(res.samples);
      corrected += (res.corrected || 0) * own / (end - start);
      continue;
    }
    const wav = encodeWav16(samples.subarray(start, end), sampleRate);
    for (let attempt = 0; ; attempt++) {
      try {
        const res = await send({ wav, notes: chunkNotes, strength });
        const decoded = decodeWav16(res.wav);
        if (decoded.sampleRate !== sampleRate) throw Error(`Chunk ${k + 1} came back at ${decoded.sampleRate} Hz, expected ${sampleRate} Hz`);
        outputs.push(decoded.samples);
        // Count each overlap once: credit a chunk only with the part before the next chunk starts.
        corrected += (res.corrected || 0) * own / (end - start);
        break;
      } catch (e) {
        if (e.retryAfter == null || attempt >= maxRetries) throw e;
        onProgress({ index: k, count: plan.length, waiting: e.retryAfter });
        await sleep(Math.max(1, e.retryAfter) * 1000);
      }
    }
  }
  return { samples: stitchChunks(outputs, plan, samples.length, chooseSeams(samples, plan, sampleRate)), corrected: Math.round(corrected), chunks: plan.length };
}
