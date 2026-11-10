// Tandem client-side transcription adapter.
// Spotify Basic Pitch is Apache-2.0 licensed. Its model runs in the browser.
// Both are served by this app (vendor/basic-pitch-1.0.1, built by
// tools/basic-pitch/build.sh, hashes in its SHA256SUMS), not by a CDN.
export const BASIC_PITCH_PACKAGE = "/vendor/basic-pitch-1.0.1/basic-pitch.mjs";
export const BASIC_PITCH_MODEL = "/vendor/basic-pitch-1.0.1/model/model.json";

// Melody transcribed into the project stays within what /api/chat and its prompt accept
// (arrangements under 60 s, at most 128 events per track).
export const PROJECT_MELODY_LIMITS = Object.freeze({ maxSeconds: 60, maxNotes: 128 });
// Vocal note targets feed chunked pitch correction (tuning.js), which handles any length,
// so they cover the whole recording. The per-request cap applies per chunk there.
export const VOCAL_TARGET_LIMITS = Object.freeze({ maxSeconds: Infinity, maxNotes: Infinity });

/** Convert the provider's note events into Tandem's portable note schema.
 * Times are in seconds, pitches in MIDI semitones. Notes are clipped to `maxSeconds`
 * and the earliest `maxNotes` are kept.
 */
export function normalizeBasicPitchNotes(events, { maxSeconds = PROJECT_MELODY_LIMITS.maxSeconds, maxNotes = PROJECT_MELODY_LIMITS.maxNotes } = {}) {
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
    result.push({ m: Math.round(pitch), t: +t.toFixed(3), d: +d.toFixed(3) });
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
/** Lazily fetch model and JS dependencies only when transcription is requested.
 * Defaults to PROJECT_MELODY_LIMITS; pass VOCAL_TARGET_LIMITS for pitch-correction targets.
 * `loadModule` is injectable so tests run without the browser bundle.
 */
export async function transcribeWithBasicPitch(audioBuffer, progress = () => {}, { maxSeconds = PROJECT_MELODY_LIMITS.maxSeconds, maxNotes = PROJECT_MELODY_LIMITS.maxNotes, loadModule = loadBasicPitch } = {}) {
  if (!audioBuffer || typeof audioBuffer.getChannelData !== "function") {
    throw new TypeError("Expected a decoded AudioBuffer");
  }
  if (audioBuffer.duration > maxSeconds) throw new Error(`For browser transcription, use a recording under ${maxSeconds} seconds.`);
  const { BasicPitch, outputToNotesPoly, noteFramesToTime, addPitchBendsToNoteEvents } = await loadModule();
  const model = new BasicPitch(BASIC_PITCH_MODEL);
  const frames=[], onsets=[], contours=[];
  const preparedBuffer = await resampleForBasicPitch(audioBuffer);
  await model.evaluateModel(preparedBuffer,
    (f,o,c)=>{frames.push(...f);onsets.push(...o);contours.push(...c)},
    p=>progress(Math.round(Math.max(0, Math.min(1, p))*100))
  );
  if (!frames.length) return [];
  const raw = outputToNotesPoly(frames,onsets,.25,.25,5);
  const timed = noteFramesToTime(addPitchBendsToNoteEvents(contours,raw));
  return normalizeBasicPitchNotes(timed, { maxSeconds: Math.min(maxSeconds, audioBuffer.duration), maxNotes });
}
