"""FX.1: a little room on the voice, in a real Chromium.

The voice's Room amount is one edit kept in `mix`. At zero the voice stem is the take exactly (test_mixer.py); with
room the voice stem is the take plus the room's impulse (mixer.js roomImpulse, read from the page) at the wet level,
convolved, so the export runs the same tail the Node tests check, and the tail rings on after the take stops.
Export WAV is levelled to -1 dB however much room is added, so it never clips. While the song plays, the room's wet
gain follows the slider at once, and the guided Sound view shows the same control.
"""
import json
import re
import wave

import numpy as np
from playwright.sync_api import expect
from scipy.signal import fftconvolve

from conftest import export_gain
from test_guided import guided_page, open_view
from test_mixer import RATE, download, open_song, samples, stems


def set_room(page, amount):
    # The way a drag ends: input while it moves, change when let go.
    page.eval_on_selector("#room-voice", """(el, v) => { el.value = String(v);
        el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); }""", amount)


def import_take(page, tmp_path, loud=0.4):
    """A take of one second of 220 Hz, then five of silence, unmuted in the mixer."""
    rate = 22050
    t = np.arange(int(rate * 6.0)) / rate
    x = np.where(t < 1.0, loud * np.sin(2 * np.pi * 220 * t), 0.0)
    with wave.open(str(tmp_path / "take.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    page.set_input_files("#audiofile", str(tmp_path / "take.wav"))
    expect(page.locator("#status")).to_have_text(re.compile(r"^Recorded 6\.0s"))
    page.click("#mute-voice")
    expect(page.locator("#mute-voice")).to_have_attribute("aria-pressed", "false")


def impulse(page):
    return np.array(page.evaluate("async () => Array.from((await import('./mixer.js')).roomImpulse(44100))"))


def test_the_room_is_the_takes_tail_in_the_voice_stem_and_one_edit(studio, tmp_path):
    page = studio
    open_song(page, tmp_path)
    import_take(page, tmp_path)
    expect(page.locator("#roomout-voice")).to_have_text("Dry")
    dry = stems(page)
    assert np.max(np.abs(dry["voice.wav"] - dry["vocal-original.wav"])) < 1e-4, "no room is the take as it was"

    set_room(page, 0.5)
    expect(page.locator("#roomout-voice")).to_have_text("50 %")
    expect(page.locator("#undo")).to_have_attribute("title", re.compile("Room on your voice: 50 %"))
    saved = json.loads(download(page, "#save"))
    assert saved["mix"]["voice"] == {"mute": False, "room": 0.5}

    wet = stems(page)
    voice, raw = wet["voice.wav"], wet["vocal-original.wav"]
    ir = impulse(page)
    assert len(ir) == round(0.012 * RATE) + round(0.8 * RATE)
    want = fftconvolve(raw, ir)[:len(voice)] * 0.25  # ROOM_WET 0.5 at a Room of 0.5
    want[:len(raw)] += raw
    assert np.max(np.abs(voice - want)) < 2e-3, "the take, and under it the room's tail at a quarter"
    second = RATE
    assert np.max(np.abs(raw[second + 600:second + 4000])) < 1e-3, "the take is silent after a second"
    tail = np.sqrt(np.mean(voice[second + 600:second + 4000] ** 2))
    assert tail > 5e-3, "the room rings on after the take stops"
    assert np.max(np.abs(voice[second + int(0.9 * RATE):second + int(1.5 * RATE)])) < 1e-3, "and dies away within the tail"
    assert np.max(np.abs(wet["mix.wav"] - (voice + wet["melody.wav"] + wet["drums.wav"]))) < 1e-4

    page.click("#undo")
    expect(page.locator("#roomout-voice")).to_have_text("Dry")
    assert json.loads(download(page, "#save"))["mix"]["voice"] == {"mute": False}

    # The room goes with the voice: muted, the voice has no stem and the room is not heard.
    page.click("#redo")
    expect(page.locator("#roomout-voice")).to_have_text("50 %")
    page.click("#mute-voice")
    assert "voice.wav" not in stems(page)
    expect(page.locator("#room-voice")).to_have_attribute("title", re.compile("unmute it first"))


def test_a_loud_take_with_room_does_not_clip_the_export(studio, tmp_path):
    page = studio
    open_song(page, tmp_path)
    import_take(page, tmp_path, loud=0.98)
    target = round(10 ** (-1 / 20) * 32767)
    before = download(page, "#exportwav")
    set_room(page, 1)
    expect(page.locator("#roomout-voice")).to_have_text("100 %")
    after = download(page, "#exportwav")
    pcm = samples(after) * 32767
    assert round(np.max(np.abs(pcm))) == target, "levelled to -1 dB, not clipped"
    assert export_gain(page) < 1, "the room made it louder, so it was turned down"
    a, b = samples(before), samples(after)
    assert len(b) >= len(a)
    assert np.max(np.abs(a - b[:len(a)])) > 0.01, "the export changed"


def test_the_room_follows_the_slider_while_playing(studio, tmp_path):
    page = studio
    open_song(page, tmp_path)
    import_take(page, tmp_path)
    set_room(page, 0.4)
    page.click("#play")
    page.wait_for_function("(document.getElementById('timeline').dataset.mix || '').length > 0")
    assert json.loads(page.get_attribute("#timeline", "data-mix"))["room"] == 0.2
    page.eval_on_selector("#room-voice", "el => { el.value = '0'; el.dispatchEvent(new Event('input', {bubbles: true})); }")
    page.wait_for_function("JSON.parse(document.getElementById('timeline').dataset.mix || '{}').room === 0")
    page.click("#stop")
    # Only dragged, never let go: no edit was made.
    expect(page.locator("#undo")).to_have_attribute("title", re.compile("Room on your voice: 40 %"))


def test_the_guided_sound_view_has_the_room_under_your_voice(browser, server_url):
    with guided_page(browser, server_url) as page:
        open_view(page, "sound")
        room = page.locator('.gview[data-view="sound"] #slot-room-voice #room-voice')
        expect(room).to_be_visible()
        expect(page.locator("#roomout-voice")).to_have_text("Dry")
        room.fill("0.25")
        expect(page.locator("#roomout-voice")).to_have_text("25 %")
        expect(page.locator("#gundo")).to_have_attribute("title", "Undo: Room on your voice: 25 %")
