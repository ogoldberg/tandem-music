// Tandem client-side transcription adapter.
// Spotify Basic Pitch is Apache-2.0 licensed. Its model runs in the browser.
// Both are served by this app (vendor/basic-pitch-1.0.1, built by
// tools/basic-pitch/build.sh, hashes in its SHA256SUMS), not by a CDN.
export const BASIC_PITCH_PACKAGE = "/vendor/basic-pitch-1.0.1/basic-pitch.mjs";
export const BASIC_PITCH_MODEL = "/vendor/basic-pitch-1.0.1/model/model.json";
import { pitchContour, mergeFragments } from "./contour.js";

// Melody transcribed into the project stays within what /api/chat and its prompt accept
// (arrangements under 60 s, at most 128 events per track).
export const PROJECT_MELODY_LIMITS = Object.freeze({ maxSeconds: 60, maxNotes: 128 });
// Vocal note targets feed chunked pitch correction (tuning.js), which handles any length,
// so they cover the whole recording. The per-request cap applies per chunk there.
export const VOCAL_TARGET_LIMITS = Object.freeze({ maxSeconds: Infinity, maxNotes: Infinity });

/** Convert the provider's note events into Tandem's portable note schema.
 * Times are in seconds, pitches in MIDI semitones. Notes are clipped to `maxSeconds`
 * and the earliest `maxNotes` are kept. With `confidence`, each note also gets `c`: Basic Pitch's
 * mean note activation clamped to 0..1 (vocal tuning targets only; the project schema has no `c`).
 */
export function normalizeBasicPitchNotes(events, { maxSeconds = PROJECT_MELODY_LIMITS.maxSeconds, maxNotes = PROJECT_MELODY_LIMITS.maxNotes, confidence = false } = {}) {
  if (!Array.isArray(events)) throw new TypeError("Expected Basic Pitch note events");
  const result = [];
  for (const event of events) {
    const pitch = Number(event.pitchMidi);
    const start = Number(event.startTimeSeconds);
    const duration = Number(event.durationSeconds);
    if (![pitch, start, duration].every(Number.isFinite)) continue;
    if (start < -0.05 || start >= maxSeconds || duration <= 0) continue;
    const t = Math.max(0, start);
    const d = Math.min(duration, maxSeconds - t);
    if (d < 0.07 || pitch < 36 || pitch > 96) continue;
    const note = { m: Math.round(pitch), t: +t.toFixed(3), d: +d.toFixed(3) };
    if (confidence) note.c = +Math.max(0, Math.min(1, Number(event.amplitude) || 0)).toFixed(2);
    result.push(note);
  }
  const sorted = result.sort((a,b)=>a.t-b.t || a.m-b.m);
  return Number.isFinite(maxNotes) ? sorted.slice(0, maxNotes) : sorted;
}

export const BASIC_PITCH_SAMPLE_RATE = 22050;

/** Render recordings at the exact sample rate expected by Basic Pitch.
 * OfflineAudioContext performs the resampling, without changing pitch or duration.
 * Dependency-inject the context for deterministic tests.
 */
export async function resampleForBasicPitch(audioBuffer, OfflineContext = globalThis.OfflineAudioContext || globalThis.webkitOfflineAudioContext) {
  if (!audioBuffer || typeof audioBuffer.getChannelData !== "function") throw new TypeError("Expected a decoded AudioBuffer");
  if (audioBuffer.sampleRate === BASIC_PITCH_SAMPLE_RATE) return audioBuffer;
  if (!OfflineContext) throw new Error("This browser doesn't support offline audio resampling.");
  const frameCount = Math.ceil(audioBuffer.duration * BASIC_PITCH_SAMPLE_RATE);
  if (frameCount <= 0) throw new Error("The recording is empty.");
  const offline = new OfflineContext(1, frameCount, BASIC_PITCH_SAMPLE_RATE);
  const source = offline.createBufferSource();
  source.buffer = audioBuffer;
  source.connect(offline.destination);
  source.start(0);
  const resampled = await offline.startRendering();
  if (resampled.sampleRate !== BASIC_PITCH_SAMPLE_RATE) throw new Error("Audio resampling failed.");
  return resampled;
}

