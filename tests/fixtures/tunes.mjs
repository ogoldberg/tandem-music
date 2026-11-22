// HARM.4: six public-domain tunes hummed low (around C3, where a hummed melody sits), in 4/4 at 100 bpm.
// Each bar is a list of [MIDI pitch or null for a rest, length in beats]. Used by tests/harmony.test.mjs.
const C = 48, D = 50, E = 52, F = 53, G = 55, A = 57, G2 = 43, A2 = 45, B2 = 47;
export const BPM = 100;
export const TUNES = {
  twinkle: { key: { tonic: 0, mode: "major" }, bars: [
    [[C, 1], [C, 1], [G, 1], [G, 1]], [[A, 1], [A, 1], [G, 2]], [[F, 1], [F, 1], [E, 1], [E, 1]], [[D, 1], [D, 1], [C, 2]],
    [[G, 1], [G, 1], [F, 1], [F, 1]], [[E, 1], [E, 1], [D, 2]], [[G, 1], [G, 1], [F, 1], [F, 1]], [[E, 1], [E, 1], [D, 2]],
    [[C, 1], [C, 1], [G, 1], [G, 1]], [[A, 1], [A, 1], [G, 2]], [[F, 1], [F, 1], [E, 1], [E, 1]], [[D, 1], [D, 1], [C, 2]],
  ] },
  ode: { key: { tonic: 0, mode: "major" }, bars: [
    [[E, 1], [E, 1], [F, 1], [G, 1]], [[G, 1], [F, 1], [E, 1], [D, 1]], [[C, 1], [C, 1], [D, 1], [E, 1]], [[E, 1.5], [D, 0.5], [D, 2]],
    [[E, 1], [E, 1], [F, 1], [G, 1]], [[G, 1], [F, 1], [E, 1], [D, 1]], [[C, 1], [C, 1], [D, 1], [E, 1]], [[D, 1.5], [C, 0.5], [C, 2]],
  ] },
  frere: { key: { tonic: 0, mode: "major" }, bars: [
    [[C, 1], [D, 1], [E, 1], [C, 1]], [[C, 1], [D, 1], [E, 1], [C, 1]], [[E, 1], [F, 1], [G, 2]], [[E, 1], [F, 1], [G, 2]],
    [[G, 0.5], [A, 0.5], [G, 0.5], [F, 0.5], [E, 1], [C, 1]], [[G, 0.5], [A, 0.5], [G, 0.5], [F, 0.5], [E, 1], [C, 1]],
    [[C, 1], [G2, 1], [C, 2]], [[C, 1], [G2, 1], [C, 2]],
  ] },
  mary: { key: { tonic: 0, mode: "major" }, bars: [
    [[E, 1], [D, 1], [C, 1], [D, 1]], [[E, 1], [E, 1], [E, 2]], [[D, 1], [D, 1], [D, 2]], [[E, 1], [G, 1], [G, 2]],
    [[E, 1], [D, 1], [C, 1], [D, 1]], [[E, 1], [E, 1], [E, 1], [E, 1]], [[D, 1], [D, 1], [E, 1], [D, 1]], [[C, 4]],
  ] },
  saints: { key: { tonic: 0, mode: "major" }, bars: [
    [[null, 1], [C, 1], [E, 1], [F, 1]], [[G, 4]], [[null, 1], [C, 1], [E, 1], [F, 1]], [[G, 4]],
    [[null, 1], [C, 1], [E, 1], [F, 1]], [[G, 2], [E, 2]], [[C, 2], [E, 2]], [[D, 4]],
    [[null, 1], [E, 1], [E, 1], [D, 1]], [[C, 2], [C, 1], [E, 1]], [[G, 2], [G, 1], [F, 1]], [[F, 2], [E, 1], [F, 1]],
    [[G, 2], [E, 2]], [[C, 2], [D, 2]], [[C, 4]],
  ] },
  godrest: { key: { tonic: 9, mode: "minor" }, bars: [
    [[A2, 1], [A2, 1], [E, 1], [E, 1]], [[D, 1], [C, 1], [B2, 1], [A2, 1]], [[G2, 1], [A2, 1], [B2, 1], [C, 1]], [[D, 1], [E, 3]],
    [[A2, 1], [A2, 1], [E, 1], [E, 1]], [[D, 1], [C, 1], [B2, 1], [A2, 1]], [[G2, 1], [A2, 1], [B2, 1], [C, 1]], [[D, 1], [E, 3]],
    [[E, 1], [D, 1], [C, 1], [B2, 1]], [[A2, 4]],
  ] },
};

// The tune as project notes: each note held for 90% of its length.
export function tuneNotes(name) {
  const beat = 60 / BPM, notes = [];
  TUNES[name].bars.forEach((bar, b) => {
    let at = b * 4;
    for (const [m, len] of bar) {
      if (m !== null) notes.push({ m, t: Math.round(at * beat * 1000) / 1000, d: Math.round(len * beat * 0.9 * 1000) / 1000 });
      at += len;
    }
  });
  return notes;
}
