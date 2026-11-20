"""AI.7: the chat's actions come from one registry (actions.json) in a real Chromium. Every registry action, as the
server's own chat_plan validates it from a canned model text, runs through the studio's chat form and actions.js as one
undoable edit; the request carries the song summary (the key and the chords the chords strip shows) and is checked
against the server's ChatRequest and prompt. Only the model's text is canned: e2e runs without provider credentials.

The example project is at 100 bpm (a 2.4 s bar): 8 melody notes 0.45 s apart (60 64 67 69 67 64 62 60), in C major.
"""
import json
import re

from playwright.sync_api import expect

from conftest import show_part
from test_studio import IDB_DRAFT, count, note_pitches


def ask(page, server, model_text, message, extra=0):
    """Sends message through the chat form; the route answers with chat_plan(model_text) for the real request."""
    sent = []

    def answer(route):
        req = server.ChatRequest.model_validate(json.loads(route.request.post_data))
        sent.append((req, server.chat_messages(req)[-1]["content"]))
        route.fulfill(status=200, json=server.chat_plan(model_text, req))
    page.unroute("**/api/chat")
    page.route("**/api/chat", answer)
    bubbles = page.locator("#chat .bubble").count()
    page.fill("#prompt", message)
    page.click("#chatform button[type=submit]")
    expect(page.locator("#chat .bubble")).to_have_count(bubbles + 2 + extra)   # extra: an action the song cannot take
    return sent[0]


def test_every_registry_action_runs_as_one_edit_and_the_request_carries_the_song_summary(studio):
    import tandem_backend as server
    page = studio
    page.click("#demo")
    show_part(page, "harmony")
    page.select_option("#harmonystyle", "chords")
    page.select_option("#harmonykey", "0:major")
    page.click("#genharmony")
    expect(page.locator("#status")).to_contain_text("in C major")
    shown = page.eval_on_selector_all("#chordstrip .chordsym", "els => els.map(b => [b.dataset.name, Number(b.dataset.t)])")
    assert shown, "the chords strip shows the generated chords"
    show_part(page, "song")
    page.uncheck("#melodylock")

    # One model reply with every action actions.json declares, in its order.
    actions = [
        {"type": "set_tempo", "bpm": 120}, {"type": "set_instrument", "instrument": "marimba"},
        {"type": "transpose", "semitones": 2}, {"type": "add_note", "pitch": 72, "start": 5, "duration": 0.5},
        {"type": "add_hit", "drum": "snare", "start": 5}, {"type": "remove_track", "track": "rhythm"},
        {"type": "replace_drums", "drums": [{"k": "kick", "t": 0}, {"k": "cowbell", "t": 1}, {"k": "hat", "t": 0.5}]},
    ]
    assert [a["type"] for a in actions] == [n for n in server.ACTIONS if n not in ("replace_notes", "generate_harmony", "add_beat", "set_genre")]
    before = page.evaluate(IDB_DRAFT)
    req, prompt = ask(page, server, json.dumps({"reply": "Brighter and faster.", "actions": actions}), "brighter and faster")
    expect(page.locator("#status")).to_have_text("Applied 7 AI edit(s). Undo is available.")
    expect(page.locator("#bpm")).to_have_value("120")
    expect(page.locator("#instrument")).to_have_value("marimba")
    assert note_pitches(page) == [62, 66, 69, 71, 69, 66, 64, 62, 72]
    # remove_track cleared the drums, add_hit's snare went with them, and replace_drums left out the cowbell.
    assert page.evaluate(IDB_DRAFT)["drums"] == [{"k": "kick", "t": 0}, {"k": "hat", "t": 0.5}]

    # The request: the studio's key and chords, named in the prompt as the chords strip names them.
    assert req.song.key.model_dump() == {"tonic": 0, "mode": "major"}
    assert [(server.KEY_NAMES[c.root] + server.CHORD_SUFFIXES[c.quality], c.t) for c in req.song.chords] == [tuple(x) for x in shown]
    assert "Key: C major\n" in prompt and "Tempo: 100 bpm, so a 4/4 bar lasts 2.40 s\n" in prompt
    assert f"\nChords: {shown[0][0]} at {shown[0][1]:.2f} s for 2.40 s" in prompt
    parts = prompt.split("\nParts: ", 1)[1].split("\n", 1)[0]
    assert parts.startswith("melody: 8 notes, C4 to A4, 0.00 to 3.51 s, on marimba; chords: 6 notes, E3 to C4, 0.00 to 4.66 s, on piano; "), parts
    assert parts.endswith("; harmony voice: none; drums: 16 hits (4 kick, 4 snare, 8 hat), 0.00 to 3.38 s"), parts

    # One undo takes the whole reply back.
    page.click("#undo")
    expect(page.locator("#bpm")).to_have_value("100")
    after = page.evaluate(IDB_DRAFT)
    assert (after["notes"], after["drums"], after["instrument"]) == (before["notes"], before["drums"], before["instrument"])

    # replace_notes, and melody lock dropping it once the lock is back on: the lock comes from the registry's parts.
    req, _ = ask(page, server, json.dumps({"reply": "New tune.", "actions": [{"type": "replace_notes", "notes": [{"m": 70, "t": 0, "d": 1}]}]}), "new tune")
    assert note_pitches(page) == [70]
    page.click("#undo")
    page.check("#melodylock")
    ask(page, server, json.dumps({"reply": "New tune.", "actions": [{"type": "replace_notes", "notes": [{"m": 70, "t": 0, "d": 1}]},
                                                                    {"type": "add_hit", "drum": "kick", "start": 3}]}), "new tune")
    expect(page.locator("#status")).to_have_text("Applied 1 AI edit(s). Undo is available.")
    assert note_pitches(page) == [60, 64, 67, 69, 67, 64, 62, 60] and count(page, "hitcount") == 17

    # remove_track on its own (in the reply above replace_drums wrote the drums after it): the drums are gone, and
    # Undo brings back every hit.
    before = page.evaluate(IDB_DRAFT)["drums"]
    assert len(before) == 17
    ask(page, server, json.dumps({"reply": "No drums.", "actions": [{"type": "remove_track", "track": "rhythm"}]}), "no drums")
    expect(page.locator("#status")).to_have_text("Applied 1 AI edit(s). Undo is available.")
    assert count(page, "hitcount") == 0 and page.evaluate(IDB_DRAFT)["drums"] == []
    page.click("#undo")
    expect(page.locator("#hitcount")).to_have_text(re.compile(r"^17 "))
    assert page.evaluate(IDB_DRAFT)["drums"] == before


