"""AMT.0: the spike's event conversion and its accompaniment measures (tools/amt-spike/spike.py).

These check the measurement, not the model: the model runs only through the spike's own commands.
"""
import importlib.util
import json
import pathlib
import shutil

import pytest


SPIKE = pathlib.Path(__file__).resolve().parents[1] / "tools" / "amt-spike" / "spike.py"
spec = importlib.util.spec_from_file_location("amt_spike", SPIKE)
spike = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spike)
F_MAJOR = {"tonic": 5, "mode": "major"}


def test_notes_become_the_models_events_and_come_back_unchanged():
    notes = [{"m": 65, "t": 0.013, "d": 0.594}, {"m": 60, "t": 1.0, "d": 12.0}]
    events = spike.to_events(notes, spike.FLUTE)
    # 10 ms steps, 0.1 s later (the library drops controls in the first 50 ms), durations capped at 10 s.
    assert events == [(11, 59, 73 * 128 + 65), (110, 999, 73 * 128 + 60)]
    back = spike.from_events(events)
    assert [(n["instrument"], n["m"], n["t"]) for n in back] == [(73, 65, 0.01), (73, 60, 1.0)]
    assert back[1]["d"] == 9.99


def test_the_melody_loops_to_the_length_and_the_control_is_a_tritone_up():
    base, key = spike.fixture()
    assert key == F_MAJOR and len(base["notes"]) == 14
    melody = spike.looped(base["notes"], 30)
    assert len(melody) == 42 and max(n["t"] for n in melody) < 30
    assert melody[14]["t"] == pytest.approx(base["notes"][0]["t"] + 10)
    tritone = spike.looped(base["notes"], 30, 6)
    assert [n["m"] - 6 for n in tritone] == [n["m"] for n in melody]


def test_the_scores_count_key_consonance_and_shared_triads_over_the_melody():
    melody = [{"m": 65, "t": 0.0, "d": 1.0}]  # F
    notes = [
        {"instrument": 0, "m": 57, "t": 0.0, "d": 1.0},   # A: in key, a third below, both in F major's I (F A C)
        {"instrument": 0, "m": 71, "t": 0.5, "d": 0.5},   # B: not in F major, a tritone above
        {"instrument": 0, "m": 62, "t": 0.5, "d": 0.5},   # D: in key, a sixth below, both in vi (D F A)
        {"instrument": 0, "m": 67, "t": 2.0, "d": 0.5},   # G: in key, but no melody note sounds then
        {"instrument": spike.DRUMS, "m": 38, "t": 0.0, "d": 0.01},  # a snare: not a pitched note
    ]
    s = spike.scores(notes, melody, F_MAJOR)
    assert s == {"notes": 4, "in_key": 0.75, "over_melody": 3, "consonant": 0.667, "shares_triad": 0.667}


def test_a_second_and_a_fourth_do_not_count_as_consonant_but_can_share_a_triad():
    melody = [{"m": 67, "t": 0.0, "d": 1.0}]  # G
    second = [{"instrument": 0, "m": 69, "t": 0.0, "d": 1.0}]  # A: a second, not one triad of F major with G
    fourth = [{"instrument": 0, "m": 60, "t": 0.0, "d": 1.0}]  # C: a fourth below G, both in C E G (V)
    assert spike.scores(second, melody, F_MAJOR)["consonant"] == 0.0
    assert spike.scores(second, melody, F_MAJOR)["shares_triad"] == 0.0
    assert spike.scores(fourth, melody, F_MAJOR)["consonant"] == 0.0
    assert spike.scores(fourth, melody, F_MAJOR)["shares_triad"] == 1.0


def test_the_latest_melody_note_to_start_is_the_one_sounding():
    melody = [{"m": 60, "t": 0.0, "d": 2.0}, {"m": 64, "t": 1.0, "d": 0.5}]
    assert spike.sounding(melody, 0.5)["m"] == 60
    assert spike.sounding(melody, 1.2)["m"] == 64
    assert spike.sounding(melody, 1.6)["m"] == 60
    assert spike.sounding(melody, 2.0) is None


def test_the_project_to_listen_to_keeps_the_melody_and_maps_the_drums():
    base, _ = spike.fixture()
    melody = spike.looped(base["notes"], 10)
    accompaniment = [{"instrument": 0, "m": 53, "t": 0.0, "d": 1.0}, {"instrument": 33, "m": 41, "t": -0.01, "d": 0.5},
                     {"instrument": spike.DRUMS, "m": 36, "t": 0.0, "d": 0.01}, {"instrument": spike.DRUMS, "m": 38, "t": 0.5, "d": 0.01},
                     {"instrument": spike.DRUMS, "m": 51, "t": 1.0, "d": 0.01}]
    project = spike.tandem_project(base, melody, accompaniment)
    assert project["notes"] == melody and project["melody_locked"] is True
    assert [n["m"] for n in project["harmony"]] == [53, 41] and project["harmony"][1]["t"] == 0.0
    assert [d["k"] for d in project["drums"]] == ["kick", "snare", "hat"]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node for harmony.js")
def test_harmony_js_scores_full_marks_on_its_own_melody_and_low_on_the_other():
    base, key = spike.fixture()
    melody = spike.looped(base["notes"], 30)
    chords = [dict(n, instrument=0) for n in spike.harmony_js(dict(base, notes=melody), "chords")]
    own = spike.scores(chords, melody, key)
    other = spike.scores(chords, spike.looped(base["notes"], 30, 6), {"tonic": 11, "mode": "major"})
    assert own["in_key"] == own["shares_triad"] == 1.0
    # HARM.4: the chords now also sit under the melody's fifth (a root a fifth below the melody), which
    # this mod-12 measure counts as a fourth; 2 of the 18 notes over the melody do that.
    assert own["consonant"] >= 0.85
    assert other["in_key"] < 0.2 and other["consonant"] < 0.2 and other["shares_triad"] == 0.0


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node for harmony.js")
def test_the_prompt_is_harmony_js_chords_and_bass_for_the_first_bar():
    base, _ = spike.fixture()
    melody = spike.looped(base["notes"], 30)
    prompt = spike.prompt_notes(base, melody, 2.5)
    assert {n["instrument"] for n in prompt} == {0, 33}
    assert all(n["t"] < 2.5 for n in prompt) and len(prompt) == 3 + 2
    json.dumps(prompt)
