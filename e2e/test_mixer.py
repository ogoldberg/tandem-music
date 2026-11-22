"""MIX.1: the mixer in a real Chromium.

A project with a melody and drums is opened and exported as stems. Turning the drums down 6 dB scales
drums.wav by that factor and leaves the melody alone, and mix.wav is still the sum of the stems; a muted
part has no stem and is not in Export WAV; a solo leaves only the soloed part; undo takes a change back.
The mix is kept in the draft and in a saved project. While the song plays, a mute is heard at once: the
part's gain node goes to zero. The voice is left out until it is unmuted, then the take is a stem too.
"""
import io
import json
import re
import wave
import zipfile

import numpy as np
from playwright.sync_api import expect

from conftest import export_gain

RATE = 44100


def project():
    notes = [{"m": [60, 64, 67, 72][i % 4], "t": i * 0.5, "d": 0.4} for i in range(8)]
    drums = [{"k": ["kick", "hat", "snare", "hat"][i % 4], "t": i * 0.25} for i in range(16)]
    return {"format": "tandem-project", "version": 1, "bpm": 120, "instrument": "piano", "melody_locked": True,
            "notes": notes, "drums": drums}


def samples(data):
    with wave.open(io.BytesIO(data)) as w:
        assert w.getframerate() == RATE and w.getnchannels() == 1
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32767


def download(page, button):
    with page.expect_download(timeout=60_000) as info:
        page.click(button)
    with open(info.value.path(), "rb") as f:
        return f.read()


def stems(page):
    """The stems as rendered: MIX.2 levels the mix and the part stems by one gain, divided out here; the takes
    as recorded (vocal-*.wav) are not levelled."""
    z = zipfile.ZipFile(io.BytesIO(download(page, "#exportstems")))
    g = export_gain(page)
    return {name: samples(z.read(name)) / (1 if name.startswith("vocal-") else g) for name in z.namelist() if name.endswith(".wav")}


def export_wav(page):
    """Export WAV as rendered, with its levelling gain divided out, and that gain."""
    wav = samples(download(page, "#exportwav"))
    g = export_gain(page)
    return wav / g, g


def set_level(page, part, db):
    # A range input's value set the way a drag ends: input while it moves, change when let go.
    page.eval_on_selector(f"#level-{part}", """(el, v) => { el.value = String(v);
        el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); }""", db)


def open_song(page, tmp_path):
    path = tmp_path / "song.json"
    path.write_text(json.dumps(project()))
    page.set_input_files("#projectfile", str(path))
    expect(page.locator("#status")).to_have_text("Project opened")


def gain_of(page, part):
    return float(page.get_attribute(f'.mixstrip[data-mix="{part}"]', "data-gain"))


def test_export_wav_and_the_stems_peak_at_minus_one_db_however_loud_the_mix(studio, tmp_path):
    """MIX.2: however loud the mixer leaves the song, Export WAV and mix.wav peak at -1 dB below full scale,
    the stems still sum to the mix, and the status says how much it was turned up or down. (A mix past full
    scale turned down is in tests/daw.test.mjs: this song stays under it even at +6 dB.)"""
    page = studio
    open_song(page, tmp_path)
    target = round(10 ** (-1 / 20) * 32767)
    peaks = []
    for db in (6, -6):
        set_level(page, "melody", db)
        set_level(page, "drums", db)
        raw = download(page, "#exportwav")
        with wave.open(io.BytesIO(raw)) as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(int)
        assert np.max(np.abs(pcm)) == target, db
        assert np.max(np.abs(pcm)) < 32767
        peaks.append(np.max(np.abs(pcm)))
        word = "down" if export_gain(page) < 1 else "up"
        expect(page.locator("#status")).to_have_text(re.compile(r"^Exported the WAV\. Turned " + word + r" [0-9.]+ dB to peak at −1 dB"))
        z = zipfile.ZipFile(io.BytesIO(download(page, "#exportstems")))
        with wave.open(io.BytesIO(z.read("mix.wav"))) as w:
            mix = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(int)
        assert np.max(np.abs(mix)) == target, db
        parts = sum(np.frombuffer(wave.open(io.BytesIO(z.read(n))).readframes(10 ** 9), "<i2").astype(int) for n in ("melody.wav", "drums.wav"))
        assert np.max(np.abs(mix - parts)) <= 2, "the levelled stems still sum to the mix"
        assert np.max(np.abs(mix[:len(pcm)] - pcm)) <= 1, "Export WAV is mix.wav"
    assert peaks[0] == peaks[1], "as loud turned up 6 dB as turned down 6 dB"


