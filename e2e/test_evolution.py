"""EVO.1: how the song grew, in a real Chromium.

A project whose melody, harmony and drums play through the whole song is opened, then an 8 s take is
imported and polished, so the song has five stages: the take, the polished take, the melody, the chords
and the drums. The evolution is exported and checked against the song's own stems (Export stems): each
section is the stems of the stages so far at the gains of evolution.js, so in the middle of a take's
section that take is all there is, and from the melody on each new part is heard in its section and the
last section is the whole mix. Then it is played and the caption at the playhead names the stage of the
time the playhead is at.
"""
import io
import json
import re
import wave
import zipfile

import numpy as np
from playwright.sync_api import expect

RATE = 44100
STAGES = ["original", "polished", "melody", "harmony", "drums"]
LABELS = {"original": "Your take, as recorded", "polished": "Cleaned up", "melody": "The melody on an instrument",
          "harmony": "Chords", "drums": "Drums"}
STEMS = {"original": "vocal-original.wav", "polished": "vocal-polished.wav", "melody": "melody.wav",
         "harmony": "harmony.wav", "drums": "drums.wav"}
FADE = 1.0


def project():
    notes = [{"m": [60, 64, 67, 72][i % 4], "t": i * 0.5, "d": 0.4} for i in range(16)]
    harmony = [{"m": m, "t": t, "d": 1.9} for t in (0, 2, 4, 6) for m in (48, 52, 55)]
    drums = [{"k": ["kick", "hat", "snare", "hat"][i % 4], "t": i * 0.25} for i in range(32)]
    return {"format": "tandem-project", "version": 1, "bpm": 120, "instrument": "piano", "melody_locked": True,
            "notes": notes, "drums": drums, "harmony": harmony, "harmony_instrument": "piano"}


def take(path, seconds=8.0, rate=22050):
    t = np.arange(int(rate * seconds)) / rate
    x = 0.4 * np.sin(2 * np.pi * 220 * t) * (1 + 0.3 * np.sin(2 * np.pi * 3 * t)) / 1.3
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    return path


def samples(data):
    with wave.open(io.BytesIO(data)) as w:
        assert w.getframerate() == RATE and w.getnchannels() == 1
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32767


def download(page, button):
    with page.expect_download(timeout=60_000) as info:
        page.click(button)
    with open(info.value.path(), "rb") as f:
        return f.read()


# The song lasts to its last sound: the 8 s take, the notes to 7.9 s and the drums to 7.75 + 0.25 s.
SONG = 8.0


def gain(i, sections, seconds, t):
    """evolution.js stageGain, for the stages of this test (takes first, then parts)."""
    length = seconds / len(sections)
    fade = min(FADE, length / 2)
    start = i * length
    rise = 1.0 if i == 0 else np.clip((t - start) / fade, 0, 1)
    if sections[i] in ("original", "polished") and i + 1 < len(sections):
        return np.minimum(rise, 1 - np.clip((t - (i + 1) * length) / fade, 0, 1))
    return rise


def test_the_song_turns_from_the_take_into_the_mix_section_by_section(studio, tmp_path):
    page = studio
    path = tmp_path / "song.json"
    path.write_text(json.dumps(project()))
    page.set_input_files("#projectfile", str(path))
    expect(page.locator("#status")).to_have_text("Project opened")
    page.set_input_files("#audiofile", str(take(tmp_path / "take.wav")))
    expect(page.locator("#status")).to_have_text(re.compile(r"^Recorded 8\.0s"))
    page.click("#polish")
    expect(page.locator("#polished")).to_be_enabled(timeout=30_000)

    stems_zip = zipfile.ZipFile(io.BytesIO(download(page, "#exportstems")))
    stems = {k: samples(stems_zip.read(name)) for k, name in STEMS.items()}
    mix = samples(stems_zip.read("mix.wav"))
    evolution = samples(download(page, "#exportevolution"))
    expect(page.locator("#status")).to_contain_text(
        "Exported how the song grew: " + ", then ".join(LABELS[k] for k in STAGES))

    frames = len(evolution)
    assert all(len(x) == frames for x in stems.values()), {k: len(x) for k, x in stems.items()}
    assert frames / RATE > SONG + 1  # the rendered tail after the last sound
    t = np.arange(frames) / RATE
    gains = {k: gain(i, STAGES, SONG, t) for i, k in enumerate(STAGES)}
    expected = sum(stems[k] * gains[k] for k in STAGES)
    # Every sample is the stems at their gains (each WAV is 16-bit, so a few steps of rounding).
    assert np.max(np.abs(evolution - expected)) < 3e-4

    length = SONG / len(STAGES)
    rms = lambda x: float(np.sqrt(np.mean(x ** 2)))
    for i, k in enumerate(STAGES):
        # The steady part of the section: after its crossfade, before the next one.
        a, b = int((i * length + FADE) * RATE), int((i + 1) * length * RATE) - 1
        part = slice(a, b)
        assert rms(stems[k][part]) > 0.01, f"{k} is silent in its own section"
        if k in ("original", "polished"):
            # A take's section is that take alone.
            assert np.max(np.abs(evolution[part] - stems[k][part])) < 2e-4, k
        else:
            # From the melody on, each section is every part so far; the new one is a real share of it.
            so_far = sum(stems[p] for p in STAGES[2:i + 1])
            assert np.max(np.abs(evolution[part] - so_far[part])) < 3e-4, k
            assert rms(stems[k][part]) > 0.1 * rms(evolution[part]), k
    # The last section is the finished song: Export stems' mix.
    last = slice(int(((len(STAGES) - 1) * length + FADE) * RATE), frames)
    assert np.max(np.abs(evolution[last] - mix[last])) < 3e-4


