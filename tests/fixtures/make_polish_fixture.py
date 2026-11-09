"""Regenerate tests/fixtures/polish_reference.json from the original server polish DSP.

This is the reference implementation that /api/polish ran before PERF.1 moved polish
into the browser (polish.js). tests/polish.test.mjs checks polish.js against its output.
Run from the repo root: python tests/fixtures/make_polish_fixture.py
"""
import base64, json
from pathlib import Path
import numpy as np
from scipy import signal


def reference_polish(x, sr, style):
    highpass = 95 if style == "natural" else 120
    lowpass = min(9000 if style == "natural" else 6800, sr * .43)
    sos = signal.butter(3, [highpass, lowpass], btype="bandpass", fs=sr, output="sos")
    x = signal.sosfilt(sos, x)
    win = max(1, int(sr * .018))
    env = np.sqrt(signal.convolve(x * x, np.ones(win) / win, mode="same", method="fft") + 1e-12)
    gate_floor = .16 if style == "natural" else .07
    gate = np.clip((env - (.002 if style == "natural" else .004)) / .014, gate_floor, 1)
    x = x * gate
    win = max(1, int(sr * .035))
    env2 = np.sqrt(signal.convolve(x * x, np.ones(win) / win, mode="same", method="fft") + 1e-12)
    threshold = .08 if style == "natural" else .042
    ratio = 2.0 if style == "natural" else 3.5
    compression = np.where(env2 > threshold, (threshold / np.maximum(env2, 1e-6)) ** (1 - 1 / ratio), 1.0)
    x = x * compression
    rms = float(np.sqrt(np.mean(x * x) + 1e-12))
    target = .075 if style == "natural" else .12
    gain = min(4.0, target / max(.009, rms))
    return np.tanh(x * gain * 1.15) / 1.15


def b64(arr):
    return base64.b64encode(np.asarray(arr, dtype="<f4").tobytes()).decode()


def main():
    rng = np.random.default_rng(7)
    cases = []
    for sr in (16000, 44100):
        n = int(sr * .3)
        t = np.arange(n) / sr
        # A loud vowel-like tone, a quiet tail (exercises the gate) and broadband noise.
        x = (.5 * np.sin(2 * np.pi * 220 * t) + .2 * np.sin(2 * np.pi * 3300 * t)) * (t < .2)
        x = x + .003 * rng.standard_normal(n) + 30 * (t > .25) * np.sin(2 * np.pi * 50 * t) * 1e-3
        x = x.astype(np.float32)
        expected = {style: b64(reference_polish(x, sr, style)) for style in ("studio", "natural")}
        cases.append({"sr": sr, "input": b64(x), "expected": expected})
    out = Path(__file__).with_name("polish_reference.json")
    out.write_text(json.dumps({"cases": cases}))
    print("wrote", out, out.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