let cachedModule;
const loadBasicPitch = () => cachedModule ||= import(BASIC_PITCH_PACKAGE);
// TRANS.1: inside one hummed note, room noise drops the sung line, and splits Basic Pitch's notes,
// for up to about 140 ms; a breath between two notes of the same pitch is longer.
export const MELODY_GAP = 0.15;
/** Lazily fetch model and JS dependencies only when transcription is requested.
 * Defaults to PROJECT_MELODY_LIMITS; pass VOCAL_TARGET_LIMITS for pitch-correction targets.
 * Pieces of one sung note that vibrato, drift or room noise split apart are merged back
 * (contour.js mergeFragments), so a hummed note stays one sustained note.
 * `loadModule` is injectable so tests run without the browser bundle.
 */
export async function transcribeWithBasicPitch(audioBuffer, progress = () => {}, { maxSeconds = PROJECT_MELODY_LIMITS.maxSeconds, maxNotes = PROJECT_MELODY_LIMITS.maxNotes, loadModule = loadBasicPitch } = {}) {
  const run = await runBasicPitch(audioBuffer, progress, maxSeconds, loadModule);
  if (!run) return [];
  const contour = pitchContour(run.contours, { duration: audioBuffer.duration });
  const merged = mergeFragments(run.notes({ maxNotes: Infinity }), contour, { gap: MELODY_GAP });
  return Number.isFinite(maxNotes) ? merged.slice(0, maxNotes) : merged;
}

/** Vocal tuning targets for the pitch-contour editor (VOX.3): notes across the whole recording,
 * each with a confidence `c`, plus the continuous sung pitch line from Basic Pitch's contour output.
 * Pieces of one sung note that vibrato split apart are merged back (contour.js mergeFragments).
 */
export async function detectVocalTargets(audioBuffer, progress = () => {}, { loadModule = loadBasicPitch } = {}) {
  const run = await runBasicPitch(audioBuffer, progress, VOCAL_TARGET_LIMITS.maxSeconds, loadModule);
  if (!run) return { notes: [], contour: { t: new Float64Array(0), m: new Float32Array(0) } };
  const contour = pitchContour(run.contours, { duration: audioBuffer.duration });
  return { notes: mergeFragments(run.notes({ maxNotes: VOCAL_TARGET_LIMITS.maxNotes, confidence: true }), contour), contour };
}

const nextTask = () => new Promise(resolve => setTimeout(resolve, 0));

async function runBasicPitch(audioBuffer, progress, maxSeconds, loadModule) {
  if (!audioBuffer || typeof audioBuffer.getChannelData !== "function") {
    throw new TypeError("Expected a decoded AudioBuffer");
  }
  if (audioBuffer.duration > maxSeconds) throw new Error(`For browser transcription, use a recording under ${maxSeconds} seconds.`);
  const { BasicPitch, outputToNotesPoly, noteFramesToTime, addPitchBendsToNoteEvents } = await loadModule();
  const model = new BasicPitch(BASIC_PITCH_MODEL);
  // REC.1: the model runs one window of audio at a time on the page's thread, and those steps follow each
  // other without ever handing the thread back, so the page drew nothing until the end and the progress
  // sat at 0%. Waiting one task before each window lets the page draw the progress (and stay responsive).
  // (Basic Pitch 1.0.1's evaluateModel calls this.evaluateSingleFrame per window; the vendored copy is pinned.)
  if (typeof model.evaluateSingleFrame === "function") {
    const step = model.evaluateSingleFrame.bind(model);
    model.evaluateSingleFrame = async (...args) => { await nextTask(); return step(...args); };
  }
  const frames=[], onsets=[], contours=[];
  const preparedBuffer = await resampleForBasicPitch(audioBuffer);
  await model.evaluateModel(preparedBuffer,
    (f,o,c)=>{frames.push(...f);onsets.push(...o);contours.push(...c)},
    p=>progress(Math.round(Math.max(0, Math.min(1, p))*100))
  );
  if (!frames.length) return null;
  const raw = outputToNotesPoly(frames,onsets,.25,.25,5);
  const timed = noteFramesToTime(addPitchBendsToNoteEvents(contours,raw));
  return {
    contours,
    notes: opts => normalizeBasicPitchNotes(timed, { maxSeconds: Math.min(maxSeconds, audioBuffer.duration), ...opts }),
  };
}