CAPTION = """() => new Promise(r => requestAnimationFrame(() => {
  const tl = document.getElementById('timeline'), c = tl.querySelector(':scope>.playhead .evocaption');
  r({t: tl.dataset.t === '' ? null : Number(tl.dataset.t), stage: tl.dataset.stage || null,
     caption: c ? c.textContent : null, line: document.querySelector('#transport .evostage').textContent});
}))"""


def test_playing_it_captions_each_stage_at_the_playhead(studio, tmp_path):
    page = studio
    path = tmp_path / "song.json"
    path.write_text(json.dumps(project()))
    page.set_input_files("#projectfile", str(path))
    expect(page.locator("#status")).to_have_text("Project opened")
    page.set_input_files("#audiofile", str(take(tmp_path / "take.wav")))
    expect(page.locator("#status")).to_have_text(re.compile(r"^Recorded 8\.0s"))
    page.click("#polish")
    expect(page.locator("#polished")).to_be_enabled(timeout=30_000)

    page.click("#evolution")
    expect(page.locator("#status")).to_contain_text("Playing how the song grew: Your take, as recorded, then Cleaned up")
    page.wait_for_function("document.getElementById('timeline').dataset.stage > ''", timeout=20_000)
    seconds, stages = SONG, ["original", "polished", "melody", "harmony", "drums"]
    seen = []
    for _ in range(400):
        s = page.evaluate(CAPTION)
        if s["t"] is None:
            break
        want = stages[min(len(stages) - 1, int(s["t"] / (seconds / len(stages))))]
        # A frame on a section's edge may round either way.
        edge = abs(s["t"] / (seconds / len(stages)) - round(s["t"] / (seconds / len(stages)))) < 0.02
        if not edge:
            assert s["stage"] == want, s
        assert s["caption"] == LABELS[s["stage"]] and s["line"] == "Now: " + LABELS[s["stage"]], s
        if not seen or seen[-1] != s["stage"]:
            seen.append(s["stage"])
        if len(seen) >= 3:
            break
        page.wait_for_timeout(50)
    assert seen == stages[:3], seen
    page.click("#stop")
    expect(page.locator("#timeline .evocaption")).to_have_count(0)
    expect(page.locator("#transport .evostage")).to_have_text("")


def test_the_guided_share_step_plays_and_downloads_how_it_grew(browser, server_url, tmp_path):
    from test_guided import guided_page
    path = tmp_path / "song.json"
    path.write_text(json.dumps(project()))
    with guided_page(browser, server_url) as page:
        page.set_input_files("#projectfile", str(path))
        page.click('#steps [data-step="share"]')
        card = page.locator('.gpanel[data-panel="share"]')
        card.locator('[data-press="evolution"]').click()
        # No take: the song grows from the melody.
        expect(card.locator(".evostage")).to_have_text("Now: The melody on an instrument", timeout=20_000)
        card.locator('[data-press="stop"]').click()
        expect(card.locator(".evostage")).to_have_text("")
        with page.expect_download(timeout=60_000) as info:
            card.locator('[data-press="exportevolution"]').click()
        assert info.value.suggested_filename == "tandem-how-it-grew.wav"
        with open(info.value.path(), "rb") as f:
            assert len(samples(f.read())) > SONG * RATE


