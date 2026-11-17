// SEC.6: the beatbox reader on the device, a line-for-line port of tandem_backend.py analyze_drums, so a beat
// take is read without leaving the device when "This device" is chosen. Onsets are peaks in the rise of a
// 10 ms RMS envelope (scipy.signal.find_peaks with height, distance and prominence, ported below), and each
// hit is named by the spectral centroid of its first 65 ms: kick under 700 Hz, snare under 2300 Hz, else hat.
// tests/fixtures/beatbox.json holds what the server reads from tests/fixtures/beatbox.wav and scipy's peaks for
// random signals; tests/beatbox.test.mjs checks this module gives the same, tests/test_beatbox_fixture.py
// that the server still does.

// The samples the server would decode from the studio's upload: the channels averaged (monoWav), written as
// 16-bit PCM by wavBlob (round(x * 32767)) and read back by decode_wav (/ 32768).
export function uploadSamples(channels) {
  const n = channels.length ? channels[0].length : 0, mono = new Float32Array(n);
  for (const a of channels) for (let i = 0; i < n; i++) mono[i] += a[i] / channels.length;
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) out[i] = Math.round(Math.max(-1, Math.min(1, mono[i])) * 32767) / 32768;
  return out;
}

// numpy.percentile with its default linear method, including numpy's lerp (from the upper end past halfway).
export function percentile(values, q) {
  const a = Float64Array.from(values).sort(), n = a.length;
  if (!n) throw Error("percentile of nothing");
  const pos = (n - 1) * q / 100, lo = Math.floor(pos), hi = Math.min(n - 1, lo + 1), t = pos - lo;
  const diff = a[hi] - a[lo];
  return t >= 0.5 ? a[hi] - diff * (1 - t) : a[lo] + diff * t;
}

// scipy.signal.find_peaks(x, height, distance, prominence) with wlen unset: local maxima (a flat top's middle,
// rounded down), then those at least `height`, then by `distance` (the highest kept first; a tie keeps the
// later one, where numpy's unstable argsort may differ), then those with at least `prominence`.
export function findPeaks(x, { height = -Infinity, distance = 1, prominence = -Infinity } = {}) {
  const n = x.length;
  let peaks = [];
  for (let i = 1; i < n - 1; i++) {
    if (x[i - 1] < x[i]) {
      let ahead = i + 1;
      while (ahead < n - 1 && x[ahead] === x[i]) ahead++;
      if (x[ahead] < x[i]) { peaks.push(Math.floor((i + ahead - 1) / 2)); i = ahead; }
    }
  }
  peaks = peaks.filter(p => x[p] >= height);
  const d = Math.ceil(distance);
  if (d > 1 && peaks.length > 1) {
    const keep = peaks.map(() => true);
    const order = peaks.map((_, j) => j).sort((a, b) => x[peaks[a]] - x[peaks[b]] || a - b);
    for (let i = order.length - 1; i >= 0; i--) {
      const j = order[i];
      if (!keep[j]) continue;
      for (let k = j - 1; k >= 0 && peaks[j] - peaks[k] < d; k--) keep[k] = false;
      for (let k = j + 1; k < peaks.length && peaks[k] - peaks[j] < d; k++) keep[k] = false;
    }
    peaks = peaks.filter((_, j) => keep[j]);
  }
  return peaks.filter(p => prominenceAt(x, p) >= prominence);
}

// scipy's peak prominence over the whole signal: the peak's height above the higher of the lowest points
// on each side before the signal rises above the peak.
export function prominenceAt(x, peak) {
  const top = x[peak];
  let left = top, right = top;
  for (let i = peak; i >= 0 && x[i] <= top; i--) if (x[i] < left) left = x[i];
  for (let i = peak; i < x.length && x[i] <= top; i++) if (x[i] < right) right = x[i];
  return top - Math.max(left, right);
}

