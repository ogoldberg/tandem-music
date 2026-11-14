"""PLAY.1: the playhead, play from here and a looped section, in a real Chromium.

The timeline's data-t is the song time the playhead is drawn at, read from the audio clock each frame.
The example project is 8 melody notes 0.45 s apart (0.36 s long) and 16 drum hits, so the timeline and
every roll show 8 s. With the mocked MIDI output of e2e/test_midi.py the notes played are the messages
the output is sent, so the test can check which notes play from a time and that a loop repeats.
"""
import time

from playwright.sync_api import expect

from test_midi import MOCK_MIDI, connect, open_studio, sent

HEAD = """() => new Promise(r => requestAnimationFrame(() => {
  const t = document.getElementById('timeline').dataset.t;
  r([performance.now() / 1000, t === '' || t == null ? null : Number(t)]);
}))"""


def song_end(page):
    """The seconds the timeline shows, from the left of the second bar tick (one bar at the tempo)."""
    bar = 240 / float(page.locator("#bpm").input_value())
    left = page.locator("#timeline .tick").nth(1).evaluate("e => parseFloat(e.style.left)")
    return bar * 97 / left


def x_at(page, t):
    box = page.locator("#timeline").bounding_box()
    return box["x"] + box["width"] * 0.97 * t / song_end(page), box["y"] + box["height"] / 2


def head(page):
    return page.evaluate(HEAD)


def wait_playing(page):
    page.wait_for_function("document.getElementById('timeline').dataset.t > ''", timeout=10000)


def drag_loop(page, a, b):
    page.locator("#timeline").scroll_into_view_if_needed()
    (xa, y), (xb, _) = x_at(page, a), x_at(page, b)
    page.mouse.move(xa, y)
    page.mouse.down()
    for i in range(1, 11):
        page.mouse.move(xa + (xb - xa) * i / 10, y)
    page.mouse.up()


def loop_bounds(page):
    text = page.locator("#timeinfo").text_content()
    parts = text.replace("Section ", "").split(" s")[0].split(" to ")
    return float(parts[0]), float(parts[1])


def test_click_on_the_timeline_plays_from_there_and_the_playhead_follows_the_audio_clock(studio):
    page = studio
    page.click("#demo")
    assert abs(song_end(page) - 8) < 0.01
    expect(page.locator("#loop")).to_be_disabled()
    page.locator("#timeline").scroll_into_view_if_needed()
    x, y = x_at(page, 3.0)
    clicked = time.monotonic()
    page.mouse.click(x, y)
    expect(page.locator("#status")).to_contain_text("Playing composition from 3.0 s")
    wait_playing(page)
    wall, t = head(page)
    elapsed = time.monotonic() - clicked
    # It starts at the time clicked (within a pixel of the 506 px timeline), not at zero.
    assert 3.0 - 0.1 < t < 3.0 + elapsed + 0.1, (t, elapsed)
    # The playhead moves with the audio clock: one second of real time is one second of song.
    time.sleep(1.0)
    wall2, t2 = head(page)
    assert abs((t2 - t) - (wall2 - wall)) < 0.15, (t, t2, wall, wall2)
    # Each roll draws the playhead at the same place on the shared scale.
    lefts = page.evaluate("""() => ['timeline','melodyroll','drumroll'].map(id =>
        parseFloat(document.querySelector('#' + id + ' > .playhead').style.left))""")
    assert max(lefts) - min(lefts) < 0.5, lefts
    _, t3 = head(page)
    assert abs(lefts[0] - t3 / 8 * 97) < 2, (lefts, t3)
    # A note at a time is drawn where the playhead is at that time.
    note = page.locator("#melodyroll .note").nth(4).evaluate("e => parseFloat(e.style.left)")
    assert abs(note - 1.8 / 8 * 97) < 0.01
    # Past the end of the song (8 s) the playhead goes away.
    page.wait_for_function("document.getElementById('timeline').dataset.t === ''", timeout=8000)
    expect(page.locator("#melodyroll > .playhead")).to_have_count(0)


