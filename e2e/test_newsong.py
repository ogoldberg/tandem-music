"""SONG.2: New song and Try an example start from an empty song, the song before is kept as a version first,
and saving past the version limit asks before the oldest version goes."""
import json

from playwright.sync_api import expect

from test_guided import guided_page
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
