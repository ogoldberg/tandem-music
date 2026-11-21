"""SONG.2: New song and Try an example start from an empty song, the song before is kept as a version first,
and saving past the version limit asks before the oldest version goes."""
import json

import pytest
from playwright.sync_api import expect

from test_guided import guided_page
from test_practice import practice_page, sharp_browser  # noqa: F401 (fixtures)
from test_studio import IDB_GET, draft_audio, import_recording, tone_wav, wait_for_draft_audio, wait_until

FULL_SONG = {
    "format": "tandem-project", "version": 1, "bpm": 92, "instrument": "flute", "melody_locked": True,
    "notes": [{"m": 64, "t": 0, "d": 0.5}, {"m": 67, "t": 0.6, "d": 0.5}],
    "drums": [{"k": "kick", "t": 0}, {"k": "snare", "t": 0.65}],
    "harmony": [{"m": 48, "t": 0, "d": 1.2}, {"m": 52, "t": 0, "d": 1.2}], "harmony_instrument": "organ",
    "voice2": [{"m": 67, "t": 0, "d": 0.5}], "voice2_instrument": "strings",
    "lyrics": "hel-lo there", "genre": "rock",
    "sections": [{"name": "Verse", "from": 0, "to": 1.3}],
    "mix": {"drums": {"level": -6}},
}
OLD_PARTS = ["notes", "drums", "harmony", "voice2", "lyrics", "genre", "sections", "mix", "takes", "layers"]


def draft(page):
    return page.evaluate(IDB_GET, "draft")


def open_full_song_with_a_recording(page, tmp_path):
    import_recording(page, tone_wav(tmp_path / "take.wav"))
    wait_for_draft_audio(page, ["original"])
    song = tmp_path / "song.json"
    song.write_text(json.dumps(FULL_SONG))
    page.set_input_files("#projectfile", str(song))
    expect(page.locator("#status")).to_have_text("Project opened")
    page.fill("#songname", "Old song")
    page.locator("#songname").dispatch_event("change")
    wait_until(page, f"async () => (await ({IDB_GET})('draft'))?.lyrics === 'hel-lo there'", "the full song is the draft")


def assert_nothing_old(page, d):
    for key in OLD_PARTS:
        value = d.get(key)
        assert not value, f"{key} is left from the old song: {value!r}"
    assert d["bpm"] != 92 and d["instrument"] != "flute"
    assert (d.get("harmony_instrument") or "piano") == "piano" and (d.get("voice2_instrument") or "piano") == "piano"
    wait_until(page, f"async () => Object.keys(await ({IDB_GET})('draft-audio') || {{}}).length === 0", "the draft links no recording")
    expect(page.locator("#original")).to_be_disabled()
    expect(page.locator("#songname")).to_have_value("")
    expect(page.locator("#lyrics")).to_have_value("")
    expect(page.locator("#harmonyroll .note, #voice2roll .note")).to_have_count(0)


def test_new_song_keeps_the_old_song_as_a_version_and_leaves_nothing_of_it(studio, tmp_path):
    page = studio
    open_full_song_with_a_recording(page, tmp_path)
    page.click("#newsong")
    expect(page.locator("#status")).to_have_text(
        'New song: sing, play or type to start. Your previous draft was saved as the version "Before a new song".')
    wait_until(page, f"async () => (await ({IDB_GET})('draft'))?.notes?.length === 0", "the draft is the new song")
    d = draft(page)
    assert_nothing_old(page, d)
    assert d["bpm"] == 100 and d["notes"] == [] and d["drums"] == []
    expect(page.locator("#melodyroll .note")).to_have_count(0)
    stored = page.evaluate(IDB_GET, "versions")
    assert [(v["name"], v.get("auto")) for v in stored] == [("Before a new song", True)]
    assert stored[0]["project"]["lyrics"] == "hel-lo there" and stored[0]["audio"]["original"]

    # The kept version brings the old song back with its recording.
    page.click("#versionlist .version:has-text('Before a new song') >> text=Restore")
    expect(page.locator("#status")).to_have_text("Restored version: Before a new song")
    wait_until(page, f"async () => (await ({IDB_GET})('draft'))?.lyrics === 'hel-lo there'", "the old song is back")
    assert draft_audio(page)["original"]["id"] == stored[0]["audio"]["original"]["id"]
    expect(page.locator("#original")).to_be_enabled()

    # An empty song is not kept again.
    page.click("#newsong")
    page.click("#newsong")
    expect(page.locator("#status")).to_have_text("New song: sing, play or type to start.")
    assert len(page.evaluate(IDB_GET, "versions")) == 1, "the restored song was unchanged, so it was not kept twice"