// The magnitudes of numpy.fft.rfft(x) for any length, by Bluestein's algorithm over a power-of-two FFT.
const chirps = new Map();
function chirp(n) {
  if (chirps.has(n)) return chirps.get(n);
  let m = 1;
  while (m < 2 * n - 1) m *= 2;
  const wr = new Float64Array(n), wi = new Float64Array(n);
  for (let k = 0; k < n; k++) {
    const a = Math.PI * ((k * k) % (2 * n)) / n;
    wr[k] = Math.cos(a); wi[k] = -Math.sin(a);
  }
  const br = new Float64Array(m), bi = new Float64Array(m);
  br[0] = wr[0]; bi[0] = -wi[0];
  for (let k = 1; k < n; k++) { br[k] = br[m - k] = wr[k]; bi[k] = bi[m - k] = -wi[k]; }
  fft(br, bi, false);
  const c = { m, wr, wi, br, bi };
  chirps.set(n, c);
  return c;
}
function fft(re, im, inverse) {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) { [re[i], re[j]] = [re[j], re[i]]; [im[i], im[j]] = [im[j], im[i]]; }
  }
  for (let len = 2; len <= n; len *= 2) {
    const a = (inverse ? 2 : -2) * Math.PI / len, cr = Math.cos(a), ci = Math.sin(a);
    for (let s = 0; s < n; s += len) {
      let ur = 1, ui = 0;
      for (let k = 0; k < len / 2; k++) {
        const p = s + k, q = p + len / 2;
        const tr = re[q] * ur - im[q] * ui, ti = re[q] * ui + im[q] * ur;
        re[q] = re[p] - tr; im[q] = im[p] - ti; re[p] += tr; im[p] += ti;
        const nr = ur * cr - ui * ci; ui = ur * ci + ui * cr; ur = nr;
      }
    }
  }
  if (inverse) for (let i = 0; i < n; i++) { re[i] /= n; im[i] /= n; }
}
export function rfftMagnitudes(x) {
  const n = x.length, { m, wr, wi, br, bi } = chirp(n);
  const ar = new Float64Array(m), ai = new Float64Array(m);
  for (let k = 0; k < n; k++) { ar[k] = x[k] * wr[k]; ai[k] = x[k] * wi[k]; }
  fft(ar, ai, false);
  for (let k = 0; k < m; k++) {
    const r = ar[k] * br[k] - ai[k] * bi[k];
    ai[k] = ar[k] * bi[k] + ai[k] * br[k]; ar[k] = r;
  }
  fft(ar, ai, true);
  const out = new Float64Array(Math.floor(n / 2) + 1);
  for (let k = 0; k < out.length; k++) {
    const r = ar[k] * wr[k] - ai[k] * wi[k], i = ar[k] * wi[k] + ai[k] * wr[k];
    out[k] = Math.hypot(r, i);
  }
  return out;
}

// The drum hits [{t, k}] in a mono take: analyze_drums(x, sr).
export function readBeats(x, sr) {
  const hop = Math.max(128, Math.floor(sr * .01)), env = [];
  for (let i = 0; i < x.length; i += hop) {
    const end = Math.min(x.length, i + hop);
    let sum = 0;
    for (let j = i; j < end; j++) sum += x[j] * x[j];
    env.push(Math.fround(Math.sqrt(sum / (end - i))));
  }
  if (!env.length) return [];
  const diff = env.map((v, i) => Math.max(0, Math.fround(v - (i ? env[i - 1] : 0))));
  const threshold = Math.max(.016, Math.fround(percentile(diff, 85)) * 2);
  const peaks = findPeaks(diff, { height: threshold, distance: Math.max(1, Math.floor(.12 * sr / hop)), prominence: threshold / 2 });
  const hits = [], size = Math.floor(sr * .065);
  for (const p of peaks.slice(0, 128)) {
    const seg = x.subarray(p * hop, Math.min(x.length, p * hop + size));
    if (seg.length < 64) continue;
    const spectrum = rfftMagnitudes(seg), bin = 1 / (seg.length * (1 / sr));
    let weighted = 0, total = 0;
    for (let k = 0; k < spectrum.length; k++) { weighted += k * bin * spectrum[k]; total += spectrum[k]; }
    const centroid = weighted / (total + 1e-9);
    hits.push({ t: Number((p * hop / sr).toFixed(3)), k: centroid < 700 ? "kick" : centroid < 2300 ? "snare" : "hat" });
  }
  return hits;
}
