"""WORDS.0: the spike's reference, alignment and scores (tools/words-spike/spike.py).

These check the measurement, not Whisper: the models run only through the spike's own commands, on the
Children's Song Dataset, which is never in the repository. The CSD files below are written by hand in its layout.
"""
import importlib.util
import json
import pathlib
import types

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SPIKE = REPO / "tools" / "words-spike" / "spike.py"
spec = importlib.util.spec_from_file_location("words_spike", SPIKE)
spike = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spike)


def test_numbers_are_written_as_they_are_sung():
    assert [spike.number_words(n) for n in (0, 7, 13, 20, 21, 40, 99)] == [
        "zero", "seven", "thirteen", "twenty", "twenty one", "forty", "ninety nine"]
    assert spike.number_words(100) == "one hundred"
    assert spike.number_words(115) == "one hundred fifteen"
    assert spike.number_words(999) == "nine hundred ninety nine"


def test_normalize_keeps_words_and_apostrophes_only():
    assert spike.normalize("Twinkle, twinkle LITTLE star!") == ["twinkle", "twinkle", "little", "star"]
    assert spike.normalize("Don’t see 3 blind-mice") == ["don't", "see", "three", "blind", "mice"]
    assert spike.normalize("'Tis 21 bells") == ["tis", "twenty", "one", "bells"]
    assert spike.normalize("1000 ...") == ["1000"]
    assert spike.normalize("  ' -- ") == []


def test_syllable_estimates():
    cases = {"a": 1, "w": 3, "star": 1, "make": 1, "little": 2, "see": 1, "the": 1, "happy": 2,
             "jumped": 1, "wanted": 2, "twinkle": 2, "elephant": 3, "'bye'": 1}
    assert {w: spike.syllable_estimate(w) for w in cases} == cases


def test_a_lines_syllables_split_over_its_words():
    assert spike.split_syllables(["twinkle", "twinkle"], 4) == ([2, 2], True)
    # Estimates 1 + 2 for 4 syllables: one more for some word, and the earliest of the cheapest splits wins.
    assert spike.split_syllables(["star", "little"], 4) == ([2, 2], False)
    assert spike.split_syllables(["little", "star"], 2) == ([1, 1], False)
    assert spike.split_syllables(["a", "b"], 1) == (None, False)
    assert spike.split_syllables([], 3) == (None, False)
    counts, exact = spike.split_syllables(["one", "elephant", "went"], 7)
    assert sum(counts) == 7 and min(counts) >= 1 and not exact


def notes(n):
    return [(float(i), i + 0.5, 60, "x") for i in range(n)]


def test_each_word_starts_on_the_note_of_its_first_syllable():
    lyric = [["Twinkle,", "twinkle"], ["little", "star"]]
    syl = [["twin", "kle", "twin", "kle"], ["lit", "tle", "star"]]
    words = spike.song_reference(lyric, syl, notes(7))
    assert [(w["w"], w["note"], w["exact"]) for w in words] == [
        ("twinkle", 0.0, True), ("twinkle", 2.0, True), ("little", 4.0, True), ("star", 6.0, True)]


def test_a_line_that_does_not_split_exactly_is_not_used_for_timing():
    lyric = [["Twinkle", "twinkle"], ["little", "star"]]
    syl = [["twin", "kle", "twin", "kle"], ["lit", "star"]]
    words = spike.song_reference(lyric, syl, notes(6))
    assert [(w["note"], w["exact"]) for w in words] == [(0.0, True), (2.0, True), (4.0, False), (5.0, False)]


def test_files_with_different_line_counts_are_one_line():
    lyric = [["Twinkle", "twinkle", "little", "star"]]
    syl = [["twin", "kle", "twin", "kle"], ["lit", "tle", "star"]]
    words = spike.song_reference(lyric, syl, notes(7))
    assert [(w["w"], w["note"], w["exact"]) for w in words] == [
        ("twinkle", 0.0, True), ("twinkle", 2.0, True), ("little", 4.0, True), ("star", 6.0, True)]


def test_a_line_with_fewer_syllables_than_words_has_no_note_times():
    words = spike.song_reference([["one", "two", "three"]], [["one", "two"]], notes(2))
    assert [(w["note"], w["exact"]) for w in words] == [(None, False)] * 3


def test_read_csd_reads_the_lyric_syllable_and_note_files(tmp_path):
    base = tmp_path / "english"
    for d in ("csv", "lyric", "txt"):
        (base / d).mkdir(parents=True)
    (base / "csv" / "en001a.csv").write_text("start,end,pitch,syllable\n0.5,0.9,62,twin\n1.0,1.4,62,kle\n")
    (base / "lyric" / "en001a.txt").write_text("Twinkle\n\n")
    (base / "txt" / "en001a.txt").write_text("twin kle\n")
    lyric, syl, ns = spike.read_csd(tmp_path, "en001a")
    assert lyric == [["Twinkle"]] and syl == [["twin", "kle"]]
    assert ns == [(0.5, 0.9, 62, "twin"), (1.0, 1.4, 62, "kle")]


