import test from "node:test";
import assert from "node:assert/strict";
import { STAGES, FADE, evolutionPlan, stageGain, stageAt, mixEvolution, contentSeconds } from "../evolution.js";

const keys = plan => plan.stages.map(s => s.key);

test("stages come in the fixed order whatever order they are given in", () => {
  const plan = evolutionPlan(["drums", "tuned", "melody", "original", "band", "polished", "harmony"], 70);
  assert.deepEqual(keys(plan), ["original", "polished", "tuned", "melody", "harmony", "drums", "band"]);
  assert.deepEqual(STAGES.map(s => s.key).filter(k => keys(plan).includes(k)), keys(plan));
});

test("missing stages are skipped and unknown keys ignored", () => {
  assert.deepEqual(keys(evolutionPlan(["melody", "drums", "accompaniment"], 20)), ["melody", "drums"]);
  assert.deepEqual(evolutionPlan([], 20).stages, []);
  assert.deepEqual(evolutionPlan(["melody"], 0).stages, []);
});

test("the sections are equal, in order, and cover the song with no gap", () => {
  const plan = evolutionPlan(["original", "polished", "tuned", "melody", "drums"], 23.5);
  assert.equal(plan.stages[0].start, 0);
  assert.equal(plan.stages.at(-1).end, 23.5);
  for (let i = 1; i < plan.stages.length; i++) assert.equal(plan.stages[i].start, plan.stages[i - 1].end);
  for (const s of plan.stages) assert.ok(Math.abs(s.end - s.start - 23.5 / 5) < 1e-9);
});

test("the crossfade is at most FADE and at most half a section", () => {
  assert.equal(evolutionPlan(["original", "melody"], 60).fade, FADE);
  assert.equal(evolutionPlan(["original", "polished", "tuned", "melody"], 2).fade, 0.25);
});

test("a take's gain and the next stage's gain sum to one across each crossfade", () => {
  const plan = evolutionPlan(["original", "vocal", "polished", "tuned", "melody", "harmony"], 30);
  const takes = plan.stages.filter(s => s.kind === "take");
  assert.equal(takes.length, 4);
  for (const s of takes) {
    const next = plan.stages[plan.stages.indexOf(s) + 1];
    for (let k = 0; k <= 20; k++) {
      const t = next.start + (k / 20) * plan.fade;
      const sum = stageGain(plan, s.key, t) + stageGain(plan, next.key, t);
      assert.ok(Math.abs(sum - 1) < 1e-9, `${s.key} -> ${next.key} at ${t}: ${sum}`);
    }
    assert.equal(stageGain(plan, s.key, next.start + plan.fade), 0);
  }
});

test("each stage is alone at full level in the middle of its own section among the takes", () => {
  const plan = evolutionPlan(["original", "polished", "tuned", "melody"], 40);
  for (const s of plan.stages) {
    const mid = (s.start + s.end) / 2;
    for (const o of plan.stages) assert.equal(stageGain(plan, o.key, mid), o === s ? 1 : 0, `${o.key} in ${s.key}`);
  }
});

test("parts fade in at their section and stay to the end, so the last section is the whole mix", () => {
  const plan = evolutionPlan(["tuned", "melody", "harmony", "drums", "band"], 50);
  const last = plan.stages.at(-1), end = last.end - 0.01;
  for (const s of plan.stages) {
    assert.equal(stageGain(plan, s.key, s.start - 0.01), s.key === "tuned" ? 1 : 0);
    assert.equal(stageGain(plan, s.key, end), s.kind === "part" ? 1 : 0);
  }
  // Half way into the drums' fade-in, the drums are at half level and the earlier parts at full.
  const drums = plan.stages.find(s => s.key === "drums");
  assert.equal(stageGain(plan, "drums", drums.start + plan.fade / 2), 0.5);
  assert.equal(stageGain(plan, "melody", drums.start + plan.fade / 2), 1);
});

test("the first stage plays from zero with no fade-in", () => {
  for (const first of ["original", "melody"]) {
    const plan = evolutionPlan([first, "drums"], 10);
    assert.equal(stageGain(plan, first, 0), 1);
  }
});

test("the stage at a time is the one whose section holds it", () => {
  const plan = evolutionPlan(["original", "tuned", "melody", "drums"], 20);
  assert.equal(stageAt(plan, 0).key, "original");
  assert.equal(stageAt(plan, 4.99).key, "original");
  assert.equal(stageAt(plan, 5).key, "tuned");
  assert.equal(stageAt(plan, 12).key, "melody");
  assert.equal(stageAt(plan, 20).key, "drums");
  assert.equal(stageAt(plan, 20.5), null);
  assert.equal(stageAt(plan, -1), null);
  assert.equal(stageAt(evolutionPlan([], 20), 1), null);
});

test("the mix is each stem times its gain, and a short stem is silent after its end", () => {
  const rate = 100, frames = 1000; // 10 s
  const plan = evolutionPlan(["original", "melody"], frames / rate, { fade: 1 });
  const original = new Float32Array(frames).fill(0.5), melody = new Float32Array(600).fill(0.25);
  const out = mixEvolution(plan, { original, melody, drums: new Float32Array(frames).fill(1) }, frames, rate);
  assert.equal(out.length, frames);
  assert.equal(out[100], 0.5); // 1 s: the take alone
  assert.ok(Math.abs(out[550] - (0.5 * 0.5 + 0.25 * 0.5)) < 1e-6); // half way through the crossfade at 5 s
  assert.equal(out[700], 0); // the melody stem ended at 6 s; the drums are not a stage of this plan
  for (let i = 0; i < frames; i++) {
    const want = original[i] * stageGain(plan, "original", i / rate) + (i < 600 ? melody[i] * stageGain(plan, "melody", i / rate) : 0);
    assert.ok(Math.abs(out[i] - want) < 1e-6);
  }
});

test("the song lasts to the end of its last note, hit, take or unmuted generated part", () => {
  const p = { notes: [{ m: 60, t: 1, d: 0.5 }], harmony: [{ m: 48, t: 2, d: 1 }], voice2: [], drums: [{ k: "kick", t: 3 }] };
  assert.equal(contentSeconds(p), 3.25);
  assert.equal(contentSeconds(p, 6), 6);
  assert.equal(contentSeconds({ ...p, band: { seconds: 9, muted: false } }), 9);
  assert.equal(contentSeconds({ ...p, band: { seconds: 9, muted: true } }), 3.25);
  assert.equal(contentSeconds({ notes: [], drums: [] }), 0);
  // A generated part counts only when its audio is there to play (review of #90).
  const band = { ...p, band: { seconds: 9, muted: false } };
  assert.equal(contentSeconds(band, 0, ["melody", "drums"]), 3.25);
  assert.equal(contentSeconds(band, 0, ["melody", "drums", "band"]), 9);
});

test("the sections cover the song and the last one runs on through the rendered tail", () => {
  const plan = evolutionPlan(["original", "melody", "drums"], 9, { length: 11 });
  assert.deepEqual(plan.stages.map(s => [s.start, s.end]), [[0, 3], [3, 6], [6, 11]]);
  assert.equal(plan.seconds, 11);
  assert.equal(stageAt(plan, 10.5).key, "drums");
  assert.equal(stageGain(plan, "drums", 10.9), 1);
  assert.equal(evolutionPlan(["melody"], 9, { length: 5 }).stages[0].end, 9);
});
