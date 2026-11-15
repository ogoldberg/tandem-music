"""SONG.1: song sections in a real Chromium: mark a chorus on the Timeline, repeat it, undo, move and delete.

The example project is at 100 bpm (a beat is 0.6 s): 8 melody notes 0.45 s apart and 16 drum hits 0.225 s apart.
A drag from 1.2 s to 2.4 s marks beats 3 and 4 (snapped to the beat), holding the melody notes at 1.35, 1.8
and 2.25 s and the five drum hits from 1.35 to 2.25 s.
"""
import json

from playwright.sync_api import expect

from test_playhead import drag_loop
from test_studio import wait_until


def sections(page):
    raw = page.locator("#sections").get_attribute("data-sections")
    return json.loads(raw) if raw else []


def mark(page, name, a, b):
    drag_loop(page, a, b)
    page.select_option("#sectionname", name)
    page.click("#marksection")


def test_a_chorus_is_marked_repeated_undone_moved_and_deleted_across_every_note_part(studio):
    page = studio
    page.click("#demo")
    expect(page.locator("#sections")).to_be_hidden()
    expect(page.locator("#marksection")).to_be_disabled()

    mark(page, "Verse", 0, 1.2)
    mark(page, "Chorus", 1.2, 2.4)
    assert sections(page) == [{"name": "Verse", "from": 0, "to": 1.2}, {"name": "Chorus", "from": 1.2, "to": 2.4}]
    expect(page.locator(".secblock")).to_have_text(["Verse", "Chorus"])
    # The section just marked is chosen, so its tools are offered.
    expect(page.locator('.secblock[data-section="1"]')).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#sectionedit")).to_be_visible()
    expect(page.locator("#sectionlater")).to_be_disabled()

    page.click("#sectionrepeat")
    expect(page.locator("#notecount")).to_have_text("11 notes")
    expect(page.locator("#hitcount")).to_have_text("21 hits")
    assert [s["name"] for s in sections(page)] == ["Verse", "Chorus", "Chorus"]
    assert sections(page)[2] == {"name": "Chorus", "from": 2.4, "to": 3.6}
    expect(page.locator("#status")).to_contain_text("Repeat Chorus")
    # The copy is chosen and marked on the Timeline, so Play loops it.
    expect(page.locator('.secblock[data-section="2"]')).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#timeinfo")).to_contain_text("Section 2.4 to 3.6 s")

    page.click("#undo")
    expect(page.locator("#notecount")).to_have_text("8 notes")
    expect(page.locator("#hitcount")).to_have_text("16 hits")
    assert [s["name"] for s in sections(page)] == ["Verse", "Chorus"]
    expect(page.locator("#sectionedit")).to_be_hidden()
    page.click("#redo")
    expect(page.locator("#notecount")).to_have_text("11 notes")

    # Move the verse after the first chorus: the chorus's first note (1.35 s) now starts the song at 0.15 s.
    page.click('.secblock[data-section="0"]')
    expect(page.locator("#sectionearlier")).to_be_disabled()
    page.click("#sectionlater")
    assert [s["name"] for s in sections(page)] == ["Chorus", "Verse", "Chorus"]
    first = page.evaluate("() => Math.min(...JSON.parse(document.getElementById('sections').dataset.sections).map(s => s.from))")
    assert first == 0
    expect(page.locator("#notecount")).to_have_text("11 notes")

    # Delete the last chorus: its three notes and five hits go.
    page.click('.secblock[data-section="2"]')
    page.click("#sectiondelete")
    expect(page.locator("#notecount")).to_have_text("8 notes")
    expect(page.locator("#hitcount")).to_have_text("16 hits")
    assert [s["name"] for s in sections(page)] == ["Chorus", "Verse"]

    # The sections are part of the draft: they are back after a reload.
    wait_until(page, """async () => { const db = await new Promise(r => { const q = indexedDB.open('tandem'); q.onsuccess = () => r(q.result) });
        const d = await new Promise(r => { const q = db.transaction('kv').objectStore('kv').get('draft'); q.onsuccess = () => r(q.result) });
        db.close(); return !!(d && d.sections && d.sections.length === 2) }""", "the draft keeps the sections")
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    expect(page.locator(".secblock")).to_have_text(["Chorus", "Verse"])
    expect(page.locator("#notecount")).to_have_text("8 notes")


def test_a_section_cannot_overlap_another(studio):
    page = studio
    page.click("#demo")
    mark(page, "Chorus", 1.2, 2.4)
    mark(page, "Bridge", 1.8, 3.0)
    expect(page.locator("#status")).to_contain_text("overlaps Chorus")
    assert [s["name"] for s in sections(page)] == ["Chorus"]