def test_try_an_example_replaces_every_part_of_the_song_before(studio, tmp_path):
    page = studio
    open_full_song_with_a_recording(page, tmp_path)
    page.click("#demo")
    expect(page.locator("#status")).to_have_text(
        'Example loaded — press Play. Your previous draft was saved as the version "Before the example".')
    wait_until(page, f"async () => (await ({IDB_GET})('draft'))?.instrument === 'marimba'", "the draft is the example")
    d = draft(page)
    assert len(d["notes"]) == 8 and len(d["drums"]) == 16
    assert_nothing_old(page, {**d, "notes": [], "drums": [], "bpm": 0, "instrument": "marimba"})
    expect(page.locator("#melodyroll .note")).to_have_count(8)
    # The unchanged example is not kept again when it is loaded again.
    page.click("#demo")
    expect(page.locator("#status")).to_have_text("Example loaded — press Play")
    assert [v["name"] for v in page.evaluate(IDB_GET, "versions")] == ["Before the example"]
    # Nor by New song: the unchanged example can be had again with one tap.
    page.click("#newsong")
    expect(page.locator("#status")).to_have_text("New song: sing, play or type to start.")
    assert [v["name"] for v in page.evaluate(IDB_GET, "versions")] == ["Before the example"]


def seed_versions(page, count):
    """Writes `count` saved versions straight into the store, oldest last, as if saved one by one."""
    page.evaluate("""count => new Promise((resolve, reject) => {
      const open = indexedDB.open('tandem');
      open.onerror = () => reject(open.error);
      open.onsuccess = () => {
        const db = open.result, tx = db.transaction('kv', 'readwrite');
        const project = { format: 'tandem-project', version: 1, bpm: 100, instrument: 'piano', melody_locked: true,
          notes: [], drums: [], harmony: [], harmony_instrument: 'piano' };
        const list = Array.from({ length: count }, (_, i) => ({ id: String(1700000000000 + count - i), name: 'Old ' + (count - i),
          savedAt: 1700000000000 + (count - i) * 1000, project }));
        list.push({ id: '1600000000000', name: 'Before the beat', savedAt: 1600000000000, project, auto: true });
        tx.objectStore('kv').put(list, 'versions');
        tx.oncomplete = () => { db.close(); resolve(); };
        tx.onerror = () => reject(tx.error);
      };
    })""", count)


def test_the_oldest_version_is_kept_until_its_removal_is_confirmed(studio):
    page = studio
    seed_versions(page, 50)
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    expect(page.locator("#versionlist .version")).to_have_count(51)
    page.click("#demo")
    expect(page.locator("#versionlist .version")).to_have_count(51)

    page.fill("#versionname", "Number 51")
    page.click("#saveversion")
    expect(page.locator("#versionfull")).to_be_visible()
    expect(page.locator("#versionfull")).to_have_attribute("data-oldest", "Old 1")
    expect(page.locator("#versionfulltext")).to_contain_text('You have 50 versions saved on this device. Saving another removes the oldest, "Old 1".')
    names = [v["name"] for v in page.evaluate(IDB_GET, "versions")]
    assert len(names) == 51 and "Old 1" in names and "Number 51" not in names

    page.click("#versionkeep")
    expect(page.locator("#versionfull")).to_be_hidden()
    expect(page.locator("#status")).to_have_text("Not saved: every version is kept.")
    assert len(page.evaluate(IDB_GET, "versions")) == 51

    page.click("#saveversion")
    expect(page.locator("#versionfull")).to_be_visible()
    page.click("#versionreplace")
    expect(page.locator("#status")).to_have_text("Saved version: Number 51")
    expect(page.locator("#versionfull")).to_be_hidden()
    expect(page.locator("#versionname")).to_have_value("")
    names = [v["name"] for v in page.evaluate(IDB_GET, "versions")]
    assert names[0] == "Number 51" and "Old 1" not in names and "Old 2" in names and "Before the beat" in names
    assert len(names) == 51


