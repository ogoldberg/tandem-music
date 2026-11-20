"""MOB.3: an idea is shared from the phone as one .tandem.zip file (the project plus its recording as
WAV) and opens in the studio of another browser profile with its audio."""
import base64
import hashlib
import io
import json
import re
import wave
import zipfile

import numpy as np
from playwright.sync_api import expect

from test_capture import PHONE, open_capture, phone_page, record
from test_studio import IDB_GET, OPFS_FILES, count, download, import_recording, tone_wav
from conftest import ALL_CONTROLS

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
    context.add_init_script(ALL_CONTROLS)
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
        # The take is kept at the rate the phone's audio runs at (REC.3: the worklet's frames, not a re-encode).
        take = json.loads(phone.get_attribute("#record", "data-take"))
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
    assert channels == 1 and width == 2 and rate == take["rate"] and frames == take["frames"]
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
            const digest = await crypto.subtle.digest('SHA-256', await (await (await d.getFileHandle(id)).getFile()).arrayBuffer());
            return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('') }""", links["original"]["id"])
        assert stored == hashlib.sha256(original).hexdigest() == links["original"]["id"]
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


def test_a_project_json_opens_over_the_recording_loaded_now(studio, tmp_path):
    """A project file is notes only (it never has audio), so it opens over the recording loaded now, which stays."""
    page = studio
    page.wait_for_function("!document.body.inert")
    page.set_input_files("#audiofile", str(tone_wav(tmp_path / "tones.wav")))
    expect(page.locator("#status")).to_contain_text("Recorded")
    linked = wait_for_draft_audio(page, ["original"])
    assert linked, "the take was never linked from the draft"
    held = linked["original"]["id"]
    project = {"format": "tandem-project", "version": 1, "bpm": 120, "notes": [{"m": 62, "t": 0, "d": 1}], "drums": []}
    page.set_input_files("#projectfile", {"name": "plain.json", "mimeType": "application/json", "buffer": json.dumps(project).encode()})
    expect(page.locator("#status")).to_have_text("Project opened")
    assert count(page, "notecount") == 1
    expect(page.locator("#original")).to_be_enabled()
    assert page.evaluate(IDB_GET, "draft-audio")["original"]["id"] == held
    assert page.evaluate(IDB_GET, "versions") in (None, [])


def test_opening_a_tandem_file_without_a_recording_keeps_the_draft_as_a_version_then_clears_its_recording(studio, tmp_path):
    """#61: a Tandem file (or folder, e2e/test_desktop.py) is a whole project, so the recording loaded before goes with the draft it belongs to:
    the draft is kept as a version with it, and the project opens without it, so a later save does not write the old
    recording into the opened project."""
    page = studio
    page.wait_for_function("!document.body.inert")
    page.set_input_files("#audiofile", str(tone_wav(tmp_path / "tones.wav")))
    expect(page.locator("#status")).to_contain_text("Recorded")
    expect(page.locator("#original")).to_be_enabled()
    linked = wait_for_draft_audio(page, ["original"])
    assert linked, "the take was never linked from the draft"
    held = linked["original"]["id"]
    project = {"format": "tandem-project", "version": 1, "bpm": 120, "notes": [{"m": 62, "t": 0, "d": 1}], "drums": []}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("project.json", json.dumps(project))
    open_bundle(page, "plain.tandem.zip", out.getvalue())
    expect(page.locator("#status")).to_have_text('Project opened. Your previous draft was saved as the version "Before plain".')
    assert count(page, "notecount") == 1
    for button in ["#original", "#polish", "#analyze", "#tune"]:
        expect(page.locator(button)).to_be_disabled()
    assert page.evaluate(IDB_GET, "draft-audio") == {}
    versions = page.evaluate(IDB_GET, "versions")
    assert [v["name"] for v in versions] == ["Before plain"] and versions[0]["audio"]["original"]["id"] == held
    # Undo brings the notes back; the version brings the recording back.
    page.click("#versionlist .version:has-text('Before plain') >> text=Restore")
    expect(page.locator("#status")).to_have_text("Restored version: Before plain")
    expect(page.locator("#original")).to_be_enabled()
    assert page.evaluate(IDB_GET, "draft-audio")["original"]["id"] == held


def test_a_project_with_only_a_harmony_voice_exports_stems_and_is_kept_as_a_version(studio, tmp_path):
    """HARM.1: notes only in the harmony voice are something to export and a draft worth keeping: Export
    stems names the harmony voice, the MIDI key is detected from it, and opening another project keeps it."""
    import mido
    page = studio
    page.wait_for_function("!document.body.inert")
    scale = [{"m": m, "t": i * 0.5, "d": 0.45} for i, m in enumerate([60, 62, 64, 65, 67, 69, 71, 72])]
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("project.json", json.dumps({"format": "tandem-project", "version": 1, "bpm": 120, "notes": [],
                                               "drums": [], "voice2": scale, "voice2_instrument": "piano"}))
    open_bundle(page, "voice.tandem.zip", out.getvalue())
    expect(page.locator("#status")).to_have_text("Project opened")
    expect(page.locator("#voice2count")).to_have_text("8 notes")

    path = download(page, "#exportstems", tmp_path)
    expect(page.locator("#status")).to_have_text("Exported 1 stem (harmony voice) and the MIDI file")
    with zipfile.ZipFile(path) as z:
        assert "harmony-voice.wav" in z.namelist()
        mid = mido.MidiFile(file=io.BytesIO(z.read("tandem.mid")))
    keys = [m.key for t in mid.tracks for m in t if m.type == "key_signature"]
    assert keys == ["C"]

    open_bundle(page, "Night drive.tandem.zip", finished_project_bundle())
    expect(page.locator("#status")).to_have_text('Opened Night drive with its recordings. Your previous draft was saved as the version "Before Night drive".')


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


def test_a_recording_that_cannot_be_decoded_changes_nothing(studio):
    page = studio
    page.wait_for_function("!document.body.inert")
    page.click("#demo")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("project.json", json.dumps({"format": "tandem-project", "version": 1, "notes": [], "drums": []}))
        z.writestr("original.wav", b"RIFF\x04\x00\x00\x00WAVEjunk")
    open_bundle(page, "broken.tandem.zip", out.getvalue())
    expect(page.locator("#status")).to_contain_text("Could not decode the recording in the file:")
    assert count(page, "notecount") == 8
    expect(page.locator("#versionlist")).to_have_text("No saved versions yet.")
    expect(page.locator("#original")).to_be_disabled()


def test_without_device_storage_opening_a_file_says_the_draft_was_not_kept(page, server_url):
    problems = []
    page.on("pageerror", lambda exc: problems.append(str(exc)))
    page.add_init_script("StorageManager.prototype.getDirectory = () => Promise.reject(new DOMException('no', 'UnknownError'));")
    page.goto(server_url + "/")
    page.wait_for_function("!document.body.inert")
    page.click("#demo")
    open_bundle(page, "Night drive.tandem.zip", finished_project_bundle())
    expect(page.locator("#status")).to_contain_text("Opened Night drive with its recordings. Your previous draft could not be saved as a version")
    # The storage problem ends as a sentence before the next one starts.
    expect(page.locator("#status")).to_have_text(re.compile(r"saved as a version: [^\n]*[^.]\. Undo brings back its notes but not its recording\.$"))
    assert count(page, "notecount") == 3
    assert not problems, problems


# SHARE.1: Share the song, the files named after the song, and the song saved with its recordings.

def song_samples(data):
    """The shared mix as floats, after checking it is a WAV of the song."""
    channels, width, rate, frames = wav_info(data)
    assert channels == 1 and width == 2 and rate == 44100 and frames > rate
    return np.frombuffer(data[44:44 + frames * 2], dtype="<i2").astype(np.float64) / 32768


def song_with_a_take(page, tmp_path, name="Bus stop"):
    """The example tune and drums over an imported take, the song named."""
    page.wait_for_function("!document.body.inert")
    wav = tmp_path / "take.wav"
    tone_wav(wav)
    import_recording(page, wav)
    page.click("#demo")
    expect(page.locator("#notecount")).to_have_text("8 notes")
    expect(page.locator("#original")).to_be_enabled()
    page.fill("#songname", name)
    page.dispatch_event("#songname", "change")


def test_share_the_song_named_after_it_with_or_without_your_voice(studio, tmp_path):
    page = studio
    song_with_a_take(page, tmp_path)
    page.evaluate(SHARE_STUB % "[]")
    # The voice is muted by default (MIX.1): the song is the arrangement alone.
    expect(page.locator("#mute-voice")).to_have_attribute("aria-pressed", "true")
    page.click("#sharesong")
    expect(page.locator("#status")).to_have_text("Shared Bus stop.wav without your voice.", timeout=40_000)
    page.click("#mute-voice")
    expect(page.locator("#undo")).to_have_attribute("title", "Undo: Unmute your voice")
    page.click("#sharesong")
    expect(page.locator("#status")).to_have_text("Shared Bus stop.wav with your voice.", timeout=40_000)
    without, with_voice = shares(page)
    for shared in (without, with_voice):
        assert shared["name"] == "Bus stop.wav" and shared["type"] == "audio/wav" and shared["title"] == "Bus stop"
    a, b = (song_samples(base64.b64decode(x["b64"])) for x in (without, with_voice))
    assert np.abs(a).max() > 0.01, "the arrangement is heard"
    # The difference is the take: its first tone (440 Hz) from zero, at the start of the song.
    n = min(len(a), len(b))
    voice = (b[:n] - a[:n])[:int(0.6 * 44100)]
    assert np.sqrt(np.mean(voice ** 2)) > 0.02
    spectrum = np.abs(np.fft.rfft(voice))
    assert abs(np.argmax(spectrum) * 44100 / len(voice) - 440) < 5


def test_share_the_song_downloads_it_where_files_cannot_be_shared_and_every_export_is_named_after_it(studio, tmp_path):
    page = studio
    song_with_a_take(page, tmp_path, "Night: drive?")
    page.evaluate(NO_SHARE)
    with page.expect_download(timeout=40_000) as info:
        page.click("#sharesong")
    assert info.value.suggested_filename == "Night- drive.wav"
    expect(page.locator("#status")).to_have_text("Downloaded Night- drive.wav without your voice.")
    for button, name in [("#exportwav", "Night- drive.wav"), ("#exportmidi", "Night- drive.mid"),
                         ("#exportmusicxml", "Night- drive.musicxml"), ("#save", "Night- drive.json"),
                         ("#savebundle", "Night- drive.tandem.zip")]:
        with page.expect_download(timeout=40_000) as info:
            page.click(button)
        assert info.value.suggested_filename == name, button


def test_a_refused_share_of_the_song_is_offered_again_until_the_song_changes(studio, tmp_path):
    page = studio
    song_with_a_take(page, tmp_path)
    page.evaluate(SHARE_STUB % "['AbortError', 'NotAllowedError', 'NotAllowedError']")
    share = page.locator("#sharesong")
    share.click()
    expect(page.locator("#status")).to_have_text("Sharing was cancelled.", timeout=40_000)
    share.click()
    expect(share).to_have_text("Tap to share", timeout=40_000)
    expect(page.locator("#status")).to_have_text("The song is ready. Tap Share the song again to send it.")
    # A change to the song drops the ready file: the next tap makes it again.
    page.click("#mute-voice")
    share.click()
    expect(share).to_have_text("Tap to share", timeout=40_000)
    share.click()
    expect(page.locator("#status")).to_have_text("Shared Bus stop.wav with your voice.")
    expect(share).to_have_text("Share the song")
    assert len(shares(page)) == 1


def test_nothing_to_share_says_so(studio):
    page = studio
    page.wait_for_function("!document.body.inert")
    page.evaluate(SHARE_STUB % "[]")
    page.click("#sharesong")
    expect(page.locator("#status")).to_have_text("Could not prepare the song: Nothing to hear yet: sing your idea or add some notes first.")
    assert shares(page) == []


def test_a_saved_song_file_opens_again_with_its_recordings_and_name(studio, browser, server_url, tmp_path):
    page = studio
    song_with_a_take(page, tmp_path)
    page.click("#mute-voice")
    path = download(page, "#savebundle", tmp_path)
    assert path.name == "Bus stop.tandem.zip"
    expect(page.locator("#status")).to_have_text("Saved Bus stop.tandem.zip with 1 recording.")
    with zipfile.ZipFile(path) as z:
        assert z.namelist() == ["tandem.json", "project.json", "original.wav"]
        assert json.loads(z.read("tandem.json"))["name"] == "Bus stop"
        project = json.loads(z.read("project.json"))
        original = z.read("original.wav")
    assert len(project["notes"]) == 8 and project["mix"] == {"voice": {"mute": False}}

    problems = []
    context, fresh = studio_page(browser, server_url, problems)
    try:
        open_bundle(fresh, path.name, path.read_bytes())
        expect(fresh.locator("#status")).to_have_text("Opened Bus stop with its recording.")
        expect(fresh.locator("#songname")).to_have_value("Bus stop")
        expect(fresh.locator("#notecount")).to_have_text("8 notes")
        expect(fresh.locator("#original")).to_be_enabled()
        expect(fresh.locator("#mute-voice")).to_have_attribute("aria-pressed", "false")
        links = wait_for_draft_audio(fresh, ["original"])
        assert links and links["original"]["id"] == hashlib.sha256(original).hexdigest()
        # Clearing the name clears it from the files too (review of #146): no name is kept behind the field.
        fresh.fill("#songname", "")
        fresh.dispatch_event("#songname", "change")
        with fresh.expect_download() as info:
            fresh.click("#exportmidi")
        assert info.value.suggested_filename == "Tandem song.mid"
        # A Tandem file without a name (an idea from the phone) names the song by its title, not the song before it.
        fresh.fill("#songname", "Bus stop")
        fresh.dispatch_event("#songname", "change")
        unnamed = io.BytesIO()
        with zipfile.ZipFile(path) as z, zipfile.ZipFile(unnamed, "w") as out:
            for item in z.namelist():
                data = z.read(item)
                out.writestr(item, json.dumps({"format": "tandem-bundle", "version": 1, "name": "", "savedAt": None}) if item == "tandem.json" else data)
        open_bundle(fresh, "Night drive.tandem.zip", unnamed.getvalue())
        expect(fresh.locator("#status")).to_contain_text("Opened Night drive with its recording.")
        expect(fresh.locator("#songname")).to_have_value("Night drive")
    finally:
        context.close()
    assert not problems, problems


def test_the_guided_share_step_shares_the_song_by_its_name_with_the_voice_chosen_there(browser, server_url):
    from test_guided import guided_page, record_take, use_server_transcriber
    with guided_page(browser, server_url, init=SHARE_STUB % "[]") as page:
        page.click('#steps [data-step="share"]')
        # Nothing recorded: no voice to choose, and the other formats are folded away.
        expect(page.locator("#gsharevoicerow")).to_be_hidden()
        expect(page.locator("#gsharesong")).to_be_visible()
        expect(page.locator('#gmoreapps [data-press="exportstems"]')).to_be_hidden()
        page.click('#steps [data-step="sing"]')
        use_server_transcriber(page)
        page.click('[data-mode="vocal"]')
        record_take(page)
        page.click('#steps [data-step="share"]')
        page.fill("#gsongname", "Bus stop")
        page.dispatch_event("#gsongname", "change")
        expect(page.locator("#songname")).to_have_value("Bus stop")
        # Singing with words is heard (UX.1); unticking With my voice mutes it as one edit.
        expect(page.locator("#gsharevoice")).to_be_checked()
        page.uncheck("#gsharevoice")
        expect(page.locator("#mute-voice")).to_have_attribute("aria-pressed", "true")
        expect(page.locator("#undo")).to_have_attribute("title", "Undo: Mute your voice")
        expect(page.locator("#gvoicein")).not_to_be_checked()
        page.click("#gsharesong")
        expect(page.locator("#status")).to_have_text(re.compile(r"Shared Bus stop\.wav without your voice\."), timeout=40_000)
        page.check("#gsharevoice")
        page.click("#gsharesong")
        expect(page.locator("#status")).to_have_text(re.compile(r"Shared Bus stop\.wav with your voice\."), timeout=40_000)
        assert [s["name"] for s in shares(page)] == ["Bus stop.wav", "Bus stop.wav"]
