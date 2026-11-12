"""GEN.2: Generate band in the Mac app's window (Chromium stands in for WKWebView).

MusicGen-Melody is 6.2 GB, too large for CI, so these tests run the studio against a stand-in
model (a fixed tone in place of the generated band) and check what the window does with the band:
what it sends, where it puts the audio, how it plays, saves, undoes and exports. The real model's
melody-following is measured in tests/test_band.py (TANDEM_TEST_BAND=1).
"""
import dataclasses
import hashlib
import io
import json
import os
import re
import threading
import wave
import zipfile

import numpy as np
import pytest
from playwright.sync_api import expect

import tandem_desktop as desk
from tandem_desktop import band, models
from tandem_desktop.ai_keys import AISettings
from tandem_desktop.projects import ProjectFolders
from test_desktop import Dialogs, MemoryKeys, free_port, open_app
from test_studio import IDB_DRAFT, IDB_GET, wait_for_draft_audio

TONE = 0.3  # the stand-in band: a 220 Hz tone at this level


def stand_in_runtime(home):
    """A runtime whose musicgen-melody files are installed (a stand-in file pinned in their place)."""
    body = b"stand-in weights"
    spec = models.ModelSpec(band.MODEL_ID, models.MUSICGEN_MELODY.label,
                            (models.ModelFile("config.json", "https://example.test/c", hashlib.sha256(body).hexdigest(), len(body)),),
                            packages=())
    runtime = models.ModelRuntime(home, [spec])
    folder = runtime.store.folder(spec)
    folder.mkdir(parents=True)
    (folder / "config.json").write_bytes(body)
    st = (folder / "config.json").stat()
    (folder / models.RECORD).write_text(json.dumps({"config.json": {"sha256": spec.files[0].sha256, "size": st.st_size, "mtime_ns": st.st_mtime_ns}}))
    return runtime