def test_the_timeline_and_rolls_cover_a_take_longer_than_the_notes_while_it_plays(studio, tmp_path):
    # The notes and drums end by about 8 s but the take lasts 12 s, and the evolution plays to the end of the take, so
    # while it plays the Timeline and the rolls show 12 s (6 bars at 120 bpm) and the playhead is not
    # parked at the right edge for the take's last 4 s; on Stop they show the song again (review of #90).
    page = studio
    path = tmp_path / "song.json"
    path.write_text(json.dumps(project()))
    page.set_input_files("#projectfile", str(path))
    expect(page.locator("#status")).to_have_text("Project opened")
    page.set_input_files("#audiofile", str(take(tmp_path / "take.wav", seconds=12.0)))
    expect(page.locator("#status")).to_have_text(re.compile(r"^Recorded 12\.0s"))
    # The song's scale: the last drum hit is drawn to 8.05 s, so 5 bars.
    expect(page.locator("#timeline .tick")).to_have_count(5)
    first = page.locator("#melodyroll .note").first.evaluate("e => parseFloat(e.style.left)")

    page.click("#evolution")
    expect(page.locator("#status")).to_contain_text("Playing how the song grew")
    expect(page.locator("#timeline .tick")).to_have_count(6)
    page.wait_for_function("document.getElementById('timeline').dataset.t > '0.5'", timeout=20_000)
    s = page.evaluate("""() => { const tl = document.getElementById('timeline');
        return {t: parseFloat(tl.dataset.t), left: parseFloat(tl.querySelector('.playhead').style.left)} }""")
    assert abs(s["left"] - s["t"] / 12 * 97) < 1.5, s
    # The melody's second note (0.5 s) is drawn on the same 12 s scale.
    second = page.locator("#melodyroll .note").nth(1).evaluate("e => parseFloat(e.style.left)")
    assert abs((second - first) - 0.5 / 12 * 97) < 0.6, (first, second)

    page.click("#stop")
    expect(page.locator("#timeline .tick")).to_have_count(5)


def short_song(page, tmp_path, take_seconds):
    """A melody to 2 s (the song's own scale is the 8 s minimum: 4 bars) and a longer take."""
    p = project()
    p["notes"], p["harmony"], p["drums"] = p["notes"][:4], [], []
    path = tmp_path / "short.json"
    path.write_text(json.dumps(p))
    page.set_input_files("#projectfile", str(path))
    expect(page.locator("#status")).to_have_text("Project opened")
    page.set_input_files("#audiofile", str(take(tmp_path / "take.wav", seconds=take_seconds)))
    expect(page.locator("#status")).to_have_text(re.compile(r"^Recorded "))
    expect(page.locator("#timeline .tick")).to_have_count(4)


def test_the_song_scale_comes_back_when_it_ends_on_its_own(studio, tmp_path):
    page = studio
    short_song(page, tmp_path, 9.0)
    page.click("#evolution")
    expect(page.locator("#timeline .tick")).to_have_count(5)
    page.wait_for_function("document.getElementById('timeline').dataset.t > ''", timeout=20_000)
    # Nobody presses Stop: when the playhead passes the end, the rolls and the Timeline show the song again.
    page.wait_for_function("document.getElementById('timeline').dataset.t === ''", timeout=20_000)
    expect(page.locator("#timeline .tick")).to_have_count(4)


def test_a_section_marked_while_it_plays_stays_inside_the_song(studio, tmp_path):
    # The Timeline shows the 12 s evolution; a drag across its last third, past the song's own 8 s,
    # marks a loop that ends at the song's end, and the Timeline shows the song again (review of #90).
    page = studio
    short_song(page, tmp_path, 12.0)
    page.click("#evolution")
    expect(page.locator("#timeline .tick")).to_have_count(6)
    tl = page.locator("#timeline")
    tl.scroll_into_view_if_needed()
    box = tl.bounding_box()
    y = box["y"] + box["height"] / 2
    page.mouse.move(box["x"] + box["width"] * 0.97 * 0.5, y)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.97 * 0.75, y, steps=5)
    page.mouse.move(box["x"] + box["width"] * 0.97 * 0.95, y, steps=5)
    page.mouse.up()
    expect(page.locator("#timeline .tick")).to_have_count(4)
    m = re.search(r"Section ([\d.]+) to ([\d.]+) s", page.locator("#timeinfo").inner_text())
    assert m, page.locator("#timeinfo").inner_text()
    start, end = float(m.group(1)), float(m.group(2))
    assert 5.5 < start < 6.5 and end <= 8.0, (start, end)
    page.click("#stop")
