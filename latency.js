// Lining a take up with the song (REC.3). What the singer hears comes out of the speakers or headphones a little after
// the audio clock schedules it, and their voice reaches the capture a little after they sing: the round trip. A take
// recorded over the song is moved earlier by that much, so a note sung with a beat lands on the beat. The round trip
// is measured once per microphone and output by playing clicks and recording them back (calibration), and until then
// estimated from what the browser reports. The page passes in its storage and audio context; the timing, the click
// and its detection are pure, so the Node tests run them on a synthetic loopback.

import { startCapture, createTakeCollector } from "./take.js";

// The calibration: CLICKS clicks EVERY seconds apart, the first LEAD after the start; each is looked for in the
// WINDOW seconds after it was played, so a round trip up to WINDOW (slow Bluetooth included) is found.
export const CALIBRATION = Object.freeze({ clicks: 6, every: 0.75, lead: 0.3, window: 0.7 });
// The clicks found must agree within SPREAD seconds; at least NEEDED of them must be found.
const SPREAD = 0.004, NEEDED = 4;
// A round trip longer than this is not believed.
export const MAX_LATENCY = 1;
export const LATENCY_KEY = "tandem-latency";

const round4 = x => Math.round(x * 1e4) / 1e4;

// The calibration click: a 3 kHz tone that starts at full level and dies away in a few milliseconds, so its onset is
// sharp and a phone's small speaker plays it well.
export function calibrationClick(rate) {
  const n = Math.round(rate * 0.008), out = new Float32Array(n);
  for (let i = 0; i < n; i++) out[i] = 0.9 * Math.sin(2 * Math.PI * 3000 * i / rate) * Math.exp(-i / (rate * 0.0015));
  return out;
}

// When the clicks play, in seconds from the start of the calibration recording.
export function clickPlan() {
  return Array.from({ length: CALIBRATION.clicks }, (_, i) => round4(CALIBRATION.lead + i * CALIBRATION.every));
}

// The round trip in a calibration recording (`samples` at `rate`, from the calibration's start) of clicks played at
// `times`: in the window after each click, its onset is the first sample at a third of that window's peak, and only a
// window whose peak stands well above the recording's noise counts. The onsets must agree; their median is the answer.
export function detectLatency(samples, rate, times, { window = CALIBRATION.window } = {}) {
  if (!(rate > 0) || !samples?.length) throw Error("The calibration recording is empty.");
  const mags = Float32Array.from(samples, Math.abs).sort(), noise = mags[Math.floor(mags.length / 2)];
  const found = [];
  for (const t of times) {
    const a = Math.round(t * rate), b = Math.min(samples.length, Math.round((t + window) * rate));
    let peak = 0;
    for (let i = a; i < b; i++) peak = Math.max(peak, Math.abs(samples[i]));
    if (!(peak > 0.003) || peak < 10 * noise) continue;
    let i = a;
    while (i < b && Math.abs(samples[i]) < peak / 3) i++;
    found.push(i / rate - t);
  }
  const sorted = [...found].sort((x, y) => x - y), median = sorted[Math.floor(sorted.length / 2)];
  const agree = sorted.filter(x => Math.abs(x - median) <= SPREAD / 2);
  if (agree.length < Math.min(NEEDED, times.length)) {
    throw Error(found.length < Math.min(NEEDED, times.length)
      ? "The microphone did not hear the clicks. Turn the sound up, or hold the headphones to the microphone, and try again."
      : "The clicks came back at different delays. Try again somewhere quieter.");
  }
  const seconds = round4(agree.reduce((s, x) => s + x, 0) / agree.length);
  return { seconds, heard: agree.length, of: times.length };
}

// The round trip as the browser reports it: the output's latency, the context's own and the microphone's.
export function estimateLatency({ outputLatency = 0, baseLatency = 0, inputLatency = 0 } = {}) {
  const ok = x => (Number.isFinite(x) && x > 0 ? x : 0);
  return round4(Math.min(MAX_LATENCY, ok(outputLatency) + ok(baseLatency) + ok(inputLatency)));
}

