// Tandem on-device vocal polish: band-pass EQ, soft noise gate, compression and
// bounded makeup gain. A port of the DSP /api/polish used to run on the server
// (reference: tests/fixtures/make_polish_fixture.py). Running it in the browser
// means recordings never leave the device and there is no length cap beyond the
// device's own memory. It changes tone and dynamics, never pitch.
// Pure functions only, so Node tests can import this module directly.

export const POLISH_STYLES = ["studio", "natural"];

const PRESETS = {
  natural: { highpass: 95, lowpass: 9000, gateFloor: 0.16, gateOffset: 0.002, threshold: 0.08, ratio: 2.0, target: 0.075 },
  studio: { highpass: 120, lowpass: 6800, gateFloor: 0.07, gateOffset: 0.004, threshold: 0.042, ratio: 3.5, target: 0.12 },
};

// Minimal complex arithmetic for the filter design: [re, im] pairs.
const cadd = (a, b) => [a[0] + b[0], a[1] + b[1]];
const csub = (a, b) => [a[0] - b[0], a[1] - b[1]];
const cmul = (a, b) => [a[0] * b[0] - a[1] * b[1], a[0] * b[1] + a[1] * b[0]];
const cdiv = (a, b) => { const d = b[0] * b[0] + b[1] * b[1]; return [(a[0] * b[0] + a[1] * b[1]) / d, (a[1] * b[0] - a[0] * b[1]) / d]; };
const cscale = (a, s) => [a[0] * s, a[1] * s];
const csqrt = a => {
  const r = Math.hypot(a[0], a[1]);
  const re = Math.sqrt((r + a[0]) / 2), im = Math.sqrt(Math.max(0, (r - a[0]) / 2));
  return [re, a[1] < 0 ? -im : im];
};

/** Digital Butterworth band-pass as second-order sections [b0,b1,b2,a0,a1,a2],
 * designed the way scipy.signal.butter(order, [low, high], "bandpass", fs, output="sos")
 * does: analog prototype -> band-pass transform -> pre-warped bilinear transform.
 */
export function butterBandpassSOS(order, low, high, sampleRate) {
  if (!(low > 0 && high > low && high < sampleRate / 2)) throw new RangeError("Band edges must satisfy 0 < low < high < Nyquist");
  // Pre-warp the edges (scipy normalises to fs = 2 internally).
  const fs = 2, w1 = 2 * fs * Math.tan(Math.PI * low / sampleRate), w2 = 2 * fs * Math.tan(Math.PI * high / sampleRate);
  const bw = w2 - w1, wo = Math.sqrt(w1 * w2);
  // Analog Butterworth prototype poles, unity gain, no zeros.
  const proto = [];
  for (let m = -order + 1; m < order; m += 2) {
    const theta = Math.PI * m / (2 * order);
    proto.push([-Math.cos(theta), -Math.sin(theta)]);
  }
  // Low-pass -> band-pass: each pole splits in two; `order` zeros land at s = 0.
  const analogPoles = [];
  for (const p of proto) {
    const pl = cscale(p, bw / 2), root = csqrt(csub(cmul(pl, pl), [wo * wo, 0]));
    analogPoles.push(cadd(pl, root), csub(pl, root));
  }
  // Bilinear transform: zeros at s=0 -> z=+1, the `order` zeros at infinity -> z=-1.
  const fs2 = 2 * fs;
  let gain = Math.pow(bw, order);
  let num = [1, 0], den = [1, 0];
  for (let i = 0; i < order; i++) num = cmul(num, [fs2, 0]);
  const poles = analogPoles.map(p => { den = cmul(den, csub([fs2, 0], p)); return cdiv(cadd([fs2, 0], p), csub([fs2, 0], p)); });
  gain *= cdiv(num, den)[0];
  // Group poles into sections: complex-conjugate pairs, then real poles two at a time.
  const eps = 1e-12, complexPoles = poles.filter(p => p[1] > eps), realPoles = poles.filter(p => Math.abs(p[1]) <= eps).map(p => p[0]);
  const sections = complexPoles.map(p => [1, -2 * p[0], p[0] * p[0] + p[1] * p[1]]);
  realPoles.sort((a, b) => a - b);
  for (let i = 0; i < realPoles.length; i += 2) sections.push([1, -(realPoles[i] + realPoles[i + 1]), realPoles[i] * realPoles[i + 1]]);
  if (sections.length !== order) throw new Error("Unexpected Butterworth pole layout");
  // Each section carries one zero at +1 and one at -1: b = [1, 0, -1].
  return sections.map((a, i) => (i === 0 ? [gain, 0, -gain, ...a] : [1, 0, -1, ...a]));
}

