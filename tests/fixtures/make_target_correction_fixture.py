"""Regenerate target-correction.json: world_tuning._target_notes on a synthetic sung pitch line.

contour.js previewCorrection must reproduce these values (tests/contour.test.mjs), and
tests/test_world_tuning.py checks the server still does, so the editor's preview cannot drift
from what /api/tune does. Run from the repository root: python tests/fixtures/make_target_correction_fixture.py
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from world_tuning import _target_notes  # noqa: E402

FIXTURE = Path(__file__).with_name("target-correction.json")


def sung_line():
    t = np.round(np.arange(300) * 0.01, 2)
    midi = np.full(300, np.nan)
    midi[10:110] = 60.4 + 0.3 * np.sin(2 * np.pi * 5.5 * t[10:110])  # sharp C4 with vibrato
    midi[60] = 72.4                                                  # a stray octave-error frame
    midi[120:200] = 64.8 + 0.2 * np.sin(2 * np.pi * 5 * t[120:200])  # E4 dragged down to D4
    midi[210:290] = 55.0                                             # G3 dragged up to B-flat 4
    return t, np.round(midi, 6)


NOTES = [{"m": 60, "t": 0.1, "d": 1.0}, {"m": 62, "t": 1.2, "d": 0.8}, {"m": 70, "t": 2.1, "d": 0.8}]
SETTINGS = [(1, 0), (1, 1), (0.5, 0.5), (0.85, 1)]


def corrected(t, midi, strength, vibrato):
    f0 = np.where(np.isfinite(midi), 440 * 2 ** ((midi - 69) / 12), 0.0)
    out, _ = _target_notes(f0, t, NOTES, strength, vibrato)
    return [None if v <= 0 else round(float(69 + 12 * np.log2(v / 440)), 6) for v in out]


def build():
    t, midi = sung_line()
    return {"t": t.tolist(), "m": [None if not np.isfinite(v) else float(v) for v in midi], "notes": NOTES,
            "cases": [{"strength": s, "vibrato": v, "corrected": corrected(t, midi, s, v)} for s, v in SETTINGS]}


if __name__ == "__main__":
    FIXTURE.write_text(json.dumps(build()))
