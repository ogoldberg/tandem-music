"""AI.5: the chat evaluation harness (tools/chat-eval/chat_eval.py), with the model faked.

A model that answers every case correctly scores 100% everywhere; each kind of wrong answer is caught
by the score it should fail. No provider is called."""
import asyncio
import importlib.util
import json
import pathlib
import shutil
import subprocess

import pytest

import tandem_backend as server

REPO = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("chat_eval", REPO / "tools" / "chat-eval" / "chat_eval.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)

GOOD = {
    "faster": [{"type": "set_tempo", "bpm": 130}],
    "slower": [{"type": "set_tempo", "bpm": 80}],
    "marimba": [{"type": "set_instrument", "instrument": "marimba"}],
    "rock-beat": [{"type": "replace_drums", "drums": [{"k": "kick", "t": 0}, {"k": "snare", "t": 0.6}, {"k": "kick", "t": 1.2}, {"k": "snare", "t": 1.8}]}],
    "eighth-hats": [{"type": "replace_drums", "drums": [{"k": "hat", "t": round(i * 0.3, 2)} for i in range(16)]}],
    "no-drums": [{"type": "remove_track", "track": "rhythm"}],
    "locked-transpose": [],
    "locked-add-note": [],
    "transpose": [{"type": "transpose", "semitones": 2}],
    "delete-last": [{"type": "replace_notes", "notes": ev.MELODY[:-1]}],
    "two-changes": [{"type": "set_tempo", "bpm": 72}, {"type": "set_instrument", "instrument": "strings"}],
    "follow-up": [{"type": "set_tempo", "bpm": 130}],
    "injection": [],
    "add-chords": [{"type": "generate_harmony", "style": "chords"}],
    "bass-line": [{"type": "generate_harmony", "style": "bass"}],
    "jazz": [{"type": "set_genre", "genre": "jazz"}],
    "chords-and-beat": [{"type": "generate_harmony", "style": "chords"}, {"type": "add_beat", "groove": "straight", "bars": 4}],
    "to-g-major": [{"type": "transpose", "semitones": 7}],
}


def case(cid):
    return next(c for c in ev.CASES if c[0] == cid)


def scored(cid, raw):
    c = case(cid)
    req = ev.request(c)
    return ev.score(raw, req, c[4], req.project.model_dump())


def answer(actions):
    return json.dumps({"reply": "Done.", "actions": actions})


def test_every_case_has_a_right_answer_that_scores_full_marks():
    assert {c[0] for c in ev.CASES} == set(GOOD)
    for cid, actions in GOOD.items():
        got = scored(cid, answer(actions))
        assert got["json"] and got["valid"] and got["did"], (cid, got)
        assert got["lock"] in (True, None), (cid, got)


def test_every_case_project_is_one_the_studio_could_send():
    for c in ev.CASES:
        ev.request(c)
    assert set(ev.SONGS) <= {c[0] for c in ev.CASES}


NODE = shutil.which("node")


def node_json(script, arg):
    done = subprocess.run([NODE, "--input-type=module", "-e", script, json.dumps(arg)], cwd=REPO, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_each_case_summary_is_the_one_the_studio_sends():
    script = ("import {songSummary} from './actions.js';"
              "process.stdout.write(JSON.stringify(JSON.parse(process.argv[1]).map(p => songSummary(p))))")
    cases = [c for c in ev.CASES if c[0] in ev.SONGS]
    assert len(cases) == 5
    assert node_json(script, [c[2] for c in cases]) == [ev.SONGS[c[0]] for c in cases]


def test_add_beats_hits_are_the_studios():
    script = ("import {GROOVES, grooveHits} from './beats.js';"
              "process.stdout.write(JSON.stringify(GROOVES.map(g => [g.id, grooveHits(g.id, {bpm: 100, bars: 3, from: 0})])))")
    studio = node_json(script, None)
    assert [g for g, _ in studio] == list(ev.GROOVE_BARS) == list(server.GROOVES)
    for g, hits in studio:
        assert ev.beat_hits(g, 3, 100) == hits, g


def test_genre_instruments_are_the_studios():
    script = ("import {GENRES, genreChanges} from './genre.js';"
              "process.stdout.write(JSON.stringify(GENRES.map(g => [g.id, genreChanges(g.id).instrument])))")
    assert dict(node_json(script, None)) == ev.GENRE_INSTRUMENTS
    assert list(ev.GENRE_INSTRUMENTS) == list(server.GENRES)


@pytest.mark.parametrize("cid,actions", [
    ("faster", [{"type": "set_tempo", "bpm": 110}]),
    ("slower", [{"type": "set_tempo", "bpm": 120}]),
    ("marimba", [{"type": "set_instrument", "instrument": "flute"}]),
    ("rock-beat", [{"type": "add_hit", "drum": "kick", "start": 0}]),
    ("eighth-hats", [{"type": "replace_drums", "drums": [{"k": "hat", "t": round(i * 0.6, 2)} for i in range(8)]}]),
    ("eighth-hats", [{"type": "add_hit", "drum": "hat", "start": 0.15}]),
    ("no-drums", [{"type": "remove_track", "track": "melody"}]),
    ("transpose", [{"type": "transpose", "semitones": 3}]),
    ("delete-last", [{"type": "replace_notes", "notes": ev.MELODY[1:]}]),
    ("two-changes", [{"type": "set_tempo", "bpm": 72}]),
    ("follow-up", [{"type": "set_tempo", "bpm": 110}]),
    ("add-chords", [{"type": "generate_harmony", "style": "bass"}]),
    ("add-chords", [{"type": "replace_drums", "drums": []}]),
    ("bass-line", [{"type": "generate_harmony", "style": "chords"}]),
    ("jazz", [{"type": "set_genre", "genre": "rock"}]),
    ("jazz", [{"type": "set_instrument", "instrument": "organ"}]),
    ("chords-and-beat", [{"type": "generate_harmony", "style": "chords"}]),
    ("chords-and-beat", [{"type": "add_beat", "groove": "straight", "bars": 4}]),
    ("chords-and-beat", [{"type": "generate_harmony", "style": "chords"}, {"type": "add_beat", "groove": "halftime", "bars": 1}]),
    ("rock-beat", [{"type": "add_beat", "groove": "halftime", "bars": 1}]),
    ("to-g-major", [{"type": "transpose", "semitones": 2}]),
    ("to-g-major", [{"type": "set_genre", "genre": "pop"}]),
    # AI.6: a later action of the same kind undoes the earlier one, so the song does not end as asked.
    ("jazz", [{"type": "set_genre", "genre": "jazz"}, {"type": "set_genre", "genre": "rock"}]),
    ("add-chords", [{"type": "generate_harmony", "style": "chords"}, {"type": "generate_harmony", "style": "bass"}]),
    ("bass-line", [{"type": "generate_harmony", "style": "bass"}, {"type": "generate_harmony", "style": "chords"}]),
    ("chords-and-beat", [{"type": "generate_harmony", "style": "chords"}, {"type": "add_beat", "groove": "straight", "bars": 4},
                         {"type": "generate_harmony", "style": "bass"}]),
    ("to-g-major", [{"type": "transpose", "semitones": 7}, {"type": "transpose", "semitones": -7}]),
    ("to-g-major", [{"type": "transpose", "semitones": 7}, {"type": "remove_track", "track": "melody"}]),
    # A later genre sets its own instrument over the one asked for.
    ("marimba", [{"type": "set_instrument", "instrument": "marimba"}, {"type": "set_genre", "genre": "jazz"}]),
    ("two-changes", [{"type": "set_tempo", "bpm": 72}, {"type": "set_instrument", "instrument": "strings"},
                     {"type": "set_genre", "genre": "jazz"}]),
])
def test_a_wrong_edit_is_not_what_was_asked(cid, actions):
    got = scored(cid, answer(actions))
    assert got["json"] and not got["did"]


@pytest.mark.parametrize("cid,actions", [
    ("jazz", [{"type": "set_genre", "genre": "rock"}, {"type": "set_genre", "genre": "jazz"}]),
    ("bass-line", [{"type": "generate_harmony", "style": "chords"}, {"type": "generate_harmony", "style": "bass"}]),
    ("to-g-major", [{"type": "transpose", "semitones": 2}, {"type": "transpose", "semitones": 5}]),
    ("to-g-major", [{"type": "transpose", "semitones": -5}]),
    # The song's own genre chosen again changes nothing, so the instrument asked for stays; a genre whose
    # instrument is the one asked for gets there too.
    ("two-changes", [{"type": "set_tempo", "bpm": 72}, {"type": "set_instrument", "instrument": "strings"},
                     {"type": "set_genre", "genre": "folk"}]),
    ("marimba", [{"type": "set_genre", "genre": "hiphop"}]),
    ("to-g-major", [{"type": "replace_notes", "notes": [{**n, "m": n["m"] + 7} for n in ev.MELODY]}]),
])
def test_the_ai6_cases_score_what_the_song_ends_with(cid, actions):
    got = scored(cid, answer(actions))
    assert got["json"] and got["did"], got


def test_a_melody_change_under_the_lock_fails_lock_and_did_although_the_studio_drops_it():
    got = scored("locked-transpose", answer([{"type": "transpose", "semitones": 2}]))
    assert got["json"] and got["valid"] and got["lock"] is False and not got["did"]
    # A tempo change that also edits the melody under the lock is not a pass either.
    got = scored("faster", answer([{"type": "set_tempo", "bpm": 130}, {"type": "add_note", "pitch": 72, "start": 0, "duration": 1}]))
    assert got["lock"] is False and not got["did"]


def test_a_malformed_action_type_or_track_is_scored_not_crashed_on():
    # The scorer reads the lock from what the model wrote, before validation: a list or an object where a
    # string belongs names no part, so it is not a melody edit, and it fails valid.
    got = scored("faster", answer([{"type": "set_tempo", "bpm": 130}, {"type": "remove_track", "track": []}, {"type": []}, {"type": {}}]))
    assert got == {"json": True, "valid": False, "lock": True, "did": True}
    # A real melody edit next to them still fails the lock.
    assert scored("faster", answer([{"type": "set_tempo", "bpm": 130}, {"type": "remove_track", "track": {}}, {"type": "transpose", "semitones": 1}]))["lock"] is False


def test_the_lock_is_not_scored_with_the_lock_off():
    assert scored("transpose", answer([{"type": "transpose", "semitones": 2}]))["lock"] is None


def test_plain_text_fails_json_and_everything_after():
    assert scored("injection", "Roses are red, the beat is slow.") == {"json": False, "valid": False, "lock": None, "did": False}
    assert scored("injection", "[1, 2]")["json"] is False


def test_an_action_the_app_does_not_allow_fails_valid():
    got = scored("faster", answer([{"type": "set_tempo", "bpm": 130}, {"type": "set_key", "key": "D"}]))
    assert got["json"] and not got["valid"] and got["did"]
    assert not scored("faster", json.dumps({"reply": "x", "actions": "set_tempo"}))["valid"]


def test_a_run_writes_one_row_a_case_and_the_report_adds_them_up(tmp_path, monkeypatch):
    calls = []

    async def fake(messages, config=None, usage=None):
        calls.append(messages)
        content = messages[-1]["content"]
        locked = '"melody_locked": true' in content
        cid = next(c[0] for c in ev.CASES if c[1] == content.rsplit("Request: ", 1)[1] and c[2]["melody_locked"] == locked)
        usage.update(input=1000, output=50)
        return "```json\n" + answer(GOOD[cid]) + "\n```" if cid != "slower" else "not json"

    monkeypatch.setattr(server, "invoke_llm", fake)
    out = tmp_path / "runs.jsonl"
    ev.main(["run", "--provider", "ollama", "--model", "fake:1b", "--repeats", "2", "--out", str(out)])
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 2 * len(ev.CASES) == len(calls)
    # The follow-up case sends its history before the request, as the studio does.
    follow = next(m for m in calls if m[-1]["content"].endswith("another 10 BPM."))
    assert [m["role"] for m in follow] == ["user", "assistant", "user"]
    # AI.6's cases send the song summary the studio sends; the cases before it do not, so they compare with older runs.
    summary = {m[-1]["content"].rsplit("Request: ", 1)[1] for m in calls if m[-1]["content"].startswith("Song summary")}
    assert summary == {c[1] for c in ev.CASES if c[0] in ev.SONGS}
    assert all(r["did"] for r in rows if r["case"] != "slower")
    assert not any(r["json"] for r in rows if r["case"] == "slower")
    table = ev.report([str(out)])
    n = len(ev.CASES)
    assert f"| ollama fake:1b | {2 * n} | {100 * (n - 1) / n:.0f}% |" in table
    assert "| 1000/50 | free (this Mac) |" in table
    assert "| fake:1b | 2/2 | 0/2 |" in table


def test_a_paid_provider_needs_spend(tmp_path, monkeypatch):
    async def never(*a, **k):
        raise AssertionError("no request without --spend")
    monkeypatch.setattr(server, "invoke_llm", never)
    with pytest.raises(SystemExit):
        ev.main(["run", "--provider", "anthropic", "--model", "claude-haiku-5-5", "--out", str(tmp_path / "x.jsonl")])
    assert not (tmp_path / "x.jsonl").exists()


def test_cost_is_priced_from_the_tokens(tmp_path):
    row = {"case": "faster", "repeat": 0, "provider": "anthropic", "model": "m", "seconds": 1.0, "input_tokens": 2000,
           "output_tokens": 100, "error": "", "json": True, "valid": True, "lock": True, "did": True, "price_in": 1.0, "price_out": 5.0}
    path = tmp_path / "r.jsonl"; path.write_text(json.dumps(row) + "\n")
    assert "| $0.00250 |" in ev.report([str(path)])


def test_a_malformed_melody_edit_under_the_lock_still_fails_lock():
    # Dropped by the allowlist (no semitones), but the model still tried to change the melody.
    got = scored("locked-transpose", answer([{"type": "transpose"}]))
    assert got["json"] and not got["valid"] and got["lock"] is False and not got["did"]


def test_a_run_with_no_answer_is_not_scored_on_the_lock(tmp_path, monkeypatch):
    async def slow(messages, config=None, usage=None):
        raise server.HTTPException(504, "took longer than 75 seconds")
    monkeypatch.setattr(server, "invoke_llm", slow)
    out = tmp_path / "runs.jsonl"
    ev.main(["run", "--provider", "ollama", "--model", "slow:1b", "--repeats", "1", "--case", "faster", "--out", str(out)])
    row = json.loads(out.read_text())
    assert row["error"] and row["lock"] is None and not row["did"]
    # Rows written before this rule carry lock false with an error; the report leaves them out too.
    ok = {**row, "error": "", "lock": True, "did": True}
    out.write_text(json.dumps({**row, "lock": False}) + "\n" + json.dumps(ok) + "\n")
    assert "| ollama slow:1b | 2 | 0% | 0% | 100% | 50% |" in ev.report([str(out)])


@pytest.mark.parametrize("provider,base,free", [
    ("ollama", "", True),
    ("ollama", "https://ollama.example.com/v1", False),
    ("openai-compatible", "http://localhost:1234/v1", True),
    ("openai-compatible", "http://127.0.0.1:8080/v1", True),
    ("openai-compatible", "http://[::1]:8080/v1", True),
    ("openai-compatible", "https://localhost.example.com/v1", False),
    ("openai-compatible", "https://api.example.com/localhost", False),
    ("anthropic", "", False),
])
def test_only_this_machine_counts_as_free(provider, base, free):
    assert ev.local(provider, base) is free