def test_a_dragged_section_loops_until_stop(studio):
    page = studio
    page.click("#demo")
    drag_loop(page, 1.0, 2.5)
    expect(page.locator("#loop")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#timeline .loopregion")).to_have_count(1)
    start, end = loop_bounds(page)
    assert abs(start - 1.0) < 0.1 and abs(end - 2.5) < 0.1, (start, end)
    page.click("#play")
    expect(page.locator("#status")).to_contain_text(f"from {start:.1f} s, looping {start:.1f} to {end:.1f} s")
    wait_playing(page)
    seen, began = [], time.monotonic()
    while time.monotonic() - began < 4.0:
        seen.append(head(page)[1])
        time.sleep(0.05)
    seen = [t for t in seen if t is not None]
    assert all(start - 0.02 <= t <= end + 0.02 for t in seen), seen
    wraps = sum(1 for a, b in zip(seen, seen[1:]) if b < a - 0.5)
    assert wraps >= 2, seen  # 4 s of a 1.5 s loop wraps twice
    # Stop ends it: the playhead goes and stays gone.
    page.click("#stop")
    expect(page.locator("#status")).to_have_text("Stopped")
    expect(page.locator("#timeline > .playhead")).to_have_count(0)
    # Loop off plays the whole song again; Clear loop forgets the section.
    page.click("#loop")
    expect(page.locator("#loop")).to_have_attribute("aria-pressed", "false")
    expect(page.locator("#timeline .loopregion.off")).to_have_count(1)
    page.click("#clearloop")
    expect(page.locator("#timeline .loopregion")).to_have_count(0)
    expect(page.locator("#loop")).to_be_disabled()
    page.click("#play")
    expect(page.locator("#status")).to_contain_text("Playing composition")
    expect(page.locator("#status")).not_to_contain_text("from")
    page.click("#stop")


def test_a_short_drag_is_a_click_and_a_too_short_section_is_not_a_loop(studio):
    page = studio
    page.click("#demo")
    page.locator("#timeline").scroll_into_view_if_needed()
    x, y = x_at(page, 2.0)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 3, y)
    page.mouse.up()
    expect(page.locator("#status")).to_contain_text("Playing composition from 2.0 s")
    page.click("#stop")
    drag_loop(page, 2.0, 2.15)
    expect(page.locator("#status")).to_contain_text("too short to loop")
    expect(page.locator("#loop")).to_be_disabled()


def melody_ons(page):
    return [d[1] for d in (e["data"] for e in sent(page)) if (d[0] & 0xF0) == 0x90 and d[2] > 0 and (d[0] & 15) != 9]


def midi_studio(page, server_url):
    problems = open_studio(page, server_url, MOCK_MIDI)
    connect(page)
    page.select_option("#midioutput", "out-1")
    page.click("#demo")
    page.evaluate("window.__midiSent.length = 0")
    return problems


def test_play_from_here_sends_the_notes_from_that_time(page, server_url):
    problems = midi_studio(page, server_url)
    page.locator("#timeline").scroll_into_view_if_needed()
    x, y = x_at(page, 1.5)  # inside the fourth note (69, 1.35 to 1.71 s)
    page.mouse.click(x, y)
    expect(page.locator("#status")).to_contain_text("Playing to Test Synth from 1.5 s")
    page.wait_for_function("window.__midiSent.filter(e => (e.data[0] & 0xf0) === 0x90 && e.data[2] > 0 && (e.data[0] & 15) !== 9).length >= 5", timeout=8000)
    # The note sounding at that time plays from there, then the rest; nothing before it.
    assert melody_ons(page)[:5] == [69, 67, 64, 62, 60]
    page.click("#stop")
    assert not problems, problems


def test_a_loop_resends_its_notes_each_pass(page, server_url):
    problems = midi_studio(page, server_url)
    drag_loop(page, 0.4, 1.3)  # the second and third notes (64 at 0.45 s, 67 at 0.9 s); 69 starts at 1.35 s
    page.click("#play")
    expect(page.locator("#status")).to_contain_text("Playing to Test Synth from 0.4 s, looping")
    page.wait_for_function("window.__midiSent.filter(e => (e.data[0] & 0xf0) === 0x90 && e.data[2] > 0 && (e.data[0] & 15) !== 9).length >= 6", timeout=8000)
    assert melody_ons(page)[:6] == [64, 67, 64, 67, 64, 67]
    page.click("#stop")
    sounding = page.evaluate("window.__midiSounding()")
    assert sounding == [], sounding
    assert not problems, problems
