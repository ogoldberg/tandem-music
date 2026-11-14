// EVO.1: evolution playback. The song plays once, from zero, and turns section by section from the raw
// take into the produced song, so a person hears what Tandem did. Kept pure so Node can test it.
//
// The song is cut into equal sections, one per stage the song has, in the order below. A take stage
// (the recording as sung, separated, cleaned up, tuned) holds the lead until the next stage arrives,
// then crossfades into it: the two gains sum to one across the crossfade. A part stage (the melody on
// its instrument, the harmony, the drums, the band...) fades in at its section and stays to the end, so
// the last section is the finished song: the mix Export WAV writes.

export const STAGES = [
  { key: "original", kind: "take", label: "Your take, as recorded" },
  { key: "vocal", kind: "take", label: "Your voice, separated from the music" },
  { key: "polished", kind: "take", label: "Cleaned up" },
  { key: "tuned", kind: "take", label: "In tune" },
  { key: "melody", kind: "part", label: "The melody on an instrument" },
  { key: "harmony", kind: "part", label: "Chords" },
  { key: "voice2", kind: "part", label: "Harmony voice" },
  { key: "voice2_sung", kind: "part", label: "Harmony sung in your voice" },
  { key: "drums", kind: "part", label: "Drums" },
  { key: "band", kind: "part", label: "Band" },
  { key: "timbre", kind: "part", label: "Your voice as an instrument" },
];

// The longest crossfade; a short section gets at most half its length.
export const FADE = 1;

// A drum hit counts as sounding this long.
const DRUM_SECONDS = 0.25;

// How long the song plays: the end of the last note, drum hit, take or generated part (the band, the
// voice as instrument, the sung harmony unless muted). The rendered audio runs on a little after it so
// the last notes ring; the sections cover the song, not that tail.
export function contentSeconds(project, takeSeconds = 0) {
  const notes = [...(project.notes || []), ...(project.harmony || []), ...(Array.isArray(project.voice2) ? project.voice2 : [])];
  const ends = notes.map(n => n.t + n.d)
    .concat((project.drums || []).map(h => h.t + DRUM_SECONDS))
    .concat(["band", "timbre", "voice2_sung"].flatMap(k => project[k] && !project[k].muted && Number.isFinite(project[k].seconds) ? [project[k].seconds] : []));
  return Math.max(0, takeSeconds || 0, ...ends);
}

// The stages the song has (`available`: the keys with audio), each with an equal section of a song
// `seconds` long; the last section runs on to `length` (the rendered audio's end) when that is later.
// Keys not in STAGES are ignored. No stages, or no length, is an empty plan.
export function evolutionPlan(available, seconds, { fade = FADE, length = seconds } = {}) {
  const have = new Set(available);
  const kept = STAGES.filter(s => have.has(s.key));
  if (!kept.length || !(seconds > 0)) return { stages: [], seconds: 0, fade: 0 };
  const len = seconds / kept.length, end = Math.max(seconds, length || 0);
  const stages = kept.map((s, i) => ({ ...s, start: i * len, end: i === kept.length - 1 ? end : (i + 1) * len }));
  return { stages, seconds: end, fade: Math.min(Math.max(0, fade), len / 2) };
}

const ramp = (t, start, fade) => (fade > 0 ? Math.min(1, Math.max(0, (t - start) / fade)) : t >= start ? 1 : 0);

// The gain of a stage's audio at song time t: 0 before its section (the first stage plays from zero),
// rising over the crossfade at its start; a take falls again over the crossfade at the next stage's start.
export function stageGain(plan, key, t) {
  const i = plan.stages.findIndex(s => s.key === key);
  if (i < 0) return 0;
  const s = plan.stages[i];
  const rise = i === 0 ? 1 : ramp(t, s.start, plan.fade);
  const next = plan.stages[i + 1];
  if (s.kind !== "take" || !next) return rise;
  return Math.min(rise, 1 - ramp(t, next.start, plan.fade));
}

// The stage whose section holds song time t (the caption at the playhead); null outside the song.
export function stageAt(plan, t) {
  if (!(t >= 0) || !plan.stages.length || t > plan.seconds) return null;
  for (let i = plan.stages.length - 1; i >= 0; i--) if (t >= plan.stages[i].start) return plan.stages[i];
  return null;
}

// The evolution's samples: each stage's stem (`stems[key]`, mono at `rate`, from zero) times its gain,
// summed, `frames` long. A stem shorter than the song is silent after its end.
export function mixEvolution(plan, stems, frames, rate) {
  const out = new Float32Array(frames);
  for (const s of plan.stages) {
    const x = stems[s.key];
    if (!x) continue;
    const n = Math.min(frames, x.length);
    for (let i = 0; i < n; i++) {
      const g = stageGain(plan, s.key, i / rate);
      if (g) out[i] += x[i] * g;
    }
  }
  return out;
}
