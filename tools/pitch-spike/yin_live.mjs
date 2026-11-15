// PITCH.0: the live pitch guide's own tracker (pitch.js createPitchTracker, the code its AudioWorklet runs) over
// every clip, fed 128-frame render quanta from time 0 as the worklet gets them. Writes tracks/yin-live/<clip>.json
// for spike.py score. Usage: node tools/pitch-spike/yin_live.mjs <spike folder>
import { readFileSync, writeFileSync, mkdirSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { performance } from "node:perf_hooks";
import { createPitchTracker } from "../../pitch.js";

export function readWav(buf) {
  let p = 12, rate = 0, channels = 1, bits = 16, data = null;
  while (p + 8 <= buf.length) {
    const id = buf.toString("ascii", p, p + 4), size = buf.readUInt32LE(p + 4);
    if (id === "fmt ") { channels = buf.readUInt16LE(p + 10); rate = buf.readUInt32LE(p + 12); bits = buf.readUInt16LE(p + 22); }
    if (id === "data") data = buf.subarray(p + 8, p + 8 + size);
    p += 8 + size + (size & 1);
  }
  if (bits !== 16 || !data) throw new Error("16-bit PCM only");
  const n = data.length / 2 / channels, x = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    let s = 0;
    for (let c = 0; c < channels; c++) s += data.readInt16LE((i * channels + c) * 2) / 32767;
    x[i] = s / channels;
  }
  return { x, rate };
}

export function track(x, rate, quantum = 128) {
  const tracker = createPitchTracker(rate), t = [], midi = [];
  for (let i = 0; i < x.length; i += quantum) {
    for (const r of tracker.push(x.subarray(i, i + quantum), i / rate)) {
      t.push(r.t); midi.push(r.hz ? 69 + 12 * Math.log2(r.hz / 440) : null);
    }
  }
  return { t, midi };
}

if (process.argv[1] && import.meta.url.endsWith(process.argv[1].split("/").pop())) {
  const root = process.argv[2];
  const clips = join(root, "clips"), out = join(root, "tracks", "yin-live");
  mkdirSync(out, { recursive: true });
  for (const f of readdirSync(clips).filter(f => f.endsWith(".wav")).sort()) {
    const { x, rate } = readWav(readFileSync(join(clips, f)));
    track(x.subarray(0, rate), rate);  // warm up
    const started = performance.now();
    const { t, midi } = track(x, rate);
    const seconds = (performance.now() - started) / 1000;
    const clip = f.slice(0, -4);
    writeFileSync(join(out, clip + ".json"), JSON.stringify({ tracker: "yin-live", clip, t, midi, seconds, audio_seconds: x.length / rate, load_seconds: 0 }));
    console.log(`yin-live ${clip}: ${(seconds / (x.length / rate) * 1000).toFixed(1)} ms per second of audio`);
  }
}
