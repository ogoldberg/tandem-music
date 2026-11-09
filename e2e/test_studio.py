"""End-to-end studio flows in a real Chromium against the real FastAPI app."""
import io
import json
import re
import wave

import numpy as np
from playwright.sync_api import expect

# A4, C5, E5: what the server melody analyzer must find in the imported recording.
TONES = [(440.0, 69), (523.25, 72), (659.25, 76)]


def tone_wav(path, rate=48000, seconds=0.6, gap=0.15):
    """Mono 16-bit WAV of three sung-range tones separated by silence, at a 48 kHz device rate."""
    parts = []
    for hz, _ in TONES:
        t = np.arange(int(rate * seconds)) / rate
        env = np.minimum(1, np.minimum(t, seconds - t) / 0.02)
        parts += [0.4 * env * np.sin(2 * np.pi * hz * t), np.zeros(int(rate * gap))]
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.concatenate(parts) * 32767).astype("<i2").tobytes())
    path.write_bytes(out.getvalue())
    return path


def note_pitches(page):
    titles = page.locator("#melodyroll .note").evaluate_all("els => els.map(e => e.title)")
    return [int(re.match(r"MIDI (\d+) at", t).group(1)) for t in titles]


def count(page, which):
    return int(page.locator("#" + which).text_content().split()[0])


def download(page, button, tmp_path):
    with page.expect_download() as info:
        page.click(button)
    target = tmp_path / info.value.suggested_filename
    info.value.save_as(target)
    return target


def test_import_transcribe_edit_play_export_save_reload(studio, tmp_path):
    page = studio
    expect(page.locator("#status")).to_have_text("Ready")
    assert count(page, "notecount") == 0

    # Import a 48 kHz recording: the browser decodes it, then posts a mono WAV to the server.
    page.select_option("#mode", "melody")
    page.select_option("#transcriber", "heuristic")
    page.set_input_files("#audiofile", str(tone_wav(tmp_path / "tones-48k.wav")))
    expect(page.locator("#status")).to_have_text(re.compile(r"^Recorded 2\.\ds\."))
    expect(page.locator("#analyze")).to_be_enabled()

    with page.expect_response(lambda r: r.url.endswith("/api/analyze?mode=melody")) as analyzed:
        page.click("#analyze")
    assert analyzed.value.status == 200
    expect(page.locator("#status")).to_have_text("Transcription complete")
    assert note_pitches(page) == [m for _, m in TONES]
    assert count(page, "notecount") == 3

    # Edit a note (tapping removes it), then undo the edit.
    page.locator("#melodyroll .note").nth(1).click()
    assert note_pitches(page) == [69, 76]
    page.click("#undo")
    assert note_pitches(page) == [69, 72, 76]
    page.click("#addnote")
    assert note_pitches(page) == [69, 72, 76, 60]
    page.select_option("#drum", "snare")
    page.click("#addhit")
    assert count(page, "hitcount") == 1

    page.click("#play")
    expect(page.locator("#status")).to_have_text("Playing composition")
    page.click("#stop")
    expect(page.locator("#status")).to_have_text("Stopped")

    wav = download(page, "#exportwav", tmp_path).read_bytes()
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    with wave.open(io.BytesIO(wav)) as w:
        assert w.getframerate() == 22050 and w.getnframes() > 22050
        samples = np.frombuffer(w.readframes(w.getnframes()), "<i2")
    assert np.abs(samples).max() > 1000, "exported arrangement is silent"

    mid = download(page, "#exportmidi", tmp_path).read_bytes()
    assert mid[:4] == b"MThd" and b"MTrk" in mid

    saved_path = download(page, "#save", tmp_path)
    saved = json.loads(saved_path.read_text())
    assert saved["format"] == "tandem-project" and saved["version"] == 1
    assert [n["m"] for n in saved["notes"]] == [69, 72, 76, 60]
    assert saved["drums"] == [{"k": "snare", "t": 0.25}]

    # Clear, then open the saved project.
    page.click("#clearnotes")
    page.click("#clearhits")
    assert count(page, "notecount") == 0 and count(page, "hitcount") == 0
    page.set_input_files("#projectfile", str(saved_path))
    expect(page.locator("#status")).to_have_text("Project opened")
    assert note_pitches(page) == [69, 72, 76, 60]
    assert count(page, "hitcount") == 1

    # The localStorage draft survives a reload.
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    assert note_pitches(page) == [69, 72, 76, 60]
    assert count(page, "hitcount") == 1
