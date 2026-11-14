"""HARM.3: Sing it in my voice moves the take onto the harmony voice's notes with WORLD on the device.

A take of four sung notes is imported, the project gives it the matching melody and a harmony voice a
third above three of them (none over the third note), and Sing it in my voice runs the WebAssembly
WORLD build in the worker. The sung harmony is measured in the stems: at the harmony pitches where the
harmony voice has a note, silent everywhere else, and in place of the harmony voice's instrument until
it is muted. Undo, redo and a reload keep it; editing the line says it has changed since it was sung.
"""
import io
import json
import wave
import zipfile

import numpy as np
from playwright.sync_api import expect

from test_studio import download, import_recording, wait_for_draft_audio

RATE = 22050
MELODY = [60, 64, 67, 72]
HARMONY = {0: 64, 1: 67, 3: 76}  # a third above every note but the third
NOTE, GAP = 0.8, 0.2


def sung_take(path):
    t = np.arange(int(RATE * NOTE)) / RATE
    env = np.minimum(1, np.minimum(t, NOTE - t) / 0.02)
    parts = [np.zeros(int(RATE * GAP))]
    for m in MELODY:
        hz = 440.0 * 2 ** ((m - 69) / 12)
        voice = sum(0.7 ** k / k * np.sin(2 * np.pi * k * hz * t) for k in range(1, 7))
        parts += [0.3 * env * voice / np.max(np.abs(voice)), np.zeros(int(RATE * GAP))]
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes(np.round(np.concatenate(parts) * 32767).astype("<i2").tobytes())
    path.write_bytes(out.getvalue())
    return path


def start(i):
    return GAP + i * (NOTE + GAP)


def project_file(path):
    notes = [{"m": m, "t": round(start(i), 3), "d": NOTE} for i, m in enumerate(MELODY)]
    voice2 = [{"m": m, "t": round(start(i), 3), "d": NOTE} for i, m in HARMONY.items()]
    path.write_text(json.dumps({"format": "tandem-project", "version": 1, "bpm": 100, "instrument": "piano",
                                "notes": notes, "drums": [], "voice2": voice2, "voice2_instrument": "flute"}))
    return path


def read_wav(data):
    with wave.open(io.BytesIO(data)) as w:
        rate = w.getframerate()
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(float) / 32767, rate


def stems(page, tmp_path, name):
    target = download(page, "#exportstems", tmp_path)
    renamed = target.with_name(name)
    target.rename(renamed)
    with zipfile.ZipFile(renamed) as z:
        return {n: z.read(n) for n in z.namelist()}


def pitch_cents(x, rate, a, b, m):
    mid = x[int(a * rate):int(b * rate)]
    mid = mid * np.hanning(len(mid))
    spectrum = np.abs(np.fft.rfft(mid, 16 * len(mid)))
    hz = np.argmax(spectrum) * rate / (16 * len(mid))
    return 1200 * np.log2(hz / (440.0 * 2 ** ((m - 69) / 12)))


def rms(x, rate, a, b):
    seg = x[int(a * rate):int(b * rate)]
    return float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0


def test_the_take_is_sung_on_the_harmony_voice_on_the_device(studio, tmp_path):
    page = studio
    expect(page.locator("#singvoice2")).to_be_disabled()
    import_recording(page, sung_take(tmp_path / "take.wav"))
    page.set_input_files("#projectfile", str(project_file(tmp_path / "song.json")))
    expect(page.locator("#voice2count")).to_have_text("3 notes")
    expect(page.locator("#tuneengine")).to_have_value("device")
    expect(page.locator("#singvoice2")).to_be_enabled()

    page.click("#singvoice2")
    expect(page.locator("#status")).to_contain_text("Sang the harmony voice in your voice on this device", timeout=120_000)
    expect(page.locator("#voice2sunginfo")).to_contain_text("in place of the instrument")
    expect(page.locator("#playvoice2sung")).to_be_enabled()
    expect(page.locator("#singvoice2")).to_have_text("Sing it again in my voice")

    files = stems(page, tmp_path, "sung.zip")
    assert "harmony-voice-sung.wav" in files
    assert "harmony-voice.wav" not in files, "the instrument still plays the harmony voice under the sung one"
    x, rate = read_wav(files["harmony-voice-sung.wav"])
    loud = max(rms(x, rate, start(i) + 0.2, start(i) + 0.6) for i in HARMONY)
    assert loud > 0.02, f"the sung harmony is almost silent ({loud})"
    for i, m in HARMONY.items():
        cents = pitch_cents(x, rate, start(i) + 0.2, start(i) + 0.6, m)
        assert abs(cents) <= 20, f"harmony note {i} ({m}) is {cents:.1f} cents off"
    # Silent where the harmony voice has no note: over the third sung note and in the gaps.
    assert rms(x, rate, start(2) + 0.05, start(2) + NOTE - 0.05) < loud * 1e-3
    for i in range(len(MELODY)):
        assert rms(x, rate, start(i) + NOTE + 0.03, start(i) + NOTE + GAP - 0.03) < loud * 1e-3

    # Mute brings back the instrument; the stem of the sung harmony is then left out of the mix.
    page.check("#voice2sungmute")
    expect(page.locator("#voice2sunginfo")).to_contain_text("muted: the instrument plays the harmony voice")
    files = stems(page, tmp_path, "muted.zip")
    assert "harmony-voice.wav" in files and "harmony-voice-sung.wav" not in files

    # Undo the mute, then the singing; redo brings it back with its audio.
    page.click("#undo")
    expect(page.locator("#voice2sungmute")).not_to_be_checked()
    page.click("#undo")
    expect(page.locator("#playvoice2sung")).to_be_disabled()
    expect(page.locator("#singvoice2")).to_have_text("Sing it in my voice")
    page.click("#redo")
    expect(page.locator("#playvoice2sung")).to_be_enabled()
    links = wait_for_draft_audio(page, ["original", "voice2_sung"])

    # A reload keeps it with its recording.
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    expect(page.locator("#voice2sunginfo")).to_contain_text("in place of the instrument")
    expect(page.locator("#playvoice2sung")).to_be_enabled()
    assert wait_for_draft_audio(page, ["original", "voice2_sung"]) == links
    files = stems(page, tmp_path, "reloaded.zip")
    assert "harmony-voice-sung.wav" in files and "harmony-voice.wav" not in files

    # Editing the line after it was sung is pointed out.
    page.click("#voice2all")
    page.click("#voice2semiup")
    expect(page.locator("#voice2sunginfo")).to_contain_text("has changed since it was sung")
    page.click("#removevoice2sung")
    expect(page.locator("#playvoice2sung")).to_be_disabled()
    files = stems(page, tmp_path, "removed.zip")
    assert "harmony-voice.wav" in files and "harmony-voice-sung.wav" not in files
