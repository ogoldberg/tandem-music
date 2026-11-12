"""SEP.1 fixture: a known sung melody over an accompaniment, made here from code (no recording).

The voice is synthesized with the WORLD vocoder (pyworld, already a dependency for /api/tune) from
vowel formant envelopes, with vibrato, glides between notes, a breath-like aperiodicity and a short
consonant-like dip at each note start ("la"), so it sounds like a voice rather than a tone. The
accompaniment is plucked chords, a bass line and drums (kick, snare, hi-hats). Used by
tests/test_separation.py and e2e/test_separation.py, with the scoring rule below.
"""
import numpy as np

RATE = 44100
MELODY = [64, 67, 69, 67, 64, 62, 60, 62, 64, 64, 65, 64, 62, 60, 62, 67]
NOTE_SECONDS = 0.5
LEAD_SECONDS = 0.5
VOICE_LEVEL = 0.7  # the voice against the accompaniment: the band is louder, as in a song
VOWELS = {  # formant frequencies and bandwidths (Hz)
    "a": ([800, 1150, 2900, 3900], [80, 90, 120, 130]),
    "e": ([400, 1600, 2700, 3300], [60, 80, 120, 120]),
    "i": ([350, 1700, 2700, 3700], [50, 100, 120, 150]),
    "o": ([450, 800, 2830, 3800], [70, 80, 100, 130]),
    "u": ([325, 700, 2530, 3500], [50, 60, 170, 180]),
}
LYRIC = "aeoiaeouaoieaoua"
CHORDS = [[48, 52, 55, 60], [45, 48, 52, 57], [41, 45, 48, 53], [43, 47, 50, 55]]  # C Am F G


def midi_hz(m):
    return 440 * 2 ** ((m - 69) / 12)


def reference_notes():
    return [{"m": m, "t": LEAD_SECONDS + k * NOTE_SECONDS, "d": NOTE_SECONDS} for k, m in enumerate(MELODY)]


def _envelopes(freqs):
    s = 2j * np.pi * freqs
    out = {}
    for v, (formants, widths) in VOWELS.items():
        h = np.ones_like(freqs, dtype=complex)
        for f, b in zip(formants, widths):
            p = -np.pi * b + 2j * np.pi * f
            h *= (p * np.conj(p)) / ((s - p) * (s - np.conj(p)))
        out[v] = np.abs(h) ** 2 / (1 + (freqs / 150) ** 2) + 1e-12  # glottal roll-off
    return out


def voice(rate=RATE, seed=1):
    import pyworld
    rng = np.random.default_rng(seed)
    period = 5.0  # ms
    n = int((LEAD_SECONDS * 2 + NOTE_SECONDS * len(MELODY)) * 1000 / period)
    rel = np.arange(n) * period / 1000 - LEAD_SECONDS
    fft = pyworld.get_cheaptrick_fft_size(rate)
    freqs = np.arange(fft // 2 + 1) * rate / fft
    env = _envelopes(freqs)
    breath = np.clip(0.02 + (freqs / 6000) ** 2 * 0.6, 0, 0.95)
    f0, sp, ap = np.zeros(n), np.empty((n, len(freqs))), np.empty((n, len(freqs)))
    for i in range(n):
        k = int(np.floor(rel[i] / NOTE_SECONDS))
        if rel[i] < 0 or k >= len(MELODY):
            sp[i], ap[i] = env["a"] * 1e-6, 1.0
            continue
        within = rel[i] - k * NOTE_SECONDS
        m = MELODY[k] + 0.3 * np.sin(2 * np.pi * 5.5 * within) * min(1, within / 0.2)
        if k and within < 0.04:
            m = MELODY[k - 1] + (MELODY[k] - MELODY[k - 1]) * within / 0.04
        f0[i] = midi_hz(m) * (1 + 0.003 * rng.standard_normal())
        cur, prev = env[LYRIC[k % len(LYRIC)]], env[LYRIC[(k - 1) % len(LYRIC)]] if k else env[LYRIC[0]]
        w = min(1, within / 0.06)
        sp[i] = prev ** (1 - w) * cur ** w * (0.25 + 0.75 * min(1, within / 0.05)) ** 2
        ap[i] = np.maximum(breath, 0.6) if within < 0.03 else breath
    y = pyworld.synthesize(f0, sp, ap, rate, period)
    return y / np.max(np.abs(y)) * 0.5


def _pluck(m, seconds, rate, partials=8):
    t = np.arange(int(seconds * rate)) / rate
    f = midi_hz(m)
    x = sum(0.7 ** h * np.sin(2 * np.pi * f * (h + 1) * t + h) * np.exp(-t * (2 + h)) for h in range(partials))
    return x * np.minimum(1, t / 0.005)


def accompaniment(length, rate=RATE, seed=2):
    rng = np.random.default_rng(seed)
    out = np.zeros(length)

    def add(start, x):
        s = int(start * rate)
        e = min(length, s + len(x))
        if e > s:
            out[s:e] += x[:e - s]
    bar = 2.0
    for b in range(int((length / rate - LEAD_SECONDS) // bar) + 1):
        chord = CHORDS[b % len(CHORDS)]
        for beat in range(4):
            at = LEAD_SECONDS + b * bar + beat * 0.5
            for m in chord[1:]:
                add(at, _pluck(m + 12, 0.5, rate) * 0.18)
            add(at, _pluck(chord[0] - 12, 0.5, rate, partials=4) * 0.5)
            t = np.arange(int(0.25 * rate)) / rate
            if beat % 2 == 0:
                add(at, np.sin(2 * np.pi * (50 + 80 * np.exp(-t * 30)) * t) * np.exp(-t * 12) * 0.6)
            else:
                add(at, rng.standard_normal(len(t)) * np.exp(-t * 25) * 0.25)
            for half in (0, 0.25):
                tt = np.arange(int(0.05 * rate)) / rate
                add(at + half, np.diff(rng.standard_normal(len(tt) + 1)) * np.exp(-tt * 80) * 0.08)
    return out


def song(rate=RATE):
    """(mixture, voice alone, accompaniment alone), mono float64 at `rate`, peak 0.9."""
    v = voice(rate)
    a = accompaniment(len(v), rate)
    mix = v * VOICE_LEVEL + a
    scale = 0.9 / np.max(np.abs(mix))
    return mix * scale, v * VOICE_LEVEL * scale, a * scale


def recall(found, reference=None, cover=0.5):
    """The share of the melody's notes found: a note counts when transcribed notes of the same MIDI
    pitch cover at least `cover` of its duration."""
    reference = reference or reference_notes()
    hit = 0
    for r in reference:
        a, b = r["t"], r["t"] + r["d"]
        got = sum(max(0.0, min(b, n["t"] + n["d"]) - max(a, n["t"])) for n in found if n["m"] == r["m"])
        hit += got >= cover * r["d"]
    return hit / len(reference)
