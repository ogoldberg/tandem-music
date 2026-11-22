"""SONG.1: song sections in a real Chromium: mark a chorus on the Timeline, repeat it, undo, move and delete.
GROW.3: with a take, the voice is placed with the notes: it plays the repeated chorus twice, in Play and every export,
and no recording is written or changed.

The example project is at 100 bpm (a beat is 0.6 s): 8 melody notes 0.45 s apart and 16 drum hits 0.225 s apart.
A drag from 1.2 s to 2.4 s marks beats 3 and 4 (snapped to the beat), holding the melody notes at 1.35, 1.8
and 2.25 s and the five drum hits from 1.35 to 2.25 s.
"""
import io
import json
import re
import wave
import zipfile

import numpy as np
from playwright.sync_api import expect

from test_playhead import drag_loop
from test_studio import IDB_DRAFT, wait_for_draft_audio, wait_until

RATE = 44100


def sections(page):
    raw = page.locator("#sections").get_attribute("data-sections")
    return json.loads(raw) if raw else []


def mark(page, name, a, b):
    drag_loop(page, a, b)
    page.select_option("#sectionname", name)
    page.click("#marksection")


def test_a_chorus_is_marked_repeated_undone_moved_and_deleted_across_every_note_part(studio):
    page = studio
    page.click("#demo")
    expect(page.locator("#sections")).to_be_hidden()
    expect(page.locator("#marksection")).to_be_disabled()

    mark(page, "Verse", 0, 1.2)
    mark(page, "Chorus", 1.2, 2.4)
    assert sections(page) == [{"name": "Verse", "from": 0, "to": 1.2}, {"name": "Chorus", "from": 1.2, "to": 2.4}]
    expect(page.locator(".secblock")).to_have_text(["Verse", "Chorus"])
    # The section just marked is chosen, so its tools are offered.
    expect(page.locator('.secblock[data-section="1"]')).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#sectionedit")).to_be_visible()
    expect(page.locator("#sectionlater")).to_be_disabled()

    page.click("#sectionrepeat")
    expect(page.locator("#notecount")).to_have_text("11 notes")
    expect(page.locator("#hitcount")).to_have_text("21 hits")
    assert [s["name"] for s in sections(page)] == ["Verse", "Chorus", "Chorus"]
    assert sections(page)[2] == {"name": "Chorus", "from": 2.4, "to": 3.6}
    expect(page.locator("#status")).to_contain_text("Repeat Chorus")
    # The copy is chosen and marked on the Timeline, so Play loops it.
    expect(page.locator('.secblock[data-section="2"]')).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#timeinfo")).to_contain_text("Section 2.4 to 3.6 s")

    page.click("#undo")
    expect(page.locator("#notecount")).to_have_text("8 notes")
    expect(page.locator("#hitcount")).to_have_text("16 hits")
    assert [s["name"] for s in sections(page)] == ["Verse", "Chorus"]
    expect(page.locator("#sectionedit")).to_be_hidden()
    page.click("#redo")
    expect(page.locator("#notecount")).to_have_text("11 notes")

    # Move the verse after the first chorus: the chorus's first note (1.35 s) now starts the song at 0.15 s.
    page.click('.secblock[data-section="0"]')
    expect(page.locator("#sectionearlier")).to_be_disabled()
    page.click("#sectionlater")
    assert [s["name"] for s in sections(page)] == ["Chorus", "Verse", "Chorus"]
    first = page.evaluate("() => Math.min(...JSON.parse(document.getElementById('sections').dataset.sections).map(s => s.from))")
    assert first == 0
    expect(page.locator("#notecount")).to_have_text("11 notes")

    # Delete the last chorus: its three notes and five hits go.
    page.click('.secblock[data-section="2"]')
    page.click("#sectiondelete")
    expect(page.locator("#notecount")).to_have_text("8 notes")
    expect(page.locator("#hitcount")).to_have_text("16 hits")
    assert [s["name"] for s in sections(page)] == ["Chorus", "Verse"]

    # The sections are part of the draft: they are back after a reload.
    wait_until(page, """async () => { const db = await new Promise(r => { const q = indexedDB.open('tandem'); q.onsuccess = () => r(q.result) });
        const d = await new Promise(r => { const q = db.transaction('kv').objectStore('kv').get('draft'); q.onsuccess = () => r(q.result) });
        db.close(); return !!(d && d.sections && d.sections.length === 2) }""", "the draft keeps the sections")
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    expect(page.locator(".secblock")).to_have_text(["Chorus", "Verse"])
    expect(page.locator("#notecount")).to_have_text("8 notes")