@pytest.fixture
def app(monkeypatch, tmp_path):
    made = []
    seen = []

    def generate(loaded, x, rate, text, seconds, job=None):
        seen.append({"text": text, "seconds": seconds, "melody": np.asarray(x), "rate": rate})
        job.report(0.5, "Playing your melody with the band")
        t = np.arange(int(round(seconds * band.RATE))) / band.RATE
        return (TONE * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    monkeypatch.setattr(band, "load_musicgen", lambda folder, on=None: ("model", "tokenizer"))
    monkeypatch.setattr(band, "generate", generate)

    def start(runtime=None):
        for key in list(os.environ):
            if key.startswith(("TANDEM_", "VERCEL", "UPSTASH_")):
                monkeypatch.delenv(key)
        runtime = runtime or stand_in_runtime(tmp_path / "home")
        port, secret = free_port(), desk.new_launch_secret()
        handle = desk.start_server(port, secret, desktop_api=ProjectFolders(Dialogs()),
                                   ai_settings=AISettings(tmp_path / "ai", MemoryKeys()), models=runtime, band=band.Band(runtime))
        made.append(handle)
        return {"url": f"http://127.0.0.1:{port}", "port": port, "secret": secret, "runtime": runtime, "seen": seen}
    yield start
    for server, thread in made:
        desk.stop_server(server, thread)


def samples_of(data):
    with wave.open(io.BytesIO(data)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768, w.getframerate()


def stems(page):
    with page.expect_download() as info:
        page.click("#exportstems")
    z = zipfile.ZipFile(info.value.path())
    return {n: z.read(n) for n in z.namelist()}


def draft(page):
    return page.evaluate(IDB_DRAFT)


# Records every scheduled Web Audio source: its start time and, for a buffer, its length and peak.
WATCH_STARTS = """() => {
  window.starts = [];
  // AudioBufferSourceNode has a start of its own, so both are watched.
  for (const proto of [AudioScheduledSourceNode.prototype, AudioBufferSourceNode.prototype]) {
    const start = proto.start;
    proto.start = function (when = 0, ...rest) {
      const b = this.buffer, d = b ? b.getChannelData(0) : null;
      let peak = 0;
      if (d) for (let i = 0; i < d.length; i++) peak = Math.max(peak, Math.abs(d[i]));
      window.starts.push({when, seconds: b ? b.duration : null, peak, now: this.context.currentTime});
      return start.call(this, when, ...rest);
    };
  }
}"""


def played(page):
    """Press Play, wait for it to start and return (band starts, the earliest other start, the first part event's time)."""
    page.evaluate("window.starts = []")
    page.click("#play")
    expect(page.locator("#status")).to_have_text(re.compile("^Playing composition"))
    starts = page.evaluate("window.starts")
    page.click("#stop")
    bands = [s for s in starts if s["seconds"] and abs(s["seconds"] - 4) < 0.05 and abs(s["peak"] - TONE) < 0.01]
    others = [s["when"] for s in starts if s not in bands]
    d = draft(page)
    first = min(n["t"] for n in d["notes"] + d["drums"] + d["harmony"])
    return bands, min(others), first


def test_the_band_is_offered_only_in_the_mac_app(studio):
    expect(studio.locator("#bandtrack")).to_be_hidden()


def test_a_band_follows_the_melody_and_is_kept_played_undone_and_exported(page, app):
    desktop = app()
    problems = open_app(page, desktop)
    expect(page.locator("#bandtrack")).to_be_visible()
    expect(page.locator("#playbandtrack")).to_be_disabled()
    page.click("#demo")
    page.fill("#bandstyle", "")
    page.click("#genband")
    expect(page.locator("#bandstatus")).to_have_text(re.compile("Describe the band's style first"))
    page.fill("#bandstyle", "lo-fi band with brushed drums")
    page.select_option("#bandfollows", "melody")
    page.click("#genband")
    expect(page.locator("#bandstatus")).to_have_text(re.compile(r"^Generated 4 s of band"), timeout=60_000)
    expect(page.locator("#genband")).to_have_text("Generate band")
    # The window sent the melody notes rendered from zero, with the tempo and the melody's key in the prompt.
    (sent,) = desktop["seen"]
    assert sent["text"] == "lo-fi band with brushed drums, 100 bpm, in C major"
    assert sent["seconds"] == pytest.approx(4.0) and sent["rate"] == 44100
    onset = np.argmax(np.abs(sent["melody"]) > 0.01) / sent["rate"]
    assert onset < 0.02, "the melody starts at zero, as the band will"
    expect(page.locator("#bandinfo")).to_have_text(re.compile(
        r'^Generated audio: MusicGen-Melody played "lo-fi band with brushed drums" following the melody notes, 4 s from the start\. '
        r"MusicGen-Melody weights are CC-BY-NC 4\.0"))
    b = draft(page)["band"]
    assert {k: b[k] for k in ("style", "follows", "seconds", "muted", "model")} == {
        "style": "lo-fi band with brushed drums", "follows": "melody", "seconds": 4, "muted": False, "model": "musicgen-melody"}
    wait_for_draft_audio(page, ["band"])
    # Play schedules the band once, from the project's zero: where the parts' zero is.
    page.evaluate(WATCH_STARTS)
    bands, earliest, first = played(page)
    assert len(bands) == 1, bands
    assert bands[0]["when"] == pytest.approx(earliest - first, abs=1e-3)
    assert bands[0]["when"] > bands[0]["now"]
    # The band is a part: its stem starts at zero, at the level it plays, and it is in the mix.
    files = stems(page)
    assert {"mix.wav", "melody.wav", "drums.wav", "band.wav"} <= set(files), list(files)
    x, rate = samples_of(files["band.wav"])
    assert rate == 44100 and abs(np.max(np.abs(x[:rate])) - 0.8 * TONE) < 0.02
    lead = np.argmax(np.abs(x) > 0.02) / rate
    assert lead < 0.005
    mix, _ = samples_of(files["mix.wav"])
    melody, _ = samples_of(files["melody.wav"])
    drums, _ = samples_of(files["drums.wav"])
    assert np.max(np.abs(mix - melody - drums - x)) < 4 / 32768
    # Muted, it is out of the stems and the mix, and still in the project.
    page.check("#bandmute")
    assert draft(page)["band"]["muted"] is True
    assert played(page)[0] == [], "a muted band does not play"
    assert "band.wav" not in stems(page)
    page.click("#undo")
    expect(page.locator("#bandmute")).not_to_be_checked()
    # Undo of Generate removes the band and its link; Redo brings both back.
    page.click("#undo")
    expect(page.locator("#playbandtrack")).to_be_disabled()
    assert draft(page)["band"] is None
    page.wait_for_function("async () => !(await (" + IDB_GET + ")('draft-audio'))?.band")
    page.click("#redo")
    expect(page.locator("#playbandtrack")).to_be_enabled()
    wait_for_draft_audio(page, ["band"])
    # A version keeps it; a reload restores it.
    page.fill("#versionname", "With band")
    page.click("#saveversion")
    expect(page.locator("#status")).to_have_text("Saved version: With band")
    page.click("#removeband")
    expect(page.locator("#bandinfo")).to_have_text(re.compile("^Describe a style"))
    page.click('#versionlist button[title="Restore With band"]')
    expect(page.locator("#bandinfo")).to_have_text(re.compile("^Generated audio"))
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    expect(page.locator("#playbandtrack")).to_be_enabled()
    expect(page.locator("#bandinfo")).to_have_text(re.compile("^Generated audio"))
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


def test_a_band_can_follow_the_recording(page, app, tmp_path):
    desktop = app()
    problems = open_app(page, desktop)
    rate = 16000
    t = np.arange(rate * 2) / rate
    path = tmp_path / "hum.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes((0.4 * np.sin(2 * np.pi * 330 * t) * 32767).astype("<i2").tobytes())
    page.set_input_files("#audiofile", str(path))
    expect(page.locator("#status")).to_have_text(re.compile(r"^Recorded 2\.0s"))
    page.fill("#bandstyle", "string quartet")
    page.select_option("#bandfollows", "recording")
    page.click("#genband")
    expect(page.locator("#bandstatus")).to_have_text(re.compile(r"^Generated 2 s of band"), timeout=60_000)
    (sent,) = desktop["seen"]
    assert sent["seconds"] == pytest.approx(2.0) and sent["text"].startswith("string quartet, 100 bpm")
    wait_for_draft_audio(page, ["original", "band"])
    # Following the melody without notes says so.
    page.select_option("#bandfollows", "melody")
    page.click("#genband")
    expect(page.locator("#bandstatus")).to_have_text(re.compile("Could not generate the band: there are no melody notes"))
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


def test_the_download_is_confirmed_with_its_size_and_licence(page, app, tmp_path):
    # The real entry without its packages, so the confirmation shows where the model packages are not installed (as in CI).
    spec = dataclasses.replace(models.MUSICGEN_MELODY, packages=())
    desktop = app(models.ModelRuntime(tmp_path / "empty", [spec]))
    problems = open_app(page, desktop)
    page.click("#demo")
    page.fill("#bandstyle", "rock")
    page.click("#genband")
    expect(page.locator("#bandstatus")).to_have_text(re.compile(
        r"^The band needs MusicGen-Melody, a 6\.23 GB download kept on this Mac\. MusicGen-Melody weights are CC-BY-NC 4\.0: "
        r"for non-commercial use only\. Select Download and generate to go ahead\."))
    expect(page.locator("#genband")).to_have_text("Download and generate")
    assert desktop["runtime"].jobs.running() == [] and desktop["seen"] == []
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


def test_missing_packages_are_named(page, app, tmp_path):
    spec = dataclasses.replace(models.MUSICGEN_MELODY, packages=("tandem_not_installed",))
    desktop = app(models.ModelRuntime(tmp_path / "empty", [spec]))
    problems = open_app(page, desktop)
    page.click("#demo")
    page.fill("#bandstyle", "rock")
    page.click("#genband")
    expect(page.locator("#bandstatus")).to_have_text(
        "Could not generate the band: it needs the Python packages tandem_not_installed (python -m pip install -r requirements-models.txt).")
    expect(page.locator("#genband")).to_have_text("Generate band")
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)



def test_a_band_finished_after_another_project_opened_is_not_added_to_it(page, app, monkeypatch):
    desktop = app()
    release = threading.Event()

    def held(loaded, x, rate, text, seconds, job=None):
        job.report(0.5, "Holding the band")
        assert release.wait(30)
        return np.full(int(seconds * band.RATE), 0.1, dtype=np.float32)
    monkeypatch.setattr(band, "generate", held)
    problems = open_app(page, desktop)
    page.click("#demo")
    page.fill("#bandstyle", "rock")
    page.click("#genband")
    expect(page.locator("#bandstatus")).to_have_text(re.compile("Holding the band"))
    try:
        page.set_input_files("#projectfile", {
            "name": "other.json", "mimeType": "application/json",
            "buffer": json.dumps({"bpm": 150, "instrument": "piano", "notes": [], "drums": []}).encode()})
        expect(page.locator("#status")).to_have_text("Project opened")
    finally:
        release.set()
    expect(page.locator("#bandstatus")).to_have_text(
        "Could not generate the band: another project was opened meanwhile, so this band was not added to it.", timeout=60_000)
    expect(page.locator("#genband")).to_have_text("Generate band")
    d = draft(page)
    assert d["bpm"] == 150 and d["band"] is None
    expect(page.locator("#playbandtrack")).to_be_disabled()
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


def test_a_reload_keeps_every_recording_with_a_band(page, app, tmp_path):
    desktop = app()
    problems = open_app(page, desktop)
    path = tmp_path / "voice.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes((np.sin(np.arange(32000) * 2 * np.pi * 330 / 16000) * 10000).astype("<i2").tobytes())
    page.set_input_files("#audiofile", str(path))
    expect(page.locator("#status")).to_have_text(re.compile(r"^Recorded 2"))
    page.click("#polish")
    expect(page.locator("#status")).to_have_text("Vocal polished. Compare Original and Polished.")
    page.fill("#bandstyle", "rock")
    page.select_option("#bandfollows", "recording")
    page.click("#genband")
    expect(page.locator("#bandstatus")).to_have_text(re.compile("^Generated"), timeout=60_000)
    kept = wait_for_draft_audio(page, ["original", "polished", "band"])
    # Slow decoding: the band is back before the polished recording, and its save must not drop the polished link.
    page.add_init_script("""
        const decode = BaseAudioContext.prototype.decodeAudioData;
        BaseAudioContext.prototype.decodeAudioData = async function (...args) {
          await new Promise(resolve => setTimeout(resolve, 500));
          return decode.apply(this, args);
        };""")
    page.reload()
    expect(page.locator("#polished")).to_be_enabled(timeout=30_000)
    expect(page.locator("#playbandtrack")).to_be_enabled()
    page.wait_for_timeout(1000)
    links = page.evaluate("async () => await (" + IDB_GET + ")('draft-audio')")
    assert links == kept
    # Another reload still finds the polished recording (the clean-up kept its file).
    page.reload()
    expect(page.locator("#polished")).to_be_enabled(timeout=30_000)
    expect(page.locator("#polishinfo")).to_have_text(re.compile("^Restored the polished vocal"))
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)