def test_alignment_counts_substitutions_deletions_and_insertions():
    a = spike.align(["a", "b", "c"], ["a", "x", "c", "d"])
    assert (a["ref"], a["sub"], a["del"], a["ins"]) == (3, 1, 0, 1)
    assert a["pairs"] == [(0, 0), (2, 2)]
    d = spike.align(["a", "b", "c", "d"], ["a", "d"])
    assert (d["sub"], d["del"], d["ins"], d["pairs"]) == (0, 2, 0, [(0, 0), (3, 1)])
    assert spike.align([], ["a"]) == {"ref": 0, "sub": 0, "del": 0, "ins": 1, "pairs": []}
    assert spike.align(["a"], []) == {"ref": 1, "sub": 0, "del": 1, "ins": 0, "pairs": []}


def test_percentile_interpolates():
    assert spike.percentile([], 0.5) is None
    assert spike.percentile([3, 1, 2], 0.5) == 2
    assert spike.percentile([1, 2, 3, 4], 0.5) == 2.5
    assert spike.percentile([0, 10], 0.9) == pytest.approx(9)
    assert spike.nearest([0.0, 1.0, 2.0], 1.4) == 1.0 and spike.nearest([], 1.0) is None


def test_whispers_words_are_normalized_and_share_their_times():
    raw = [{"text": " A-B", "start": 1.0, "end": 2.0}, {"text": " 3!", "start": 2.0, "end": 2.5}]
    assert spike.hyp_words(raw) == [
        {"w": "a", "start": 1.0, "end": 2.0}, {"w": "b", "start": 1.0, "end": 2.0},
        {"w": "three", "start": 2.0, "end": 2.5}]


REF = [{"w": "twinkle", "note": 0.0, "exact": True}, {"w": "twinkle", "note": 2.0, "exact": True},
       {"w": "little", "note": 4.0, "exact": False}, {"w": "star", "note": 6.0, "exact": True}]
ONSETS = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]


def hyp(*pairs):
    return [{"w": w, "start": t, "end": t + 0.3} for w, t in pairs]


def test_a_recording_is_scored_on_the_words_heard_right():
    # One wrong word, one word heard right on an inexact line, one right and timed 50 ms late.
    r = spike.score_recording(REF, ONSETS, hyp(("twinkle", -0.02), ("sprinkle", 2.1), ("little", 4.3), ("star", 6.05)))
    assert (r["ref"], r["sub"], r["del"], r["ins"], r["correct"]) == (4, 1, 0, 0, 3)
    assert r["to_note"] == pytest.approx([-0.02, 0.05])
    assert r["to_onset"] == pytest.approx([-0.02, 0.3, 0.05])


def test_the_summary_pools_every_recording():
    a = spike.score_recording(REF, ONSETS, hyp(("twinkle", 0.1), ("twinkle", 2.0), ("little", 4.0), ("star", 6.3)))
    b = spike.score_recording(REF, ONSETS, hyp(("twinkle", 0.0), ("twinkle", 2.0), ("star", 6.0)))
    s = spike.summarize([a, b], audio_seconds=120.0, run_seconds=9.0)
    assert (s["recordings"], s["words"], s["sub"], s["del"], s["ins"]) == (2, 8, 0, 1, 0)
    assert s["wer"] == pytest.approx(1 / 8)
    assert (s["wer_median_recording"], s["wer_worst_recording"]) == (pytest.approx(0.125), 0.25)
    # Timed: 0.1, 0.0, 0.3 from a, 0.0, 0.0, 0.0 from b.
    assert s["timed_words"] == 6
    assert s["to_note_median"] == pytest.approx(0.0) and s["to_note_abs_median"] == pytest.approx(0.0)
    assert s["to_note_abs_p90"] == pytest.approx(0.2)
    assert s["within_100ms"] == pytest.approx(5 / 6) and s["within_250ms"] == pytest.approx(5 / 6)
    # Less the median (0): the same words.
    assert s["shifted_abs_median"] == pytest.approx(0.0) and s["shifted_within_100ms"] == pytest.approx(5 / 6)
    assert (s["audio_minutes"], s["seconds_per_minute"]) == (2.0, 4.5)
    late = spike.summarize([spike.score_recording(REF, ONSETS, hyp(
        ("twinkle", 0.2), ("twinkle", 2.2), ("little", 4.0), ("star", 6.25)))], 60.0, 1.0)
    # 200, 200 and 250 ms late: none within 100 ms, all of them once the 200 ms median is taken away.
    assert late["within_100ms"] == 0 and late["shifted_within_100ms"] == 1
    assert late["shifted_abs_median"] == pytest.approx(0.0)
    empty = spike.summarize([], 0.0, 0.0)
    assert empty["wer"] is None and empty["within_100ms"] is None and empty["seconds_per_minute"] is None
    assert empty["shifted_within_100ms"] is None


