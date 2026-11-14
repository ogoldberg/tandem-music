"""SEP.1: Separate in the Mac app's window (Chromium stands in for WKWebView), with the real HTDemucs
model where it can run (see tests/test_separation.py for TANDEM_TEST_MODEL_HOME and
TANDEM_REQUIRE_SEPARATION); the tests that do not need the model run everywhere."""
import dataclasses
import importlib.util
import io
import os
import re
import sys
import wave
import zipfile

import numpy as np
import pytest
from playwright.sync_api import expect

import tandem_desktop as desk
from tandem_desktop import models
from tandem_desktop.separation import Separation
from tandem_desktop.ai_keys import AISettings
from tandem_desktop.projects import ProjectFolders
from test_desktop import Dialogs, MemoryKeys, free_port, open_app
from test_studio import IDB_DRAFT, draft_audio, wait_for_draft_audio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests"))
import separation_fixture as fx  # noqa: E402

REQUIRE = os.environ.get("TANDEM_REQUIRE_SEPARATION") == "1"


def serve(monkeypatch, catalog_home, catalog=None):
    for key in list(os.environ):
        if key.startswith(("TANDEM_", "VERCEL", "UPSTASH_")) and key not in ("TANDEM_TEST_MODEL_HOME", "TANDEM_REQUIRE_SEPARATION"):
            monkeypatch.delenv(key)
    port, secret = free_port(), desk.new_launch_secret()
    runtime = models.ModelRuntime(catalog_home, *([catalog] if catalog is not None else []))
    server, thread = desk.start_server(port, secret, desktop_api=ProjectFolders(Dialogs()),
                                       ai_settings=AISettings(os.path.join(catalog_home, 'ai'), MemoryKeys()),
                                       models=runtime, separation=Separation(runtime))
    return {"url": f"http://127.0.0.1:{port}", "port": port, "secret": secret, "runtime": runtime}, (server, thread)


@pytest.fixture
def app(monkeypatch, tmp_path):
    made = []

    def start(home=None, catalog=None):
        info, handle = serve(monkeypatch, home or tmp_path / "home", catalog)
        made.append(handle)
        return info
    yield start
    for server, thread in made:
        desk.stop_server(server, thread)


def song_wav(path):
    mix, _, _ = fx.song()
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(fx.RATE)
        w.writeframes((mix * 32767).astype("<i2").tobytes())
    path.write_bytes(out.getvalue())
    return path


def test_separate_is_offered_only_in_the_mac_app(studio, page, app, tmp_path):
    # The web studio (the `studio` fixture's page) has no Separate.
    expect(studio.locator("#separaterow")).to_be_hidden()
    desktop = app()
    problems = open_app(page, desktop)
    expect(page.locator("#separate")).to_be_visible()
    expect(page.locator("#separate")).to_be_disabled()
    page.set_input_files("#audiofile", str(song_wav(tmp_path / "song.wav")))
    expect(page.locator("#separate")).to_be_enabled()
    expect(page.locator("#playvocal")).to_be_disabled()
    expect(page.locator("#usefull")).to_be_disabled()
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


def test_separate_says_which_packages_are_missing(page, app, tmp_path):
    spec = dataclasses.replace(models.HTDEMUCS, packages=("tandem_not_installed",))
    desktop = app(catalog=[spec])
    problems = open_app(page, desktop)
    page.set_input_files("#audiofile", str(song_wav(tmp_path / "song.wav")))
    page.click("#separate")
    expect(page.locator("#separateinfo")).to_have_text(re.compile(
        r"Could not separate the voice: it needs the Python packages tandem_not_installed \(python -m pip install -r requirements-models.txt\)"))
    expect(page.locator("#separate")).to_have_text("Separate voice from music")
    assert desktop["runtime"].jobs.running() == []
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


def need_model():
    missing = [p for p in models.HTDEMUCS.packages if importlib.util.find_spec(p) is None]
    if missing:
        if REQUIRE:
            pytest.fail("TANDEM_REQUIRE_SEPARATION=1 but the packages are missing: " + ", ".join(missing))
        pytest.skip("needs requirements-models.txt")


def melody(page):
    return page.evaluate(IDB_DRAFT)["notes"]


def transcribe_on_server(page):
    page.select_option("#mode", "melody")
    page.select_option("#transcriber", "heuristic")
    page.click("#analyze")
    expect(page.locator("#status")).to_have_text("Transcription complete", timeout=60_000)
    return melody(page)