def test_the_guided_view_starts_a_new_song_and_asks_before_the_oldest_version_goes(browser, server_url):
    with guided_page(browser, server_url) as page:
        page.click("#gdemo")
        page.locator("#lyrics").fill("la la la")
        page.locator("#lyrics").blur()
        wait_until(page, f"async () => (await ({IDB_GET})('draft'))?.lyrics === 'la la la'", "the words are kept")
        page.click('#steps [data-step="sing"]')
        page.click("#gnewsong")
        expect(page.locator("#gstatus")).to_contain_text('Your previous draft was saved as the version "Before a new song".')
        wait_until(page, f"async () => (await ({IDB_GET})('draft'))?.notes?.length === 0", "the draft is the new song")
        seed_versions(page, 50)
        page.reload()
        page.click('#steps [data-step="share"]')
        page.fill("#gversionname", "One more")
        page.click("#gsaveversion")
        expect(page.locator("#gversionfull")).to_be_visible()
        expect(page.locator("#gversionfulltext")).to_contain_text('removes the oldest, "Old 1"')
        page.click("#gversionfull button[data-press=versionreplace]")
        expect(page.locator("#gversionfull")).to_be_hidden()
        expect(page.locator("#gversionname")).to_have_value("")
        names = [v["name"] for v in page.evaluate(IDB_GET, "versions")]
        assert names[0] == "One more" and "Old 1" not in names and len(names) == 51


def test_new_song_and_the_example_wait_until_the_take_being_recorded_is_stopped(studio):
    # Review of #147: a take stopped after New song would land in the new, empty song.
    page = studio
    page.uncheck("#countin")
    page.click("#record")
    expect(page.locator("#status")).to_have_text("Recording…", timeout=8000)
    for button in ["#newsong", "#demo"]:
        page.click(button)
        expect(page.locator("#status")).to_have_text("Stop recording first: the take belongs to the song you are recording it into.")
    expect(page.locator("#notecount")).not_to_have_text("8 notes")
    page.click("#finish")
    expect(page.locator("#original")).to_be_enabled()
    assert page.evaluate(IDB_GET, "versions") is None, "nothing was kept, because nothing was replaced"
    page.click("#newsong")
    expect(page.locator("#status")).to_contain_text("New song: sing, play or type to start.")
    expect(page.locator("#original")).to_be_disabled()


# FIX.10 (review of #147): a keyboard take or a practice run under way stays with its song, and Record pressed while
# New song keeps the song before waits for it, so the take is not unloaded with the old song.
KEYS_FIRST = "Stop recording from the keyboard first: the notes you play belong to the song you are playing them into."
PRACTICE_FIRST = "Stop practising first: the pass you are singing belongs to the song you are practising."


def test_new_song_and_the_example_wait_until_the_keyboard_take_is_stopped(page, server_url):
    import time
    from test_midi import MOCK_MIDI, connect, open_studio
    problems = open_studio(page, server_url, MOCK_MIDI)
    page.click("#demo")
    page.fill("#bpm", "150")
    page.locator("#bpm").dispatch_event("change")
    connect(page)
    page.click("#midirecord")
    expect(page.locator("#status")).to_contain_text("Recording from Test Keys")
    for button in ["#newsong", "#demo"]:
        page.click(button)
        expect(page.locator("#status")).to_have_text(KEYS_FIRST)
    time.sleep(1.6 + 0.3)  # past the one-bar count-in at 150 BPM
    page.evaluate("window.__midiKey([0x90, 72, 100])")
    time.sleep(0.3)
    page.evaluate("window.__midiKey([0x80, 72, 0])")
    page.click("#midirecord")
    expect(page.locator("#status")).to_have_text("Recorded 1 note from the MIDI keyboard into the melody")
    expect(page.locator("#notecount")).to_have_text("9 notes")
    wait_until(page, f"async () => (await ({IDB_GET})('draft'))?.notes?.length === 9", "the take is in the example's draft")
    assert page.evaluate(IDB_GET, "versions") is None, "nothing was replaced, so nothing was kept"
    page.click("#newsong")
    expect(page.locator("#status")).to_contain_text("New song: sing, play or type to start.")
    assert [len(v["project"]["notes"]) for v in page.evaluate(IDB_GET, "versions")] == [9]
    assert not problems, problems