def test_levels_mutes_and_solos_shape_the_stems_and_export_wav(studio, tmp_path):
    page = studio
    open_song(page, tmp_path)
    # Nobody mixed this song: every part at 0 dB, the voice muted (there is no take yet).
    expect(page.locator("#level-drums")).to_have_value("0")
    expect(page.locator("#mute-voice")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#solo-voice")).to_have_attribute("title", re.compile("unmute it first"))
    expect(page.locator("#mute-melody")).to_have_attribute("aria-pressed", "false")
    before = stems(page)
    assert set(before) == {"mix.wav", "melody.wav", "drums.wav"}
    assert np.max(np.abs(before["drums.wav"])) > 0.05 and np.max(np.abs(before["melody.wav"])) > 0.05

    # Drums down 6 dB: drums.wav is scaled by 10^(-6/20), the melody is unchanged, the mix is their sum.
    set_level(page, "drums", -6)
    expect(page.locator("#levelout-drums")).to_have_text("−6 dB")
    expect(page.locator("#undo")).to_have_attribute("title", re.compile("Level of drums"))
    after = stems(page)
    factor = 10 ** (-6 / 20)
    assert np.max(np.abs(after["drums.wav"] - before["drums.wav"] * factor)) < 1e-4
    assert np.max(np.abs(after["melody.wav"] - before["melody.wav"])) < 1e-4
    assert np.max(np.abs(after["mix.wav"] - (after["drums.wav"] + after["melody.wav"]))) < 1e-4
    wav, g = export_wav(page)
    assert np.max(np.abs(wav - after["mix.wav"])) < 1e-4 / min(g, 1)
    # MIX.2: Export WAV is levelled to peak at -1 dB below full scale.
    assert abs(np.max(np.abs(wav)) * g - 10 ** (-1 / 20)) < 1e-4

    # A muted melody is silent: no melody stem, and Export WAV is the drums alone.
    page.click("#mute-melody")
    expect(page.locator("#mute-melody")).to_have_attribute("aria-pressed", "true")
    assert gain_of(page, "melody") == 0
    muted = stems(page)
    assert set(muted) == {"mix.wav", "drums.wav"}
    wav, g = export_wav(page)
    assert np.max(np.abs(wav - after["drums.wav"])) < 1e-4 / min(g, 1)

    # Undo brings the melody back; a solo on the melody leaves only the melody.
    page.click("#undo")
    expect(page.locator("#mute-melody")).to_have_attribute("aria-pressed", "false")
    page.click("#solo-melody")
    expect(page.locator("#solo-melody")).to_have_attribute("aria-pressed", "true")
    assert gain_of(page, "drums") == 0 and gain_of(page, "melody") == 1
    solo = stems(page)
    assert set(solo) == {"mix.wav", "melody.wav"}
    assert np.max(np.abs(solo["mix.wav"] - before["melody.wav"])) < 1e-4

    # The mix is kept in the saved project and in the draft.
    saved = json.loads(download(page, "#save"))
    assert saved["mix"] == {"drums": {"level": -6}, "melody": {"solo": True}}
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent === '8 notes'")
    expect(page.locator("#solo-melody")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#level-drums")).to_have_value("-6")
    expect(page.locator("#levelout-drums")).to_have_text("−6 dB")


def test_a_mute_while_playing_is_heard_at_once(studio, tmp_path):
    page = studio
    open_song(page, tmp_path)
    page.click("#play")
    page.wait_for_function("(document.getElementById('timeline').dataset.mix || '').length > 0")
    live = json.loads(page.get_attribute("#timeline", "data-mix"))
    assert live["melody"] == 1 and live["drums"] == 1 and live["voice"] == 0
    assert abs(live["harmony"] - 0.6) < 1e-3  # the harmony's own level under the melody (HARMONY_GAIN)
    page.click("#mute-drums")
    page.wait_for_function("JSON.parse(document.getElementById('timeline').dataset.mix || '{}').drums === 0")
    set_level(page, "melody", -12)
    page.wait_for_function("Math.abs(JSON.parse(document.getElementById('timeline').dataset.mix || '{}').melody - 0.251) < 0.002")
    page.click("#stop")


def test_the_voice_joins_the_mix_when_unmuted(studio, tmp_path):
    page = studio
    open_song(page, tmp_path)
    rate = 22050
    t = np.arange(int(rate * 6.0)) / rate
    with wave.open(str(tmp_path / "take.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes((0.4 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2").tobytes())
    page.set_input_files("#audiofile", str(tmp_path / "take.wav"))
    expect(page.locator("#status")).to_have_text(re.compile(r"^Recorded 6\.0s"))

    # Muted by default: the take is a raw vocal stem but not a part of the mix.
    first = stems(page)
    assert "voice.wav" not in first and "vocal-original.wav" in first
    page.click("#mute-voice")
    expect(page.locator("#mute-voice")).to_have_attribute("aria-pressed", "false")
    expect(page.locator("#solo-voice")).to_have_attribute("title", "Solo: hear only the soloed parts")
    set_level(page, "voice", -6)
    mixed = stems(page)
    factor = 10 ** (-6 / 20)
    voice, raw = mixed["voice.wav"], mixed["vocal-original.wav"]
    assert len(voice) == len(raw) == len(mixed["mix.wav"])
    assert np.max(np.abs(voice - raw * factor)) < 1e-4
    assert np.max(np.abs(mixed["mix.wav"] - (voice + mixed["melody.wav"] + mixed["drums.wav"]))) < 1e-4
