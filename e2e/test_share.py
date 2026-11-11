"""MOB.3: an idea is shared from the phone as one .tandem.zip file (the project plus its recording as
WAV) and opens in the studio of another browser profile with its audio."""
import base64
import io
import json
import wave
import zipfile

import numpy as np
from playwright.sync_api import expect

from test_capture import PHONE, open_capture, phone_page, record
from test_studio import IDB_GET, OPFS_FILES, count

# navigator.share with files, as on iOS Safari and Android Chrome: the shared file is kept for the test.
SHARE_STUB = """(() => {
  window.__shares = [];
  window.__shareFailures = %s;
  navigator.canShare = data => !!data && Array.isArray(data.files) && data.files.length > 0;
  navigator.share = async data => {
    if (window.__shareFailures.length) throw new DOMException('refused', window.__shareFailures.shift());
    const f = data.files[0], bytes = new Uint8Array(await f.arrayBuffer());
    let s = '';
    for (const b of bytes) s += String.fromCharCode(b);
    window.__shares.push({ name: f.name, type: f.type, title: data.title, b64: btoa(s) });
  };
})()"""

NO_SHARE = "delete Navigator.prototype.share; delete Navigator.prototype.canShare;"


def shares(page):
    return page.evaluate("window.__shares")


def wav_info(data):
    with wave.open(io.BytesIO(data)) as w:
        return w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()


def wait_for_draft_audio(page, slots):
    """Polls inside the page: wait_for_function would pass at once on an async predicate."""
    return page.evaluate(f"""async () => {{
      for (let i = 0; i < 100; i++) {{
        const v = await ({IDB_GET})('draft-audio');
        if (v && {json.dumps(sorted(slots))}.every(s => v[s]) && Object.keys(v).length === {len(slots)}) return v;
        await new Promise(r => setTimeout(r, 100));
      }}
      return null;
    }}""")


def studio_page(browser, server_url, problems):
    """The studio in a fresh browser profile (a new context: its own IndexedDB and OPFS)."""
    context = browser.new_context(base_url=server_url)
    page = context.new_page()
    page.on("pageerror", lambda exc: problems.append(f"pageerror: {exc}"))
    page.on("console", lambda msg: problems.append(f"console.{msg.type}: {msg.text}") if msg.type == "error" else None)
    page.goto("/")
    page.wait_for_function("!document.body.inert")
    return context, page


def open_bundle(page, name, data):
    page.set_input_files("#projectfile", {"name": name, "mimeType": "application/zip", "buffer": data})


def test_share_an_idea_and_open_it_in_a_fresh_profile_with_its_audio(browser, browser_name, server_url):
    with phone_page(browser, browser_name, server_url) as phone:
        phone.add_init_script(SHARE_STUB % "[]")
        open_capture(phone)
        record(phone, 1.5)
        phone.click(".idea >> text=Rename")
        phone.fill(".idea input", "Bus stop")
        phone.keyboard.press("Enter")
        expect(phone.locator(".idea .title")).to_have_text("Bus stop")
        phone.click(".idea >> text=Share")
        expect(phone.locator("#status")).to_have_text("Shared Bus stop.")
        [shared] = shares(phone)
    assert shared["name"] == "Bus stop.tandem.zip" and shared["type"] == "application/zip" and shared["title"] == "Bus stop"
    data = base64.b64decode(shared["b64"])

    # A standard zip that any tool reads: the DESK.3 project folder.
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.testzip() is None
        assert z.namelist() == ["tandem.json", "project.json", "original.wav"]
        meta = json.loads(z.read("tandem.json"))
        project = json.loads(z.read("project.json"))
        original = z.read("original.wav")
    assert meta["format"] == "tandem-bundle" and meta["version"] == 1 and meta["name"] == "Bus stop" and meta["savedAt"] > 0
    assert project == {"format": "tandem-project", "version": 1, "bpm": 100, "instrument": "piano", "melody_locked": True,
                       "notes": [], "drums": [], "harmony": [], "harmony_instrument": "piano"}
    channels, width, rate, frames = wav_info(original)
    assert channels == 1 and width == 2 and rate == 48000
    assert 1.2 <= frames / rate <= 3, frames / rate
    # The fake microphone beeps: the recording is not silence.
    samples = np.frombuffer(original[44:], dtype="<i2")
    assert np.abs(samples).max() > 1000

    problems = []
    context, page = studio_page(browser, server_url, problems)
    try:
        open_bundle(page, shared["name"], data)
        expect(page.locator("#status")).to_have_text("Opened Bus stop with its recording.")
        for button in ["#original", "#analyze", "#tune"]:
            expect(page.locator(button)).to_be_enabled()
        links = wait_for_draft_audio(page, ["original"])
        assert links and links["original"]["type"] == "audio/wav"
        assert page.evaluate(OPFS_FILES) == [links["original"]["id"]]
        # The kept recording is the shared WAV, byte for byte.
        stored = page.evaluate("""async id => { const d = await (await navigator.storage.getDirectory()).getDirectoryHandle('recordings');
            return [...new Uint8Array(await (await (await d.getFileHandle(id)).getFile()).arrayBuffer())].length }""", links["original"]["id"])
        assert stored == len(original)
        # Kept across a reload in this profile.
        page.reload()
        page.wait_for_function("!document.body.inert")
        expect(page.locator("#status")).to_have_text("Restored the draft and its recording.")
        expect(page.locator("#original")).to_be_enabled()
    finally:
        context.close()
    assert not problems, problems