@pytest.mark.parametrize("starting", [False, True], ids=["practising", "starting"])
def test_new_song_and_the_example_wait_until_practising_stops(practice_page, starting):
    from test_practice import GATE_MIC, with_melody
    page = practice_page
    with_melody(page)
    page.uncheck("#countin")
    if starting:
        page.evaluate(GATE_MIC)  # Practise waits for the microphone: still starting.
    page.click("#practice")
    if not starting:
        expect(page.locator("#practice")).to_have_attribute("aria-pressed", "true", timeout=8000)
    for button in ["#newsong", "#demo"]:
        page.click(button)
        expect(page.locator("#status")).to_have_text(PRACTICE_FIRST)
    if starting:
        page.evaluate("() => window.__openMic()")
        expect(page.locator("#practice")).to_have_attribute("aria-pressed", "true", timeout=8000)
    expect(page.locator("#notecount")).to_have_text("4 notes")
    page.click("#practicestop")
    assert page.evaluate(IDB_GET, "versions") is None, "the song being practised was not replaced"
    assert len(draft(page)["notes"]) == 4


HOLD_RECORDINGS = """() => new Promise(held => navigator.locks.request('tandem-recordings', {mode: 'exclusive'},
  () => new Promise(release => { window.__releaseRecordings = release; held(); })))"""


def test_record_pressed_while_new_song_keeps_the_song_before_waits_for_it(studio):
    page = studio
    page.uncheck("#countin")
    page.click("#demo")
    page.fill("#bpm", "120")
    page.locator("#bpm").dispatch_event("change")
    wait_until(page, f"async () => (await ({IDB_GET})('draft'))?.bpm === 120", "the changed example is the draft")
    # Keeping the song before as a version waits on the recordings lock, held here until released.
    page.evaluate(HOLD_RECORDINGS)
    page.click("#newsong")
    page.click("#practice")
    expect(page.locator("#status")).to_have_text("Wait a moment: the song before is still being kept as a version.")
    expect(page.locator("#practice")).to_have_attribute("aria-pressed", "false")
    page.click("#record")
    expect(page.locator("#status")).to_have_text("Recording once the song before is kept…")
    page.wait_for_timeout(1500)
    expect(page.locator("#finish")).to_be_disabled()
    assert page.evaluate(IDB_GET, "versions") is None
    page.evaluate("() => window.__releaseRecordings()")
    expect(page.locator("#status")).to_have_text("Recording…", timeout=8000)
    page.click("#finish")
    expect(page.locator("#original")).to_be_enabled()
    wait_for_draft_audio(page, ["original"])
    d = draft(page)
    assert d["bpm"] == 100 and d["notes"] == [], "the take is in the new song"
    stored = page.evaluate(IDB_GET, "versions")
    assert [(v["name"], v["project"]["bpm"], v.get("audio")) for v in stored] == [("Before a new song", 120, None)]


FAIL_VERSIONS = """() => { const put = IDBObjectStore.prototype.put;
  IDBObjectStore.prototype.put = function (value, key) {
    if (key === 'versions') throw new DOMException('The disk is full', 'QuotaExceededError');
    return put.call(this, value, key);
  }; }"""


def test_record_pressed_while_new_song_fails_does_not_record_into_the_song_before(studio):
    """UX.3 (PR #151's P3): when keeping the song before fails, New song says why and Record, which was waiting for
    it, does not start a take in the song that was not replaced."""
    page = studio
    page.uncheck("#countin")
    page.click("#demo")
    page.fill("#bpm", "120")
    page.locator("#bpm").dispatch_event("change")
    wait_until(page, f"async () => (await ({IDB_GET})('draft'))?.bpm === 120", "the changed example is the draft")
    page.evaluate(HOLD_RECORDINGS)
    page.click("#newsong")
    page.click("#record")
    expect(page.locator("#status")).to_have_text("Recording once the song before is kept…")
    page.evaluate(FAIL_VERSIONS)
    page.evaluate("() => window.__releaseRecordings()")
    expect(page.locator("#status")).to_contain_text("The disk is full")
    page.wait_for_timeout(1500)
    expect(page.locator("#finish")).to_be_disabled()
    expect(page.locator("#status")).to_contain_text("The disk is full")
    assert draft(page)["bpm"] == 120, "the song before is still the song"