def test_chords_a_beat_and_a_genre_from_the_chat_are_what_the_studio_makes_and_undo_as_one(studio):
    """AI.6: set_genre, generate_harmony and add_beat run the studio's own Genre menu, Generate and Starter beat."""
    import tandem_backend as server
    page = studio
    page.click("#demo")
    show_part(page, "song")
    page.uncheck("#melodylock")
    page.check("#melodylock")   # the lock does not stop them: none of them changes the melody
    before = page.evaluate(IDB_DRAFT)
    assert not before.get("harmony") and not before.get("genre")
    actions = [{"type": "set_genre", "genre": "jazz"}, {"type": "generate_harmony", "style": "chords"},
               {"type": "add_beat", "groove": "shuffle", "bars": 4}]
    req, prompt = ask(page, server, json.dumps({"reply": "Jazz chords and a shuffle.", "actions": actions}), "make it a jazz song with chords and a beat")
    assert "generate_harmony (style chords or bass" in server.SYSTEM and req.project.melody_locked
    expect(page.locator("#status")).to_have_text("Applied 3 AI edit(s). Undo is available.")
    # The genre menus and the controls a genre sets follow, as choosing it in the menu does.
    expect(page.locator("#genre")).to_have_value("jazz")
    expect(page.locator("#groove")).to_have_value("shuffle")   # jazz's starter beat (genre.js)
    expect(page.locator("#swing")).to_have_value("100")
    expect(page.locator("#chordstrip .chordsym").first).to_be_visible()
    ai = page.evaluate(IDB_DRAFT)
    assert ai["genre"] == "jazz" and ai["notes"] == before["notes"]
    assert ai["harmony"] and len(ai["drums"]) == 4 * 12   # shuffle: 2 kicks, 2 snares, 8 hats a bar
    assert sorted({h["k"] for h in ai["drums"]}) == ["hat", "kick", "snare"]

    # One Undo takes the reply back.
    page.click("#undo")
    expect(page.locator("#genre")).to_have_value("")
    undone = page.evaluate(IDB_DRAFT)
    assert (undone["notes"], undone["drums"], undone.get("harmony") or [], undone.get("genre")) == (before["notes"], before["drums"], [], None)

    # The same three by hand, with the studio's own controls, make the same project.
    page.select_option("#genre", "jazz")
    show_part(page, "harmony")
    page.select_option("#harmonystyle", "chords")
    page.click("#genharmony")
    show_part(page, "drums")
    page.select_option("#groove", "shuffle")
    page.select_option("#groovebars", "4")
    page.uncheck("#groovekeep")
    page.click("#addgroove")
    expect(page.locator("#status")).to_contain_text("Added the shuffle beat")
    by_hand = page.evaluate(IDB_DRAFT)
    for k in ("genre", "instrument", "harmony_instrument", "harmony", "drums", "notes"):
        assert by_hand.get(k) == ai.get(k), k


def test_an_action_the_song_cannot_take_is_told_in_the_chat_and_the_rest_apply(studio):
    import tandem_backend as server
    page = studio
    show_part(page, "song")
    ask(page, server, json.dumps({"reply": "Chords, and slower.", "actions": [{"type": "generate_harmony", "style": "chords"}, {"type": "set_tempo", "bpm": 90}]}),
        "add chords and slow it down", extra=1)
    expect(page.locator("#chat .bubble").last).to_have_text("Tandem could not do generate_harmony: Add or transcribe a melody before generating harmony.")
    expect(page.locator("#status")).to_have_text("Applied 1 AI edit(s). Undo is available. 1 could not be done; see the chat.")
    expect(page.locator("#bpm")).to_have_value("90")
    assert not page.evaluate(IDB_DRAFT).get("harmony")
