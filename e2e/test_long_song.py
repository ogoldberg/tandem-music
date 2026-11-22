"""GROW.2: room for a whole song. A three-minute song (90 bars at 120 bpm, a starter beat as long as the song, more hits
than the old 1,024 a part) plays, exports as WAV and MIDI, and the chat refuses it in words without sending it. The time of
one edit's update() and of one undo step is measured under CPU throttling, on that song and on one at the full 4,096
events a part, and held under a budget."""
import json
import wave

from playwright.sync_api import expect

from conftest import show_part
from test_beats import drum_hits
from test_studio import download, wait_until

BPM = 120  # a 2 s bar
SECONDS = 180
# Chromium's CPU throttling: 4x is DevTools' "low-end mobile" preset.
THROTTLE = 4
# The budget for one edit (update() and the redraw) and for one undo step, in ms of wall time while throttled.
# Measured on an M-series Mac on 2026-11-22 (docs/TESTING.md, GROW.2): about 50 ms on the three-minute song and about
# 450 ms at 4,096 events a part (1,300 ms before readChords read each bar from its own notes). The budgets leave
# room for a slower CI runner and still catch a redraw that grows with the square of the song.
BUDGET_SONG_MS = 400
BUDGET_FULL_MS = 1200


def open_song(page, tmp_path, project, name="song.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"format": "tandem-project", "version": 1, "bpm": BPM, "instrument": "piano",
                                "melody_locked": True, "drums": [], **project}))
    page.set_input_files("#projectfile", str(path))
    expect(page.locator("#status")).to_have_text("Project opened")


def three_minute_melody():
    # A four-bar tune of quarter notes, 22 times and a half: 90 bars, 360 notes, the last ending at 180 s.
    tune = [60, 62, 64, 65, 67, 65, 64, 62, 60, 64, 67, 72, 71, 67, 64, 62]
    return [{"m": tune[i % 16], "t": i * 0.5, "d": 0.45} for i in range(SECONDS * 2)]


def edit_and_undo_ms(page):
    """The slowest of three: an edit (the melody instrument, one edit and one update()) and the undo step after it."""
    edits, undos = [], []
    for instrument in ("flute", "marimba", "strings"):
        edits.append(page.evaluate("""async which => {
          const s = document.getElementById('instrument'), t = performance.now();
          s.value = which; s.dispatchEvent(new Event('change'));
          await new Promise(r => requestAnimationFrame(() => setTimeout(r, 0)));
          return performance.now() - t;
        }""", instrument))
        expect(page.locator("#undo")).to_have_attribute("title", "Undo: Change instrument")
        undos.append(page.evaluate("""async () => {
          const t = performance.now();
          document.getElementById('undo').click();
          await new Promise(r => requestAnimationFrame(() => setTimeout(r, 0)));
          return performance.now() - t;
        }"""))
        expect(page.locator("#instrument")).to_have_value("piano")
    return max(edits), max(undos)


def test_a_three_minute_song_plays_exports_and_the_chat_refuses_it_in_words(studio, tmp_path):
    page = studio
    open_song(page, tmp_path, {"notes": three_minute_melody()})

    # A starter beat as long as the song: 90 bars, past the old 64-bar cap and the old 1,024 hits a part.
    show_part(page, "drums")
    page.select_option("#groove", "straight")
    page.select_option("#groovebars", "song")
    page.click("#addgroove")
    expect(page.locator("#status")).to_contain_text("Added the straight beat")
    hits = drum_hits(page)
    assert len(hits) == 90 * 12, len(hits)
    assert max(t for _, t in hits) == 179.75

    # It plays: the playhead moves from the start.
    page.click("#play")
    wait_until(page, "() => Number(document.getElementById('timeline').dataset.t) > 0.3", "the playhead moving")
    page.click("#stop")

    # The MIDI file has every note and hit; the WAV is the whole three minutes.
    midi = download(page, "#exportmidi", tmp_path).read_bytes()
    assert midi.count(b"MTrk") >= 3
    with page.expect_download(timeout=180_000) as info:
        page.click("#exportwav")
    with wave.open(str(info.value.path())) as w:
        assert SECONDS <= w.getnframes() / w.getframerate() < SECONDS + 5

    # The chat refuses the song before sending it, in words, and the typed request stays in the box.
    sent = []
    page.route("**/api/chat", lambda route: (sent.append(route.request.url), route.abort()))
    bubbles = page.locator("#chat .bubble").count()
    show_part(page, "song")
    page.fill("#prompt", "Add a bass line")
    page.click("#chatform button[type=submit]")
    expect(page.locator("#chat .bubble")).to_have_count(bubbles + 1)
    expect(page.locator("#chat .bubble").last).to_have_text(
        "This song is too long for Ask Tandem to read yet: the drums have 1080 hits, and Ask Tandem reads up to 1024 "
        "a part. Nothing was sent.")
    expect(page.locator("#prompt")).to_have_value("Add a bass line")
    assert sent == []

    # One edit and one undo step on this song, with the CPU slowed down four times.
    cdp = page.context.new_cdp_session(page)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": THROTTLE})
    try:
        edit, undo = edit_and_undo_ms(page)
    finally:
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
    print(f"GROW.2 three-minute song, {THROTTLE}x throttled: edit {edit:.0f} ms, undo {undo:.0f} ms")
    assert edit < BUDGET_SONG_MS and undo < BUDGET_SONG_MS, (edit, undo)


def test_a_song_at_4096_events_a_part_opens_and_edits_within_the_budget(studio, tmp_path):
    page = studio
    n, step = 4096, 590 / 4096
    note = lambda i, low: {"m": low + (i * 7) % 24, "t": round(i * step, 3), "d": round(step * 0.8, 3)}
    kinds = ["kick", "hat", "snare", "hat"]
    open_song(page, tmp_path, {
        "notes": [note(i, 55) for i in range(n)],
        "harmony": [note(i, 48) for i in range(n)],
        "voice2": [note(i, 59) for i in range(n)],
        "drums": [{"k": kinds[i % 4], "t": round(i * step, 3)} for i in range(n)],
    }, "full.json")
    expect(page.locator("#notecount")).to_have_text("4096 notes")
    assert page.locator("#drumroll .hit").count() == n

    cdp = page.context.new_cdp_session(page)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": THROTTLE})
    try:
        edit, undo = edit_and_undo_ms(page)
    finally:
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
    print(f"GROW.2 4,096 events a part, {THROTTLE}x throttled: edit {edit:.0f} ms, undo {undo:.0f} ms")
    assert edit < BUDGET_FULL_MS and undo < BUDGET_FULL_MS, (edit, undo)


def test_a_song_within_the_chat_s_cap_is_still_sent(studio, tmp_path):
    """A 1,024-event part behaves as before: the chat sends it."""
    page = studio
    open_song(page, tmp_path, {"notes": [{"m": 60 + i % 12, "t": round(i * 0.5, 3), "d": 0.4} for i in range(1024)]})
    sent = []
    page.route("**/api/chat", lambda route: (sent.append(json.loads(route.request.post_data)),
                                            route.fulfill(status=200, json={"reply": "Fine.", "actions": []})))
    show_part(page, "song")
    page.fill("#prompt", "Hello")
    page.click("#chatform button[type=submit]")
    expect(page.locator("#chat .bubble").last).to_have_text("Fine.")
    assert len(sent) == 1 and len(sent[0]["project"]["notes"]) == 1024
