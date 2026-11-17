"""AI.5: the chat evaluation harness (tools/chat-eval/chat_eval.py), with the model faked.

A model that answers every case correctly scores 100% everywhere; each kind of wrong answer is caught
by the score it should fail. No provider is called."""
import asyncio
import importlib.util
import json
import pathlib

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
}


def case(cid):
    return next(c for c in ev.CASES if c[0] == cid)


def scored(cid, raw):
    cid, message, proj, history, check = case(cid)
    req = server.ChatRequest(message=message, project=proj, history=history)
    return ev.score(raw, req, check, req.project.model_dump())


def answer(actions):
    return json.dumps({"reply": "Done.", "actions": actions})


def test_every_case_has_a_right_answer_that_scores_full_marks():
    assert {c[0] for c in ev.CASES} == set(GOOD)
    for cid, actions in GOOD.items():
        got = scored(cid, answer(actions))
        assert got["json"] and got["valid"] and got["did"], (cid, got)
        assert got["lock"] in (True, None), (cid, got)


def test_every_case_project_is_one_the_studio_could_send():
    for cid, message, proj, history, check in ev.CASES:
        server.ChatRequest(message=message, project=proj, history=history)


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
])
def test_a_wrong_edit_is_not_what_was_asked(cid, actions):
    got = scored(cid, answer(actions))
    assert got["json"] and not got["did"]


def test_a_melody_change_under_the_lock_fails_lock_and_did_although_the_studio_drops_it():
    got = scored("locked-transpose", answer([{"type": "transpose", "semitones": 2}]))
    assert got["json"] and got["valid"] and got["lock"] is False and not got["did"]
    # A tempo change that also edits the melody under the lock is not a pass either.
    got = scored("faster", answer([{"type": "set_tempo", "bpm": 130}, {"type": "add_note", "pitch": 72, "start": 0, "duration": 1}]))
    assert got["lock"] is False and not got["did"]


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