def test_a_section_cannot_overlap_another(studio):
    page = studio
    page.click("#demo")
    mark(page, "Chorus", 1.2, 2.4)
    mark(page, "Bridge", 1.8, 3.0)
    expect(page.locator("#status")).to_contain_text("overlaps Chorus")
    assert [s["name"] for s in sections(page)] == ["Chorus"]


def test_a_version_restores_its_sections_and_one_without_sections_clears_them(studio):
    page = studio
    page.click("#demo")
    page.fill("#versionname", "No sections")
    page.click("#saveversion")
    expect(page.locator("#status")).to_have_text("Saved version: No sections")
    mark(page, "Chorus", 1.2, 2.4)
    page.fill("#versionname", "With chorus")
    page.click("#saveversion")
    expect(page.locator("#status")).to_have_text("Saved version: With chorus")

    page.click("#versionlist .version:has-text('No sections') >> text=Restore")
    expect(page.locator("#status")).to_contain_text("Restored version: No sections")
    expect(page.locator("#sections")).to_be_hidden()
    assert sections(page) == []

    page.click("#versionlist .version:has-text('With chorus') >> text=Restore")
    expect(page.locator("#status")).to_contain_text("Restored version: With chorus")
    assert sections(page) == [{"name": "Chorus", "from": 1.2, "to": 2.4}]


def ramp_wav(path, seconds=4.0):
    """A 440 Hz tone whose level rises steadily from 0.05 to 0.45, so its level says which second of the take is playing."""
    t = np.arange(int(RATE * seconds)) / RATE
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes(((0.05 + 0.4 * t / seconds) * np.sin(2 * np.pi * 440 * t) * 32767).astype("<i2").tobytes())
    return path


def take_level(take_seconds, seconds=4.0):
    return 0.05 + 0.4 * take_seconds / seconds


# Keeps every buffer Play schedules, so its samples can be read afterwards.
WATCH_BUFFERS = """() => {
  window.bufs = [];
  const start = AudioBufferSourceNode.prototype.start;
  AudioBufferSourceNode.prototype.start = function (...args) { if (this.buffer) window.bufs.push(this.buffer); return start.apply(this, args); };
}"""


def scheduled_voice(page, seconds):
    """Press Play from the start, not looping, and return the level of the scheduled buffer `seconds` long at a few song times."""
    if page.locator("#clearloop").is_enabled():
        page.click("#clearloop")
    page.evaluate("window.bufs = []")
    page.click("#play")
    expect(page.locator("#status")).to_have_text(re.compile("^Playing composition"))
    page.click("#stop")
    return page.evaluate("""seconds => { const voice = window.bufs.filter(b => Math.abs(b.duration - seconds) < 0.005);
      return {count: voice.length, at: [1.0, 1.8, 3.0, 4.5].map(t => { const x = voice[0].getChannelData(0), r = voice[0].sampleRate;
        let peak = 0; for (let i = Math.floor((t - 0.02) * r); i < (t + 0.02) * r; i++) peak = Math.max(peak, Math.abs(x[i])); return peak; })} }""", seconds)


# Every recording in the Origin Private File System by name, with the SHA-256 of what it holds.
OPFS_HASHES = """async () => { const out = {}; const dir = await (await navigator.storage.getDirectory()).getDirectoryHandle('recordings');
  for await (const e of dir.values()) { const data = await (await e.getFile()).arrayBuffer();
    out[e.name] = [...new Uint8Array(await crypto.subtle.digest('SHA-256', data))].map(b => b.toString(16).padStart(2, '0')).join(''); }
  return out; }"""


def stem_files(page):
    with page.expect_download(timeout=60_000) as info:
        page.click("#exportstems")
    z = zipfile.ZipFile(info.value.path())
    out = {}
    for n in z.namelist():
        if n.endswith(".wav"):
            with wave.open(io.BytesIO(z.read(n))) as w:
                assert w.getframerate() == RATE
                out[n] = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32768
    return out