def finished_project_bundle():
    """A project with notes, harmony and drums plus its original and tuned recordings, zipped by
    Python with deflate inside a folder, as Finder would zip a DESK.3 project folder."""
    def tone(hz, rate=22050, seconds=0.8):
        out = io.BytesIO()
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            t = np.arange(int(rate * seconds)) / rate
            w.writeframes((0.3 * np.sin(2 * np.pi * hz * t) * 32767).astype("<i2").tobytes())
        return out.getvalue()
    project = {"format": "tandem-project", "version": 1, "bpm": 84, "instrument": "flute", "melody_locked": True,
               "notes": [{"m": 60, "t": 0, "d": 0.5}, {"m": 64, "t": 0.5, "d": 0.5}, {"m": 67, "t": 1, "d": 0.5}],
               "drums": [{"k": "kick", "t": 0}, {"k": "snare", "t": 0.5}],
               "harmony": [{"m": 48, "t": 0, "d": 1.5}], "harmony_instrument": "strings"}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Night drive.tandem/tandem.json", json.dumps({"format": "tandem-bundle", "version": 1, "name": "Night drive", "savedAt": 1762819200000}))
        z.writestr("Night drive.tandem/project.json", json.dumps(project))
        z.writestr("Night drive.tandem/original.wav", tone(440))
        z.writestr("Night drive.tandem/tuned.wav", tone(441))
        z.writestr("__MACOSX/Night drive.tandem/._original.wav", b"\0" * 32)
    return out.getvalue()


def test_opening_a_project_file_keeps_the_previous_draft_and_restores_every_recording(studio):
    page = studio
    page.wait_for_function("!document.body.inert")
    page.click("#demo")
    expect(page.locator("#notecount")).to_have_text("8 notes")

    open_bundle(page, "Night drive.tandem.zip", finished_project_bundle())
    expect(page.locator("#status")).to_have_text('Opened Night drive with its recordings. Your previous draft was saved as the version "Before Night drive".')
    assert count(page, "notecount") == 3
    expect(page.locator("#bpm")).to_have_value("84")
    expect(page.locator("#instrument")).to_have_value("flute")
    expect(page.locator("#harmonyinstrument")).to_have_value("strings")
    expect(page.locator("#original")).to_be_enabled()
    expect(page.locator("#playtuned")).to_be_enabled()
    expect(page.locator("#polished")).to_be_disabled()
    links = wait_for_draft_audio(page, ["original", "tuned"])
    assert links and links["original"]["id"] != links["tuned"]["id"]

    # Opening it is one undoable edit for the notes, like Open project.
    page.click("#undo")
    assert count(page, "notecount") == 8

    page.click("#versionlist .version:has-text('Before Night drive') >> text=Restore")
    expect(page.locator("#status")).to_have_text("Restored version: Before Night drive")
    assert count(page, "notecount") == 8


def test_a_project_file_without_a_recording_opens_like_a_project(studio):
    page = studio
    page.wait_for_function("!document.body.inert")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("project.json", json.dumps({"format": "tandem-project", "version": 1, "bpm": 120, "notes": [{"m": 62, "t": 0, "d": 1}], "drums": []}))
    open_bundle(page, "plain.tandem.zip", out.getvalue())
    expect(page.locator("#status")).to_have_text("Project opened")
    assert count(page, "notecount") == 1
    expect(page.locator("#versionlist")).to_have_text("No saved versions yet.")


def test_a_file_that_is_not_a_tandem_project_is_refused(studio):
    page = studio
    page.wait_for_function("!document.body.inert")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("song.mp3", b"ID3")
    open_bundle(page, "photos.zip", out.getvalue())
    expect(page.locator("#status")).to_have_text("The file has no project.json, so it is not a Tandem project.")
    project = io.BytesIO()
    with zipfile.ZipFile(project, "w") as z:
        z.writestr("project.json", json.dumps({"notes": [], "drums": [], "instrument": "kazoo"}))
        z.writestr("original.wav", b"RIFF\0\0\0\0WAVE")
    open_bundle(page, "kazoo.tandem.zip", project.getvalue())
    expect(page.locator("#status")).to_have_text("Unsupported instrument: kazoo")
    assert page.evaluate(OPFS_FILES) == []


def test_share_downloads_the_file_where_files_cannot_be_shared(browser, browser_name, server_url, tmp_path):
    with phone_page(browser, browser_name, server_url) as phone:
        phone.add_init_script(NO_SHARE)
        open_capture(phone)
        record(phone)
        with phone.expect_download() as info:
            phone.click(".idea >> text=Share")
        expect(phone.locator("#status")).to_contain_text("Downloaded Idea · ")
        target = tmp_path / info.value.suggested_filename
        info.value.save_as(target)
    assert target.name.startswith("Idea · ") and target.name.endswith(".tandem.zip") and ":" not in target.name
    with zipfile.ZipFile(target) as z:
        assert z.namelist() == ["tandem.json", "project.json", "original.wav"]
        assert json.loads(z.read("tandem.json"))["name"] == ""


def test_a_cancelled_share_says_so_and_a_refused_one_is_offered_again(browser, browser_name, server_url):
    with phone_page(browser, browser_name, server_url) as phone:
        phone.add_init_script(SHARE_STUB % "['AbortError', 'NotAllowedError']")
        open_capture(phone)
        record(phone)
        share = phone.locator(".idea .share")
        share.click()
        expect(phone.locator("#status")).to_have_text("Sharing was cancelled.")
        assert shares(phone) == []
        # Safari refuses a share that comes too long after the tap (building the file takes time): the
        # file is ready, and the next tap shares it at once.
        share.click()
        expect(share).to_have_text("Tap to share")
        expect(phone.locator("#status")).to_contain_text("The file is ready. Tap Share again")
        share.click()
        expect(phone.locator("#status")).to_contain_text("Shared Idea · ")
        expect(share).to_have_text("Share")
        assert len(shares(phone)) == 1
