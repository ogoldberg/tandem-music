"""SEC.6: tests/fixtures/beatbox.json is what beatbox.js is checked against (tests/beatbox.test.mjs); the
server must still give the same, or the device's beat reader has drifted from /api/analyze?mode=rhythm."""
import json
from pathlib import Path

import numpy as np
from scipy import signal

from tandem_backend import analyze_drums, decode_wav

FIXTURES = Path(__file__).parent / "fixtures"


def test_the_server_still_reads_the_fixture_beat_as_stored():
    stored = json.loads((FIXTURES / "beatbox.json").read_text())
    x, sr = decode_wav((FIXTURES / "beatbox.wav").read_bytes())
    assert sr == stored["sample_rate"]
    assert analyze_drums(x, sr) == stored["drums"]


def test_scipy_still_finds_the_stored_peaks():
    for case in json.loads((FIXTURES / "beatbox.json").read_text())["peak_cases"]:
        x = np.array(case["x"])
        peaks, _ = signal.find_peaks(x, height=case["height"], distance=case["distance"], prominence=case["prominence"])
        assert peaks.tolist() == case["peaks"]
        assert float(np.percentile(x, 85)) == case["percentile85"]