def level_at(x, t):
    return float(np.max(np.abs(x[int((t - 0.02) * RATE):int((t + 0.02) * RATE)])))


def test_a_repeated_chorus_repeats_the_voice_in_play_and_the_stems_and_no_recording_changes(studio, tmp_path):
    page = studio
    page.evaluate(WATCH_BUFFERS)
    page.click("#demo")
    page.set_input_files("#audiofile", str(ramp_wav(tmp_path / "ramp.wav")))
    expect(page.locator("#status")).to_have_text(re.compile(r"^Recorded 4\.0s"))
    wait_for_draft_audio(page, ["original"])
    files = page.evaluate(OPFS_HASHES)
    assert files and all(name.startswith(sha) for name, sha in files.items()), files
    # Before any section edit the voice plays whole from zero, as before GROW.3.
    assert "placed" not in page.evaluate(IDB_DRAFT) or page.evaluate(IDB_DRAFT)["placed"] is None
    expect(page.locator("#lanefill-voice")).to_be_hidden()
    assert scheduled_voice(page, 4.0)["count"] == 1

    mark(page, "Chorus", 1.2, 2.4)
    page.click("#sectionrepeat")
    expect(page.locator("#status")).to_have_text("Repeat Chorus. The recordings play with it")
    expect(page.locator("#sectioninfo")).not_to_contain_text("stay where they are")
    clips = [{"from": 0, "to": 2.4, "at": 0}, {"from": 1.2, "to": 4, "at": 2.4}]
    want = json.dumps({"voice": clips}, separators=(",", ":"))
    wait_until(page, f"async () => JSON.stringify((await ({IDB_DRAFT})()).placed) === {json.dumps(want)}", "the draft keeps where the voice plays")
    expect(page.locator("#lanefill-voice")).to_be_visible()
    assert json.loads(page.get_attribute("#lanefill-voice", "data-clips")) == clips
    expect(page.locator("#lanefill-voice span")).to_have_count(2)

    # Play schedules the voice laid out over 5.2 s: the chorus (take 1.2..2.4) at 1.2 s and again at 2.4 s, the rest after.
    got = scheduled_voice(page, 5.2)
    assert got["count"] == 1
    assert abs(got["at"][0] - take_level(1.0)) < 0.01
    assert abs(got["at"][1] - take_level(1.8)) < 0.01 and abs(got["at"][2] - take_level(1.8)) < 0.01
    assert abs(got["at"][3] - take_level(3.3)) < 0.01

    # Unmuted, the voice is a stem laid out the same way, and the stems still sum to the mix.
    page.click("#mute-voice")
    expect(page.locator("#mute-voice")).to_have_attribute("aria-pressed", "false")
    stems = stem_files(page)
    voice, original = stems["voice.wav"], stems["vocal-original.wav"]
    assert len(voice) >= 5.2 * RATE
    for x in (voice, original):
        assert abs(level_at(x, 3.0) - take_level(1.8)) < 0.01 and abs(level_at(x, 4.5) - take_level(3.3)) < 0.01
    parts = [x for n, x in stems.items() if n in ("voice.wav", "melody.wav", "drums.wav")]
    assert np.max(np.abs(stems["mix.wav"] - sum(parts))) < 4 / 32768

    # Undo takes the clips off with the notes, Redo brings them back; a move and a delete carry them too.
    page.click("#undo")  # the unmute
    page.click("#undo")
    expect(page.locator("#notecount")).to_have_text("8 notes")
    expect(page.locator("#lanefill-voice")).to_be_hidden()
    assert scheduled_voice(page, 4.0)["count"] == 1
    page.click("#redo")
    expect(page.locator("#notecount")).to_have_text("11 notes")
    assert json.loads(page.get_attribute("#lanefill-voice", "data-clips")) == clips
    page.click('.secblock[data-section="1"]')
    page.click("#sectiondelete")
    expect(page.locator("#notecount")).to_have_text("8 notes")
    expect(page.locator("#lanefill-voice")).to_be_hidden()
    assert scheduled_voice(page, 4.0)["count"] == 1
    # No section edit wrote or changed a recording.
    assert page.evaluate(OPFS_HASHES) == files