def test_score_and_table_from_a_run(tmp_path, capsys):
    refs = {"en001a": {"words": REF, "onsets": ONSETS, "seconds": 60.0}}
    (tmp_path / "refs.json").write_text(json.dumps(refs))
    (tmp_path / "runs").mkdir()
    raw = [{"text": t, "start": s, "end": s + 0.3} for t, s in
           ((" Twinkle,", -0.2), (" twinkle", 2.0), (" little", 4.0), (" star.", 6.1))]
    (tmp_path / "runs" / "mlx-small.en.json").write_text(json.dumps(
        {"runtime": "mlx", "model": "small.en", "recordings": {"en001a": {"raw": raw, "seconds": 3.0}}, "seconds": 3.0}))
    spike.cmd_score(types.SimpleNamespace(out=str(tmp_path)))
    r = json.loads((tmp_path / "results.json").read_text())["mlx-small.en"]
    assert r["wer"] == 0 and r["timed_words"] == 3 and r["per_recording"] == {"en001a": 0}
    out = capsys.readouterr().out
    assert "| mlx-small.en | 1 (0) | 4 | 0.0% | 0 / 0 / 0 | 0.0%, 0.0% | 3.0 |" in out
    assert "| mlx-small.en | 3 | 0 | 100 | 180 | 66.7% | 100.0% | 50 | 100, 66.7% |" in out


FAKE_CLI = """#!/usr/bin/env python3
import json, os, pathlib, sys
a = sys.argv
wav, prefix = pathlib.Path(a[a.index("-f") + 1]), a[a.index("-of") + 1]
if wav.stem in os.environ["FAKE_FAIL"].split(","):
    sys.exit(134)
words = [("Twinkle", 0), ("twinkle", 2000), ("little", 4000), ("star", 6000)]
segs = [{"text": " " + w, "offsets": {"from": t, "to": t + 300}} for w, t in words]
pathlib.Path(prefix + ".json").write_text(json.dumps({"transcription": segs}))
"""


def test_a_recording_whisper_cpp_fails_on_is_kept_as_failed_and_left_out(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("FAKE_FAIL", "en002a")
    cli = tmp_path / "whisper-cli"
    cli.write_text(FAKE_CLI)
    cli.chmod(0o755)
    names = ("en001a", "en002a", "en003a")
    (tmp_path / "refs.json").write_text(json.dumps({n: {"words": REF, "onsets": ONSETS, "seconds": 60.0} for n in names}))
    (tmp_path / "wav16").mkdir()
    for n in names:
        (tmp_path / "wav16" / f"{n}.wav").write_bytes(b"")
    spike.main(["run", "--runtime", "cpp", "--model", "small.en", "--models", str(tmp_path / "models"),
                "--out", str(tmp_path), "--whisper-cli", str(cli)])
    run = json.loads((tmp_path / "runs" / "cpp-small.en.json").read_text())
    assert run["recordings"]["en002a"]["error"] == "exit 134" and "raw" not in run["recordings"]["en002a"]
    assert [len(run["recordings"][n]["raw"]) for n in ("en001a", "en003a")] == [4, 4]
    assert run["seconds"] == pytest.approx(sum(run["recordings"][n]["seconds"] for n in ("en001a", "en003a")))
    assert "2 recordings, 1 failed" in capsys.readouterr().out
    spike.cmd_score(types.SimpleNamespace(out=str(tmp_path)))
    r = json.loads((tmp_path / "results.json").read_text())["cpp-small.en"]
    assert (r["recordings"], r["failed"], r["words"], r["wer"]) == (2, 1, 8, 0)
    assert r["audio_minutes"] == 2.0 and set(r["per_recording"]) == {"en001a", "en003a"}
    assert "| cpp-small.en | 2 (1) | 8 | 0.0% |" in capsys.readouterr().out


def test_a_run_goes_on_when_the_first_recording_fails_in_the_warm_up(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_FAIL", "en001a")
    cli = tmp_path / "whisper-cli"
    cli.write_text(FAKE_CLI)
    cli.chmod(0o755)
    names = ("en001a", "en002a")
    (tmp_path / "refs.json").write_text(json.dumps({n: {"words": REF, "onsets": ONSETS, "seconds": 60.0} for n in names}))
    (tmp_path / "wav16").mkdir()
    for n in names:
        (tmp_path / "wav16" / f"{n}.wav").write_bytes(b"")
    spike.main(["run", "--runtime", "cpp", "--model", "small.en", "--models", str(tmp_path / "models"),
                "--out", str(tmp_path), "--whisper-cli", str(cli)])
    run = json.loads((tmp_path / "runs" / "cpp-small.en.json").read_text())
    assert run["recordings"]["en001a"]["error"] == "exit 134" and len(run["recordings"]["en002a"]["raw"]) == 4
