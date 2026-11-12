"""TIMBRE.1: Play my voice on it in the Mac app's window (Chromium stands in for WKWebView).

The studio runs against a stand-in for the RAVE model (the recording at half volume in place of the
instrument), so these tests check what the window does: what it sends, where it puts the new
recording, how it plays, saves, undoes and exports. The real models' pitch and timing are measured in
tests/test_timbre.py (TANDEM_TEST_TIMBRE=1).
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
from tandem_desktop import models, timbre
from tandem_desktop.ai_keys import AISettings
from tandem_desktop.projects import ProjectFolders
from test_desktop import Dialogs, MemoryKeys, free_port, open_app
from test_studio import IDB_DRAFT, IDB_GET, wait_for_draft_audio

RATE = 16000
SECONDS = 2


def stand_in_runtime(home):
    """A runtime with every RAVE instrument installed (a stand-in file pinned in place of each model)."""
    body = b"stand-in model"
    specs = [models.ModelSpec(s.id, s.label, (models.ModelFile(s.files[0].name, "https://example.test/m",
                                                             hashlib.sha256(body).hexdigest(), len(body)),), packages=())
             for s in models.RAVE_MODELS]
    runtime = models.ModelRuntime(home, specs)
    for spec in specs:
        folder = runtime.store.folder(spec)
        folder.mkdir(parents=True)
        (folder / spec.files[0].name).write_bytes(body)
        st = (folder / spec.files[0].name).stat()
        (folder / models.RECORD).write_text(json.dumps(
            {spec.files[0].name: {"sha256": spec.files[0].sha256, "size": st.st_size, "mtime_ns": st.st_mtime_ns}}))
    return runtime


@pytest.fixture
def app(monkeypatch, tmp_path):
    made = []
    seen = []
    hold = {"event": None}

    def transfer(model, x, rate, sr, job=None):
        seen.append({"x": np.asarray(x), "rate": rate})
        job.report(0.5, "Playing your voice on the instrument")
        if hold["event"] is not None:
            assert hold["event"].wait(30)
        return (0.5 * np.asarray(x)).astype(np.float32)
    monkeypatch.setattr(timbre, "load_rave", lambda path, rate: "model")
    monkeypatch.setattr(timbre, "transfer", transfer)

    def start(runtime=None):
        for key in list(os.environ):
            if key.startswith(("TANDEM_", "VERCEL", "UPSTASH_")):
                monkeypatch.delenv(key)
        runtime = runtime or stand_in_runtime(tmp_path / "home")
        port, secret = free_port(), desk.new_launch_secret()
        handle = desk.start_server(port, secret, desktop_api=ProjectFolders(Dialogs()),
                                   ai_settings=AISettings(tmp_path / "ai", MemoryKeys()), models=runtime,
                                   timbre=timbre.Timbre(runtime))
        made.append(handle)
        return {"url": f"http://127.0.0.1:{port}", "port": port, "secret": secret, "runtime": runtime, "seen": seen, "hold": hold}
    yield start
    for server, thread in made:
        desk.stop_server(server, thread)


def hum(path, hz=330, seconds=SECONDS):
    t = np.arange(RATE * seconds) / RATE
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes((0.4 * np.sin(2 * np.pi * hz * t) * 32767).astype("<i2").tobytes())
    return path


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


def record(page, path):
    page.set_input_files("#audiofile", str(path))
    expect(page.locator("#status")).to_have_text(re.compile(r"^Recorded 2\.0s"))


# Records every scheduled Web Audio buffer source with its start time, length and peak.
WATCH_STARTS = """() => {
  window.starts = [];
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
    """Press Play and return the instrument recordings it scheduled (2 s long, peak 0.2), and the time of zero."""
    page.evaluate("window.starts = []")
    page.click("#play")
    expect(page.locator("#status")).to_have_text(re.compile("^Playing composition"))
    starts = page.evaluate("window.starts")
    page.click("#stop")
    voices = [s for s in starts if s["seconds"] and abs(s["seconds"] - SECONDS) < 0.01 and abs(s["peak"] - 0.2) < 0.01]
    others = [s["when"] for s in starts if s not in voices]
    first = min(n["t"] for n in draft(page)["notes"] + draft(page)["drums"])
    return voices, min(others) - first


def test_the_instrument_voice_is_offered_only_in_the_mac_app(studio):
    expect(studio.locator("#timbretrack")).to_be_hidden()


def test_the_voice_is_played_as_an_instrument_kept_played_undone_and_exported(page, app, tmp_path):
    desktop = app()
    problems = open_app(page, desktop)
    expect(page.locator("#timbretrack")).to_be_visible()
    expect(page.locator("#playtimbretrack")).to_be_disabled()
    page.click("#gentimbre")
    expect(page.locator("#timbrestatus")).to_have_text("Record or import your voice first, then play it on the instrument.")
    page.click("#demo")
    record(page, hum(tmp_path / "hum.wav"))
    page.select_option("#timbreinstrument", "sax")
    page.click("#gentimbre")
    expect(page.locator("#timbrestatus")).to_have_text(re.compile(r"^Your take played as a soprano saxophone \(2 s\)"), timeout=60_000)
    expect(page.locator("#gentimbre")).to_have_text("Play my voice on it")
    # The window sent the take as it was recorded: from zero, at its pitch.
    (sent,) = desktop["seen"]
    x, rate = sent["x"], sent["rate"]
    assert len(x) == SECONDS * rate and np.argmax(np.abs(x) > 0.05) < rate * 0.002
    spectrum = np.abs(np.fft.rfft(x))
    assert abs(np.argmax(spectrum) * rate / len(x) - 330) < 2
    expect(page.locator("#timbreinfo")).to_have_text(re.compile(
        r"^Generated audio: your take played as a soprano saxophone by a RAVE model, 2 s from the start\. "
        r"The RAVE instrument models are CC-BY-NC 4\.0"))
    t = draft(page)["timbre"]
    assert {k: t[k] for k in ("instrument", "source", "seconds", "muted", "model")} == {
        "instrument": "sax", "source": "take", "seconds": 2, "muted": False, "model": "rave"}
    wait_for_draft_audio(page, ["original", "timbre"])
    # Play schedules it once, from the parts' zero; muted, it does not play and is out of the export.
    page.evaluate(WATCH_STARTS)
    voices, zero = played(page)
    assert len(voices) == 1 and voices[0]["when"] == pytest.approx(zero, abs=1e-3)
    files = stems(page)
    assert {"mix.wav", "melody.wav", "drums.wav", "timbre.wav", "vocal-original.wav"} <= set(files), list(files)
    y, rate = samples_of(files["timbre.wav"])
    assert rate == 44100 and abs(np.max(np.abs(y[:rate * SECONDS])) - 0.2) < 0.02 and np.argmax(np.abs(y) > 0.05) < 0.005 * rate
    mix, _ = samples_of(files["mix.wav"])
    melody, _ = samples_of(files["melody.wav"])
    drums, _ = samples_of(files["drums.wav"])
    assert np.max(np.abs(mix - melody - drums - y)) < 4 / 32768
    page.check("#timbremute")
    assert draft(page)["timbre"]["muted"] is True
    assert played(page)[0] == []
    assert "timbre.wav" not in stems(page)
    page.click("#undo")
    expect(page.locator("#timbremute")).not_to_be_checked()
    # Undo removes it and its link; Redo brings both back; the original stays throughout.
    page.click("#undo")
    expect(page.locator("#playtimbretrack")).to_be_disabled()
    assert draft(page)["timbre"] is None
    wait_for_draft_audio(page, ["original"])
    page.click("#redo")
    expect(page.locator("#playtimbretrack")).to_be_enabled()
    wait_for_draft_audio(page, ["original", "timbre"])
    # A version keeps it; a reload restores it.
    page.fill("#versionname", "As sax")
    page.click("#saveversion")
    expect(page.locator("#status")).to_have_text("Saved version: As sax")
    page.click("#removetimbre")
    expect(page.locator("#timbreinfo")).to_have_text(re.compile("^Choose an instrument"))
    page.click('#versionlist button[title="Restore As sax"]')
    expect(page.locator("#timbreinfo")).to_have_text(re.compile("^Generated audio"))
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    expect(page.locator("#playtimbretrack")).to_be_enabled()
    expect(page.locator("#timbreinfo")).to_have_text(re.compile("^Generated audio"))
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


def test_the_tuned_voice_is_played_when_there_is_one(page, app, tmp_path):
    desktop = app()
    problems = open_app(page, desktop)
    page.select_option("#mode", "vocal")
    record(page, hum(tmp_path / "hum.wav", hz=338))  # a little sharp of E4
    page.click("#tune")
    expect(page.locator("#status")).to_have_text("Pitch correction complete", timeout=120_000)
    page.select_option("#timbreinstrument", "guitar")
    page.click("#gentimbre")
    expect(page.locator("#timbrestatus")).to_have_text(re.compile(r"^Your tuned voice played as an electric guitar \(2 s\)"), timeout=60_000)
    (sent,) = desktop["seen"]
    x, rate = sent["x"], sent["rate"]
    mid = x[rate // 2:rate * 3 // 2]
    hz = np.argmax(np.abs(np.fft.rfft(mid))) * rate / len(mid)
    assert abs(hz - 329.6) < 3, "the tuned voice (E4), not the sharp take"
    assert draft(page)["timbre"]["source"] == "tuned"
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


def test_the_download_is_confirmed_with_its_size_and_licence(page, app, tmp_path):
    specs = [dataclasses.replace(s, packages=()) for s in models.RAVE_MODELS]
    desktop = app(models.ModelRuntime(tmp_path / "empty", specs))
    problems = open_app(page, desktop)
    record(page, hum(tmp_path / "hum.wav"))
    page.select_option("#timbreinstrument", "organ")
    page.click("#gentimbre")
    expect(page.locator("#timbrestatus")).to_have_text(
        "The church organ needs its RAVE model, a 164 MB download kept on this Mac. The RAVE instrument models are "
        "CC-BY-NC 4.0: for non-commercial use only. Select Download and play to go ahead.")
    expect(page.locator("#gentimbre")).to_have_text("Download and play")
    assert desktop["runtime"].jobs.running() == [] and desktop["seen"] == []
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


def test_missing_packages_are_named(page, app, tmp_path):
    specs = [dataclasses.replace(s, packages=("tandem_not_installed",)) for s in models.RAVE_MODELS]
    desktop = app(models.ModelRuntime(tmp_path / "empty", specs))
    problems = open_app(page, desktop)
    record(page, hum(tmp_path / "hum.wav"))
    page.click("#gentimbre")
    expect(page.locator("#timbrestatus")).to_have_text(
        "Could not play your voice on the instrument: it needs the Python packages tandem_not_installed "
        "(python -m pip install -r requirements-models.txt).")
    expect(page.locator("#gentimbre")).to_have_text("Play my voice on it")
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


def test_an_instrument_recording_finished_after_another_project_opened_is_not_added_to_it(page, app, tmp_path):
    desktop = app()
    desktop["hold"]["event"] = threading.Event()
    problems = open_app(page, desktop)
    record(page, hum(tmp_path / "hum.wav"))
    page.click("#gentimbre")
    expect(page.locator("#timbrestatus")).to_have_text(re.compile("Playing your voice on the instrument"))
    try:
        page.set_input_files("#projectfile", {
            "name": "other.json", "mimeType": "application/json",
            "buffer": json.dumps({"bpm": 150, "instrument": "piano", "notes": [], "drums": []}).encode()})
        expect(page.locator("#status")).to_have_text("Project opened")
    finally:
        desktop["hold"]["event"].set()
    expect(page.locator("#timbrestatus")).to_have_text(
        "Could not play your voice on the instrument: another project was opened meanwhile, so this recording was not added to it.",
        timeout=60_000)
    assert draft(page)["timbre"] is None
    expect(page.locator("#playtimbretrack")).to_be_disabled()
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


def test_a_reload_keeps_every_recording_with_an_instrument_voice(page, app, tmp_path):
    desktop = app()
    problems = open_app(page, desktop)
    record(page, hum(tmp_path / "hum.wav"))
    page.click("#polish")
    expect(page.locator("#status")).to_have_text("Vocal polished. Compare Original and Polished.")
    page.click("#gentimbre")
    expect(page.locator("#timbrestatus")).to_have_text(re.compile("^Your take played"), timeout=60_000)
    kept = wait_for_draft_audio(page, ["original", "polished", "timbre"])
    page.add_init_script("""
        const decode = BaseAudioContext.prototype.decodeAudioData;
        BaseAudioContext.prototype.decodeAudioData = async function (...args) {
          await new Promise(resolve => setTimeout(resolve, 500));
          return decode.apply(this, args);
        };""")
    page.reload()
    expect(page.locator("#polished")).to_be_enabled(timeout=30_000)
    expect(page.locator("#playtimbretrack")).to_be_enabled()
    page.wait_for_timeout(1000)
    assert page.evaluate("async () => await (" + IDB_GET + ")('draft-audio')") == kept
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


def test_opening_an_idea_drops_the_previous_projects_instrument_track(page, app, tmp_path):
    desktop=app()
    open_app(page, desktop)
    record(page, hum(tmp_path/'hum.wav'))
    page.click('#gentimbre')
    expect(page.locator('#timbrestatus')).to_have_text(re.compile('^Your take played'), timeout=60000)
    assert draft(page)['timbre']
    idea=page.evaluate('''async () => {
      const {openKV}=await import('./storage.js');
      const {createIdeaStore}=await import('./ideas.js');
      const kv=await openKV(indexedDB);
      const links=await kv.get('draft-audio');
      return await createIdeaStore(kv).add({duration:2,audio:links.original});
    }''')
    page.goto(desktop['url']+'/?idea='+idea['id'])
    expect(page.locator('#status')).to_contain_text('Transcribe it to turn it into notes.')
    assert draft(page)['timbre'] is None