// Which microphone and output a measurement belongs to.
export function deviceKey({ input = "", output = "" } = {}) {
  return (String(input) || "default") + "|" + (String(output) || "default");
}

function readAll(storage) {
  try {
    const v = JSON.parse(storage?.getItem(LATENCY_KEY) || "{}");
    return v && typeof v === "object" && !Array.isArray(v) ? v : {};
  } catch { return {}; }
}

// The measured round trip for a device, or null.
export function readLatency(storage, key) {
  const e = readAll(storage)[key];
  return e && Number.isFinite(e.seconds) && e.seconds >= 0 && e.seconds <= MAX_LATENCY ? e.seconds : null;
}

export function saveLatency(storage, key, seconds, at = Date.now()) {
  if (!(Number.isFinite(seconds) && seconds >= 0 && seconds <= MAX_LATENCY)) throw Error("A round trip is 0 to 1 second.");
  const all = readAll(storage);
  all[key] = { seconds: round4(seconds), at };
  storage.setItem(LATENCY_KEY, JSON.stringify(all));
}

// The round trip a take uses: the measured one, else the estimate.
export function takeLatency(storage, key, estimate) {
  const measured = readLatency(storage, key);
  return measured === null ? { seconds: estimateLatency(estimate), measured: false } : { seconds: measured, measured: true };
}

export function latencyText({ seconds, measured }) {
  return "Takes are moved " + Math.round(seconds * 1000) + " ms earlier to line up (" + (measured ? "measured" : "estimated: measure it for this microphone and output") + ")";
}

// In the page: the key for the microphone of `stream` and the output `ac` plays to, with the output's name where the
// browser tells it (a Bluetooth headset and the speaker are different outputs).
export async function deviceKeyFor(ac, stream, mediaDevices) {
  const input = stream?.getAudioTracks?.()[0]?.getSettings?.().deviceId || "";
  let output = ac.sinkId || "";
  try {
    const want = output || "default", outs = (await mediaDevices.enumerateDevices()).filter(d => d.kind === "audiooutput");
    const d = outs.find(x => x.deviceId === want);
    if (d?.label) output = d.label;
  } catch {}
  return deviceKey({ input, output });
}

// The browser's estimate for a running context and microphone stream.
export function browserEstimate(ac, stream) {
  const s = stream?.getAudioTracks?.()[0]?.getSettings?.() || {};
  return { outputLatency: ac.outputLatency, baseLatency: ac.baseLatency, inputLatency: s.latency };
}

// In the page: plays the calibration clicks in `ac` and records them back from `source` (the microphone's node).
// Resolves to detectLatency's result; the clicks are heard, so the page asks for quiet first.
export async function measureLatency(ac, source) {
  const rate = ac.sampleRate, start = ac.currentTime + 0.2, times = clickPlan();
  const collector = createTakeCollector({ zero: start, rate });
  const capture = await startCapture(ac, source, (t, channels) => collector.add(t, channels));
  const click = ac.createBuffer(1, calibrationClick(rate).length, rate);
  click.copyToChannel(calibrationClick(rate), 0);
  for (const t of times) { const s = ac.createBufferSource(); s.buffer = click; s.connect(ac.destination); s.start(start + t); }
  const end = start + times.at(-1) + CALIBRATION.window + 0.05;
  await new Promise(resolve => { const tick = () => (ac.currentTime >= end ? resolve() : setTimeout(tick, 50)); tick(); });
  await capture.flush();
  const { channels, frames } = collector.finish(end), mono = new Float32Array(frames);
  for (const ch of channels) for (let i = 0; i < frames; i++) mono[i] += ch[i] / channels.length;
  return detectLatency(mono, rate, times);
}
