"""CHAT.1a: instrument lines in a real Chromium.

A project file with a melody and a guitar line opens with the line kept: Play plays it on its own bus at
its mixer level, the stems have it as line-1.wav (and mix.wav is the melody plus the line), the MIDI file
has a Guitar track on the line's channel with the guitar's program, MusicXML has it as a part, and the
saved project keeps it and names it in `uses`. Quantize moves the line with the melody, and Undo takes
it back. A file whose line is invalid is refused. No control adds a line yet (CHAT.1b).
"""
import io
import json
import zipfile

import mido
import numpy as np
from playwright.sync_api import expect

from conftest import export_gain
from test_mixer import download, samples

GUITAR = 24  # General MIDI program 25, Acoustic Guitar (nylon), daw.js PROGRAMS.guitar
LINE_CHANNEL = 3  # lines.js LINE_CHANNELS[0]


def project():
    notes = [{"m": [60, 64, 67, 72][i % 4], "t": i * 0.5, "d": 0.4} for i in range(8)]
    line = [{"m": 76, "t": 0.27, "d": 0.3}, {"m": 79, "t": 1.02, "d": 0.3}, {"m": 81, "t": 2.0, "d": 0.6}]
    return {"format": "tandem-project", "version": 1, "bpm": 120, "instrument": "piano", "melody_locked": True,
            "notes": notes, "drums": [], "uses": ["lines"],
            "lines": [{"id": "g1", "name": "Guitar", "instrument": "guitar", "notes": line}],
            "mix": {"line-g1": {"level": -6}}}


def open_song(page, tmp_path, p=None, name="song.json"):
    path = tmp_path / name
    path.write_text(json.dumps(p or project()))
    page.set_input_files("#projectfile", str(path))


def note_ons(data, channel):
    out = []
    for track in mido.MidiFile(file=io.BytesIO(data)).tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "note_on" and msg.velocity > 0 and msg.channel == channel:
                out.append((tick, msg.note))
    return out


def saved(page, tmp_path):
    with page.expect_download() as info:
        page.click("#save")
    target = tmp_path / info.value.suggested_filename
    info.value.save_as(target)
    return json.loads(target.read_text())


def test_a_line_plays_exports_saves_and_undoes_with_the_song(studio, tmp_path):
    page = studio
    open_song(page, tmp_path)
    expect(page.locator("#status")).to_have_text("Project opened")

    # Play: the line has a bus of its own at its mixer level (-6 dB), beside the melody's.
    page.click("#play")
    page.wait_for_function("(document.getElementById('timeline').dataset.mix || '').includes('line-g1')")
    live = json.loads(page.get_attribute("#timeline", "data-mix"))
    assert abs(live["line-g1"] - 10 ** (-6 / 20)) < 2e-3 and live["melody"] == 1
    page.click("#stop")

    # The stems: line-1.wav is the guitar, heard; mix.wav is the melody plus the line.
    z = zipfile.ZipFile(io.BytesIO(download(page, "#exportstems")))
    g = export_gain(page)
    assert sorted(n for n in z.namelist() if n.endswith(".wav")) == ["line-1.wav", "melody.wav", "mix.wav"]
    stem = {n: samples(z.read(n)) / g for n in ("line-1.wav", "melody.wav", "mix.wav")}
    assert np.abs(stem["line-1.wav"]).max() > 0.01, "the line's stem is silent"
    # The line starts at its first note (0.27 s): nothing before it.
    assert np.abs(stem["line-1.wav"][: int(0.26 * 44100)]).max() < 1e-4
    assert np.abs(stem["mix.wav"] - stem["melody.wav"] - stem["line-1.wav"]).max() < 3 / 32767 / g + 1e-6

    # The MIDI file: a Guitar track on the line's channel with the guitar's program.
    data = download(page, "#exportmidi")
    mid = mido.MidiFile(file=io.BytesIO(data))
    assert [t.name for t in mid.tracks] == ["Tandem", "Melody", "Guitar"]
    programs = [(m.channel, m.program) for m in mid.tracks[2] if m.type == "program_change"]
    assert programs == [(LINE_CHANNEL, GUITAR)]
    beat = mid.ticks_per_beat  # 120 bpm: a beat is half a second
    assert note_ons(data, LINE_CHANNEL) == [(round(0.27 * 2 * beat), 76), (round(1.02 * 2 * beat), 79), (4 * beat, 81)]

    # MusicXML: the line is a part named Guitar.
    xml = download(page, "#exportmusicxml").decode()
    assert "<part-name>Guitar</part-name>" in xml

    # The saved project keeps the line and says it needs lines.
    out = saved(page, tmp_path)
    assert out["lines"] == project()["lines"] and out["uses"] == ["lines"]
    assert out["mix"] == {"line-g1": {"level": -6}}

    # Quantize moves the line with the melody, as one edit; Undo puts it back.
    page.click("#quantize")
    expect(page.locator("#status")).to_contain_text("Quantize to")
    assert [n["t"] for n in saved(page, tmp_path)["lines"][0]["notes"]] == [0.25, 1.0, 2.0]
    page.click("#undo")
    assert [n["t"] for n in saved(page, tmp_path)["lines"][0]["notes"]] == [0.27, 1.02, 2.0]

    # The draft keeps the line across a reload.
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    assert saved(page, tmp_path)["lines"] == project()["lines"]


def test_a_version_keeps_its_lines_and_restoring_one_without_lines_clears_them(studio, tmp_path):
    page = studio
    plain = project()
    del plain["lines"], plain["mix"], plain["uses"]
    open_song(page, tmp_path, plain, "plain.json")
    expect(page.locator("#status")).to_have_text("Project opened")
    page.fill("#versionname", "Plain")
    page.click("#saveversion")
    expect(page.locator("#status")).to_have_text("Saved version: Plain")
    open_song(page, tmp_path)
    expect(page.locator("#status")).to_have_text("Project opened")
    page.fill("#versionname", "With guitar")
    page.click("#saveversion")
    expect(page.locator("#status")).to_have_text("Saved version: With guitar")

    # Restoring the version without lines drops the open song's line.
    page.click('#versionlist button[title="Restore Plain"]')
    expect(page.locator("#status")).to_contain_text("Restored version: Plain")
    assert saved(page, tmp_path).get("lines") is None
    # Restoring the version with a line brings it back, with its mixer level.
    page.click('#versionlist button[title="Restore With guitar"]')
    expect(page.locator("#status")).to_contain_text("Restored version: With guitar")
    out = saved(page, tmp_path)
    assert out["lines"] == project()["lines"] and out["mix"] == {"line-g1": {"level": -6}}


def test_a_file_with_an_invalid_line_is_refused(studio, tmp_path):
    page = studio
    bad = project()
    bad["lines"][0]["instrument"] = "kazoo"
    open_song(page, tmp_path, bad, "bad.json")
    expect(page.locator("#status")).to_contain_text("Unsupported line instrument: kazoo")
    assert saved(page, tmp_path).get("lines") is None
