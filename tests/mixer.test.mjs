import test from "node:test";
import assert from "node:assert/strict";
import { MIX_PARTS, OWN_MUTE, LEVEL_MIN, LEVEL_MAX, cleanMix, channel, dbToGain, mixGains, setChannel, levelText, scaled } from "../mixer.js";

const close = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);

test("a project with no mix plays every part at full level, the voice left out", () => {
  const g = mixGains({});
  for (const p of MIX_PARTS) assert.equal(g[p], p === "voice" ? 0 : 1, p);
});

test("level in dB becomes a gain factor", () => {
  close(dbToGain(0), 1);
  close(dbToGain(-6), 0.501187233627, 1e-9);
  close(dbToGain(6), 1.995262314969, 1e-9);
  close(dbToGain(-20), 0.1);
  const g = mixGains({ mix: { melody: { level: -6 }, drums: { level: 3 } } });
  close(g.melody, dbToGain(-6));
  close(g.drums, dbToGain(3));
  close(g.harmony, 1);
});

test("mute silences a part; an unmuted voice is heard at its level", () => {
  const g = mixGains({ mix: { harmony: { mute: true }, voice: { mute: false, level: -3 } } });
  assert.equal(g.harmony, 0);
  close(g.voice, dbToGain(-3));
  assert.equal(g.melody, 1);
});

test("the band, instrument and sung harmony mute through their own field", () => {
  const project = { band: { muted: true }, timbre: { muted: false }, voice2_sung: { muted: true }, mix: { band: { level: -2 } } };
  const g = mixGains(project);
  assert.equal(g.band, 0);
  assert.equal(g.timbre, 1);
  assert.equal(g.voice2_sung, 0);
  assert.equal(channel(project, "band").level, -2);
  assert.deepEqual(OWN_MUTE, ["band", "timbre", "voice2_sung"]);
  assert.throws(() => cleanMix({ band: { mute: true } }), /Invalid mix/);
  assert.throws(() => setChannel({}, "timbre", { mute: true }), /own mute/);
});

test("a solo silences every other part, keeps levels, and several solos add up", () => {
  let g = mixGains({ mix: { drums: { solo: true, level: -4 } } });
  close(g.drums, dbToGain(-4));
  for (const p of MIX_PARTS) if (p !== "drums") assert.equal(g[p], 0, p);
  g = mixGains({ mix: { drums: { solo: true }, melody: { solo: true } } });
  assert.equal(g.drums, 1);
  assert.equal(g.melody, 1);
  assert.equal(g.harmony, 0);
});

test("a muted part stays silent when soloed, and its solo does not silence the rest", () => {
  const g = mixGains({ mix: { melody: { solo: true, mute: true } } });
  assert.equal(g.melody, 0);
  assert.equal(g.drums, 1);
  // The voice is muted by default, so a solo on it alone is no solo.
  const v = mixGains({ mix: { voice: { solo: true } } });
  assert.equal(v.voice, 0);
  assert.equal(v.melody, 1);
});

test("a solo on a part that is not there does not silence the song", () => {
  const project = { mix: { band: { solo: true } } };
  assert.equal(mixGains(project, ["melody", "drums"]).melody, 1);
  assert.equal(mixGains(project, ["melody", "drums", "band"]).melody, 0);
});

test("cleanMix keeps only what differs from the defaults and rounds to half a dB", () => {
  assert.deepEqual(cleanMix(undefined), {});
  assert.deepEqual(cleanMix(null), {});
  assert.deepEqual(cleanMix({ melody: { level: 0, mute: false, solo: false }, voice: { mute: true } }), {});
  assert.deepEqual(cleanMix({ melody: { level: -6.2 }, voice: { mute: false }, drums: { solo: true } }),
    { melody: { level: -6 }, voice: { mute: false }, drums: { solo: true } });
  assert.deepEqual(cleanMix({ melody: { level: LEVEL_MIN }, harmony: { level: LEVEL_MAX } }),
    { melody: { level: LEVEL_MIN }, harmony: { level: LEVEL_MAX } });
});

test("cleanMix refuses anything it does not know", () => {
  for (const bad of [[], "loud", { piano: { level: 0 } }, { melody: [] }, { melody: { level: "3" } }, { melody: { level: LEVEL_MAX + 1 } },
    { melody: { level: LEVEL_MIN - 1 } }, { melody: { level: NaN } }, { melody: { mute: "yes" } }, { melody: { solo: 1 } }, { melody: { pan: 0 } }]) {
    assert.throws(() => cleanMix(bad), /Invalid mix/, JSON.stringify(bad));
  }
});

test("setChannel changes one part and drops it when back at the defaults", () => {
  let mix = setChannel({}, "melody", { level: -6 });
  assert.deepEqual(mix, { melody: { level: -6 } });
  mix = setChannel(mix, "melody", { solo: true });
  assert.deepEqual(mix, { melody: { level: -6, solo: true } });
  mix = setChannel(mix, "voice", { mute: false });
  assert.deepEqual(mix, { melody: { level: -6, solo: true }, voice: { mute: false } });
  mix = setChannel(mix, "melody", { level: 0, solo: false });
  assert.deepEqual(mix, { voice: { mute: false } });
  assert.throws(() => setChannel({}, "kazoo", { level: 1 }), /Unknown mix part/);
});

test("levelText and scaled", () => {
  assert.equal(levelText(0), "0 dB");
  assert.equal(levelText(-6), "−6 dB");
  assert.equal(levelText(3.5), "+3.5 dB");
  assert.deepEqual([...scaled(Float32Array.from([1, -0.5, 0.25]), 0.5)], [0.5, -0.25, 0.125]);
});