@pytest.mark.model
def test_a_song_is_separated_and_transcribed_from_its_voice(page, app, tmp_path):
    """The model is downloaded through the window the first time (pinned and verified), the
    recording is separated, the voice is what Transcribe works on, and the full recording stays."""
    need_model()
    desktop = app(home=tmp_path / "fresh")
    problems = open_app(page, desktop)
    page.set_input_files("#audiofile", str(song_wav(tmp_path / "song.wav")))
    expect(page.locator("#status")).to_have_text(re.compile(r"^Recorded 9\.0s\."))
    # Before separating, the server transcriber finds hardly any of the melody under the music.
    before = fx.recall(transcribe_on_server(page))
    # CI.3: keep every message Separate shows. The download can finish before a poll for it starts
    # (the runner fetches the 80 MB in about a second), so look for it once separation is done.
    page.evaluate("""() => { const el = document.getElementById('separateinfo'); window.__separateInfo = [];
      new MutationObserver(() => window.__separateInfo.push(el.textContent)).observe(el, {childList: true, characterData: true, subtree: true}); }""")
    page.click("#separate")
    expect(page.locator("#separate")).to_have_text("Cancel separation")
    expect(page.locator("#separateinfo")).to_have_text(re.compile(r"^Separated the voice from the music"), timeout=900_000)
    shown = page.evaluate("window.__separateInfo")
    assert any(t.startswith("Downloading") for t in shown), shown
    assert desktop["runtime"].installed_ids() == ["htdemucs"]
    expect(page.locator("#playvocal")).to_be_enabled()
    expect(page.locator("#separate")).to_be_disabled()
    links = wait_for_draft_audio(page, ["original", "vocal", "accompaniment"])
    assert len({links[s]["id"] for s in links}) == 3
    after = fx.recall(transcribe_on_server(page))
    print(f"\nSEP.1 in the window: melody recall {before:.2f} before separating, {after:.2f} after")
    # The browser hands the server its own decoding of the take (resampled), so the bar is a little
    # lower than tests/test_separation.py's.
    assert before <= 0.2 and after >= 0.5
    # The stems export carries the full recording, the separated vocal and the music.
    with page.expect_download() as info:
        page.click("#exportstems")
    names = zipfile.ZipFile(info.value.path()).namelist()
    assert {"vocal-original.wav", "vocal-separated.wav", "accompaniment.wav"} <= set(names), names
    # A reload restores the separation from the draft.
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    expect(page.locator("#separateinfo")).to_have_text(re.compile("Restored the separated voice and music"))
    expect(page.locator("#usefull")).to_be_enabled()
    # Use the full recording drops the separation; Transcribe works on all of it again.
    page.click("#usefull")
    wait_for_draft_audio(page, ["original"])
    assert fx.recall(transcribe_on_server(page)) <= 0.2
    expect(page.locator("#separate")).to_be_enabled()
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


@pytest.mark.model
def test_a_separation_can_be_cancelled(page, app, tmp_path):
    need_model()
    home = os.environ.get("TANDEM_TEST_MODEL_HOME")
    if not home:
        if REQUIRE:
            pytest.fail("TANDEM_REQUIRE_SEPARATION=1 needs TANDEM_TEST_MODEL_HOME")
        pytest.skip("set TANDEM_TEST_MODEL_HOME to a folder for the HTDemucs weights")
    desktop = app(home=home)
    rt = desktop["runtime"]
    if not rt.store.installed(models.HTDEMUCS):
        assert rt.jobs.wait(rt.start_download("htdemucs").id, timeout=900).state == "done"
    problems = open_app(page, desktop)
    # A long take, so the separation is still running when Cancel is pressed.
    mix, _, _ = fx.song()
    long = np.tile(mix, 20)
    path = tmp_path / "long.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(fx.RATE)
        w.writeframes((long * 32767).astype("<i2").tobytes())
    page.set_input_files("#audiofile", str(path))
    expect(page.locator("#separate")).to_be_enabled()
    page.click("#separate")
    page.wait_for_function("/Separating the voice from the music…/.test(document.getElementById('separateinfo').textContent)", timeout=120_000)
    page.click("#separate")
    expect(page.locator("#separateinfo")).to_have_text("Separation cancelled.", timeout=120_000)
    expect(page.locator("#playvocal")).to_be_disabled()
    assert set(draft_audio(page)) == {"original"}
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)
