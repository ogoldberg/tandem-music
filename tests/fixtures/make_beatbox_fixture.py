"""Regenerate beatbox.wav and beatbox.json: what tandem_backend.analyze_drums reads from a synthetic beat,
and what scipy.signal.find_peaks and numpy.percentile give for random signals.

beatbox.js must reproduce these (tests/beatbox.test.mjs), and tests/test_beatbox_fixture.py checks the
server still does, so the device's beat reader (SEC.6) cannot drift from /api/analyze?mode=rhythm.
Run from the repository root: python tests/fixtures/make_beatbox_fixture.py
"""
import io
import json
import sys
import wave
from pathlib import Path

import numpy as np
from scipy import signal

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tandem_backend import analyze_drums, decode_wav  # noqa: E402

HERE = Path(__file__).parent
SR = 22050  # hop 220 samples, so hit times are not whole hundredths


def beat():
    """Two bars of a beatboxed groove at 120 bpm: kick, hat, snare, hat on the eighths, and a quiet floor."""
    rng = np.random.default_rng(7)
    x = rng.normal(0, 0.002, int(SR * 4.2))
    pattern = ["kick", "hat", "snare", "hat", "kick", "kick", "snare", "hat"] * 2
    for i, kind in enumerate(pattern):
        start = int((0.1 + i * 0.25) * SR)
        n = int(0.18 * SR)
        t = np.arange(n) / SR
        if kind == "kick":
            hit = 0.7 * np.sin(2 * np.pi * (90 * t - 60 * t * t)) * np.exp(-t * 25)
        elif kind == "snare":
            noise = signal.sosfilt(signal.butter(4, [900, 2200], "bandpass", fs=SR, output="sos"), rng.normal(0, 1, n))
            hit = (0.5 * noise + 0.2 * np.sin(2 * np.pi * 220 * t)) * np.exp(-t * 30)
        else:
            noise = signal.sosfilt(signal.butter(4, 6000, "highpass", fs=SR, output="sos"), rng.normal(0, 1, n))
            hit = 0.4 * noise * np.exp(-t * 60)
        x[start:start + n] += hit
    return np.clip(x, -1, 1)


def wav(x):
    pcm = np.clip(np.round(x * 32767), -32768, 32767).astype("<i2")
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
    return out.getvalue()


def peak_cases():
    """Random signals with flat tops; a case where two equal peaks compete within the distance is skipped,
    because numpy's argsort breaks that tie in no fixed order."""
    rng = np.random.default_rng(11)
    cases = []
    while len(cases) < 30:
        n = int(rng.integers(20, 400))
        x = np.round(np.abs(np.cumsum(rng.normal(0, 1, n))) + rng.exponential(1, n) * (rng.random(n) < 0.1) * 5, 1)
        height = float(np.round(rng.uniform(0, np.max(x)), 2))
        distance = int(rng.integers(1, 12))
        prominence = float(np.round(rng.uniform(0, 3), 2))
        candidates, _ = signal.find_peaks(x, height=height)
        tied = any(x[a] == x[b] and abs(a - b) < distance for i, a in enumerate(candidates) for b in candidates[i + 1:])
        if tied:
            continue
        peaks, _ = signal.find_peaks(x, height=height, distance=distance, prominence=prominence)
        cases.append({"x": x.tolist(), "height": height, "distance": distance, "prominence": prominence,
                      "peaks": peaks.tolist(), "percentile85": float(np.percentile(x, 85))})
    return cases


def main():
    data = wav(beat())
    (HERE / "beatbox.wav").write_bytes(data)
    x, sr = decode_wav(data)
    fixture = {"sample_rate": sr, "drums": analyze_drums(x, sr), "peak_cases": peak_cases()}
    (HERE / "beatbox.json").write_text(json.dumps(fixture, separators=(",", ":")) + "\n")
    print(len(fixture["drums"]), "hits:", [h["k"] for h in fixture["drums"]])


if __name__ == "__main__":
    main()
