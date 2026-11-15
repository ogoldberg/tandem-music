"""PITCH.0: the spike's ground truth and scoring (tools/pitch-spike/spike.py), and its run of the live guide's tracker.

These check the measurement, not the trackers: RMVPE and PESTO run only through the spike's own commands.
"""
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys

import numpy as np
import pytest

pyworld = pytest.importorskip("pyworld")
REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
import separation_fixture as fx  # noqa: E402
import test_vocal_benchmark as vox  # noqa: E402

SPIKE = REPO / "tools" / "pitch-spike" / "spike.py"
spec = importlib.util.spec_from_file_location("pitch_spike", SPIKE)
spike = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spike)


@pytest.mark.parametrize("case", ["steady", "vibrato", "transitions"])
def test_the_vox_truth_is_the_pitch_render_sings(case):
    rate = 22050
    x, _ = vox.render(case, rate)
    truth, pitch = spike.vox_truth(case, rate)
    # Synthesize from the truth's pitch exactly as render() does: the same samples come out.
    hz = 440.0 * 2 ** ((pitch - 69) / 12)
    phase = 2 * np.pi * np.cumsum(hz) / rate
    voice = sum((0.8 ** k) / k * np.sin(k * phase) for k in range(1, 11))
    voiced = np.isfinite(truth)
    env = np.zeros_like(x)
    sung = np.flatnonzero(voiced)
    env[sung] = 1
    fade = int(0.02 * rate)
    env[sung[:fade]] = np.linspace(0, 1, fade)
    env[sung[-fade:]] = np.linspace(1, 0, fade)
    assert np.array_equal(x, (0.3 * voice / np.max(np.abs(voice)) * env).astype(np.float64))
    # Silent outside the phrase, sung inside it.
    assert np.all(x[~voiced] == 0) and voiced.sum() == int(round(vox.NOTE_SECONDS * len(vox.PHRASE) * rate))


def test_the_sep_truth_is_the_f0_the_fixture_hands_world(monkeypatch):
    handed = {}

    def synthesize(f0, sp, ap, rate, period):
        handed["f0"] = f0.copy()
        return np.ones(int(len(f0) * period / 1000 * rate))
    monkeypatch.setattr(pyworld, "synthesize", synthesize)
    fx.voice()
    f0 = handed["f0"]
    truth = spike.sep_truth()
    assert len(truth) == len(f0)
    assert np.array_equal(np.isfinite(truth), f0 > 0)
    assert np.allclose(truth[f0 > 0], 69 + 12 * np.log2(f0[f0 > 0] / 440))


def line(midi_by_time, hop=0.005, seconds=2.0):
    t = np.arange(int(seconds / hop)) * hop
    return np.array([midi_by_time(v) for v in t])


def test_the_score_counts_cents_octaves_and_voicing():
    # Silent for 0.5 s, then A4 to 1.5 s, then silent.
    truth = line(lambda t: 69.0 if 0.5 <= t < 1.5 else np.nan)
    t = np.arange(0, 2.0, 0.01)
    exact = np.where((t >= 0.5) & (t < 1.5), 69.0, np.nan)
    s = spike.score_track(truth, 0.005, t, exact)
    assert s["median_cents"] == 0 and s["gross"] == 0 and s["voicing_recall"] == 1 and s["false_alarm"] == 0
    # 5 cents sharp throughout; an octave low for a fifth of the note; voiced on part of the silence.
    est = exact + 0.05
    est[(t >= 0.7) & (t < 0.9)] = 57.05
    est[(t >= 0.1) & (t < 0.3)] = 60.0
    s = spike.score_track(truth, 0.005, t, est)
    assert s["median_cents"] == pytest.approx(5, abs=1e-6)
    assert s["octave"] == pytest.approx(s["gross"]) and s["gross"] == pytest.approx(20 / 90, abs=0.01)
    assert s["false_alarm"] == pytest.approx(20 / 90, abs=0.01)  # 45 + 45 silent frames outside the guard
    # Frames within GUARD of a voicing change are not scored, so a late onset is not a miss.
    late = np.where((t >= 0.53) & (t < 1.5), 69.0, np.nan)
    assert spike.score_track(truth, 0.005, t, late)["voicing_recall"] == 1
    missing = np.where((t >= 0.7) & (t < 1.5), 69.0, np.nan)
    assert spike.score_track(truth, 0.005, t, missing)["voicing_recall"] < 0.9


def test_best_lag_finds_a_tracker_that_stamps_its_readings_late():
    truth = line(lambda t: 60 + 0.25 * np.sin(2 * np.pi * 5.5 * t) if 0.2 <= t < 1.8 else np.nan)
    t = np.arange(0, 2.0, 0.01)
    late = 0.015  # each reading is the pitch of 15 ms before its time stamp
    est = np.array([60 + 0.25 * np.sin(2 * np.pi * 5.5 * (v - late)) if 0.2 <= v - late < 1.8 else np.nan for v in t])
    assert spike.best_lag(truth, 0.005, t, est) == pytest.approx(late, abs=0.0026)
    assert spike.score_track(truth, 0.005, t, est, late)["median_cents"] < 0.5


def test_rmvpe_decodes_the_weighted_mean_of_the_bins_around_the_peak():
    r = object.__new__(spike.Rmvpe)
    r.cents = np.pad(20 * np.arange(360) + 1997.3794084376191, (4, 4))
    hidden = np.zeros((3, 360))
    hidden[0, 100] = 0.9                       # one bin: its own cents
    hidden[1, 100], hidden[1, 101] = 0.5, 0.5  # two equal bins: halfway
    hidden[2, 100] = 0.02                      # below the threshold: unvoiced
    midi = r.decode(hidden)
    cents = 20 * 100 + 1997.3794084376191
    assert midi[0] == pytest.approx(spike.hz_to_midi([10 * 2 ** (cents / 1200)])[0])
    assert midi[1] == pytest.approx(spike.hz_to_midi([10 * 2 ** ((cents + 10) / 1200)])[0])
    assert np.isnan(midi[2])


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
def test_the_live_guides_tracker_runs_over_the_clips(tmp_path):
    clips = tmp_path / "clips"
    clips.mkdir()
    x, _ = vox.render("steady", 44100)
    spike.write_wav(clips / "vox-steady-44100.wav", x, 44100)
    subprocess.run(["node", str(REPO / "tools" / "pitch-spike" / "yin_live.mjs"), str(tmp_path)], check=True, capture_output=True)
    rec = json.loads((tmp_path / "tracks" / "yin-live" / "vox-steady-44100.json").read_text())
    truth, _ = spike.vox_truth("steady", 44100)
    s = spike.score_track(truth[::220], 220 / 44100, rec["t"], spike.from_list(rec["midi"]))
    assert s["median_cents"] < 1 and s["voicing_recall"] > 0.95 and s["false_alarm"] == 0