/** Apply second-order sections in direct form II transposed, like scipy.signal.sosfilt. */
export function sosFilter(sos, input) {
  let x = Float64Array.from(input);
  for (const [b0, b1, b2, a0, a1, a2] of sos) {
    const y = new Float64Array(x.length);
    const nb0 = b0 / a0, nb1 = b1 / a0, nb2 = b2 / a0, na1 = a1 / a0, na2 = a2 / a0;
    let z1 = 0, z2 = 0;
    for (let i = 0; i < x.length; i++) {
      const xi = x[i], yi = nb0 * xi + z1;
      z1 = nb1 * xi - na1 * yi + z2;
      z2 = nb2 * xi - na2 * yi;
      y[i] = yi;
    }
    x = y;
  }
  return x;
}

/** RMS envelope: sqrt of a centred moving average of x^2 over `win` samples,
 * matching np.convolve(x*x, ones(win)/win, mode="same").
 */
function rmsEnvelope(x, win) {
  const n = x.length, env = new Float64Array(n), lead = Math.floor((win - 1) / 2);
  // Window for output i covers x[i + lead - win + 1 .. i + lead].
  let sum = 0;
  for (let j = 0; j <= Math.min(lead, n - 1); j++) sum += x[j] * x[j];
  for (let i = 0; i < n; i++) {
    if (i > 0) {
      const add = i + lead, drop = i + lead - win;
      if (add < n) sum += x[add] * x[add];
      if (drop >= 0 && drop < n) sum -= x[drop] * x[drop];
    }
    env[i] = Math.sqrt(Math.max(0, sum / win) + 1e-12);
  }
  return env;
}

/** Polish a mono recording. Returns a new Float32Array of the same length. */
export function polishSamples(samples, sampleRate, style = "studio") {
  if (!(samples instanceof Float32Array || samples instanceof Float64Array)) throw new TypeError("Expected mono samples as a Float32Array");
  const preset = PRESETS[style];
  if (!preset) throw new RangeError("Choose vocal style natural or studio");
  if (!(sampleRate >= 8000 && sampleRate <= 384000)) throw new RangeError("Unsupported sample rate " + sampleRate);
  if (!samples.length) throw new RangeError("The recording is empty");

  const lowpass = Math.min(preset.lowpass, sampleRate * 0.43);
  let x = sosFilter(butterBandpassSOS(3, preset.highpass, lowpass, sampleRate), samples);

  // Soft gate: smooth low-level noise rather than cutting word endings abruptly.
  const env = rmsEnvelope(x, Math.max(1, Math.floor(sampleRate * 0.018)));
  for (let i = 0; i < x.length; i++) {
    const g = Math.min(1, Math.max(preset.gateFloor, (env[i] - preset.gateOffset) / 0.014));
    x[i] *= g;
  }

  // Compression above threshold.
  const env2 = rmsEnvelope(x, Math.max(1, Math.floor(sampleRate * 0.035)));
  const exponent = 1 - 1 / preset.ratio;
  for (let i = 0; i < x.length; i++) {
    if (env2[i] > preset.threshold) x[i] *= Math.pow(preset.threshold / Math.max(env2[i], 1e-6), exponent);
  }

  // Makeup gain bounded to 4x, with tanh soft clipping.
  let energy = 0;
  for (let i = 0; i < x.length; i++) energy += x[i] * x[i];
  const rms = Math.sqrt(energy / x.length + 1e-12);
  const gain = Math.min(4, preset.target / Math.max(0.009, rms));
  const out = new Float32Array(x.length);
  for (let i = 0; i < x.length; i++) out[i] = Math.tanh(x[i] * gain * 1.15) / 1.15;
  return out;
}
