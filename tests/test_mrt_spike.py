"""MRT.0: the spike's piano roll and its note-following measure (tools/mrt-spike/spike.py).

These check the measurement, not the model: the model runs only through the spike's own commands.
"""
import importlib.util
import pathlib

import numpy as np


SPIKE = pathlib.Path(__file__).resolve().parents[1] / "tools" / "mrt-spike" / "spike.py"
spec = importlib.util.spec_from_file_location("mrt_spike", SPIKE)
spike = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spike)


def test_a_note_is_an_onset_then_held_frames_and_repeats_every_period():
    roll = spike.piano_roll([{"m": 60, "t": 0.0, "d": 0.2}], 20.0)
    assert roll.shape == (500, 128)
    assert roll[0, 60] == 2 and (roll[1:5, 60] == 1).all() and roll[5, 60] == 0
    assert roll[250, 60] == 2  # the loop again at PERIOD (10 s)
    assert roll.sum() == 2 * (2 + 4)


def test_the_tritone_control_moves_every_note_six_semitones():
    notes = spike.fixture_notes()
    a, b = spike.piano_roll(notes, 10.0), spike.piano_roll(notes, 10.0, 6)
    assert (a[:, :-6] == b[:, 6:]).all() and a.sum() == b.sum() > 0


def test_a_note_starting_inside_a_held_one_is_an_onset_whichever_is_listed_first():
    held, struck = {"m": 60, "t": 0.0, "d": 1.0}, {"m": 60, "t": 0.4, "d": 0.2}
    for notes in ([held, struck], [struck, held]):
        roll = spike.piano_roll(notes, 2.0)
        assert roll[0, 60] == 2 and roll[10, 60] == 2 and roll[11, 60] == 1 and roll[24, 60] == 1


def tone(midis, seconds_each):
    rate = spike.RATE
    t = np.arange(int(rate * seconds_each)) / rate
    return np.concatenate([0.3 * np.sin(2 * np.pi * 440 * 2 ** ((m - 69) / 12) * t) for m in midis])


def test_audio_that_plays_the_notes_matches_them_and_not_the_tritone():
    notes = [{"m": m, "t": i * 0.5, "d": 0.5} for i, m in enumerate([65, 69, 72, 67])]
    rolls = [spike.piano_roll(notes, 2.0), spike.piano_roll(notes, 2.0, 6)]
    own, other = spike.scores(tone([65, 69, 72, 67], 0.5), rolls)
    assert own["frame_match_best"] > 0.8 and other["frame_match_best"] < 0.2
    assert own["profile_cosine"] > other["profile_cosine"]


def test_late_audio_is_found_at_its_lag_and_aligned_audio_at_zero():
    ms = [65, 69, 72, 67, 65, 69, 72, 67]
    notes = [{"m": m, "t": i * 0.48, "d": 0.48} for i, m in enumerate(ms)]
    roll = spike.piano_roll(notes, len(ms) * 0.48)
    n = int(len(ms) * 0.48 * spike.RATE)
    (aligned,) = spike.scores(tone(ms, 0.48)[:n], [roll])
    assert aligned["best_lag_ms"] == 0 and aligned["frame_match_lag0"] > 0.9
    late = np.concatenate([np.zeros(int(0.2 * spike.RATE)), tone(ms, 0.48)])[:n]
    (own,) = spike.scores(late, [roll])
    assert own["best_lag_ms"] == 200 and own["frame_match_best"] > 0.9 > own["frame_match_lag0"]
