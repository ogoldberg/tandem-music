"""SILENT.2: draw a melody as a line on the roll, in a real Chromium. With Draw line on, a stroke drawn with the mouse
is previewed as notes in the key on the grid, in place of the melody notes in its span; Keep makes it one edit that
Undo takes back, and Cancel leaves the melody as it was.

The example project is at 100 bpm (grid 1/8: 0.3 s steps): 8 melody notes 0.45 s apart (60 64 67 69 67 64 62 60).
"""
import json

from playwright.sync_api import expect

from conftest import show_part


def melody(page):
    return page.eval_on_selector_all("#melodyroll .note", "els => els.map(b => b.title)")


def draw_staircase(page):
    """Hold G from 1.8 s to 2.4 s, step straight down to C and hold it to 3.6 s, at the rows of the example's G and C."""
    roll = page.locator("#melodyroll")
    roll.scroll_into_view_if_needed()
    c = page.locator('#melodyroll .note[data-i="0"]').bounding_box()
    c2 = page.locator('#melodyroll .note[data-i="1"]').bounding_box()
    g = page.locator('#melodyroll .note[data-i="2"]').bounding_box()
    per_second = (c2["x"] - c["x"]) / 0.45

    def x(t):
        return c["x"] + t * per_second

    yc, yg = c["y"] + c["height"] / 2, g["y"] + g["height"] / 2
    page.mouse.move(x(1.8), yg)
    page.mouse.down()
    page.mouse.move(x(2.4), yg, steps=25)
    page.mouse.move(x(2.41), yc, steps=2)
    page.mouse.move(x(3.6), yc, steps=40)
    page.mouse.up()


def test_draw_line_previews_notes_in_the_key_keeps_them_as_one_edit_and_undoes(studio):
    page = studio
    page.click("#demo")
    show_part(page, "harmony")
    page.select_option("#harmonykey", "0:major")
    show_part(page, "melody")
    before = melody(page)
    assert len(before) == 8

    expect(page.locator("#melodyline")).to_have_attribute("aria-pressed", "false")
    page.click("#melodyline")
    expect(page.locator("#melodyline")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#lineinfo")).to_have_text("Draw a line through the roll from left to right.")
    draw_staircase(page)

    # The preview: the line itself, and its notes (marked) in place of the four notes from 1.8 s on; nothing kept yet.
    expect(page.locator("#linebar")).to_be_visible()
    assert page.locator("#melodyroll svg.drawline polyline").count() == 1
    drawn = json.loads(page.locator("#lineinfo").get_attribute("data-notes"))
    assert drawn == [{"m": 67, "t": 1.8, "d": 0.6}, {"m": 60, "t": 2.4, "d": 1.2}]
    expect(page.locator("#lineinfo")).to_have_text("2 notes in C major, in place of 4 of the melody. Keep it or cancel it.")
    assert melody(page) == before[:4] + ["MIDI 67 at 1.8s", "MIDI 60 at 2.4s"]
    assert page.locator("#melodyroll .note.drawn").count() == 2

    # Cancel: the melody is as it was, and there is nothing to undo from the line.
    page.click("#linecancel")
    expect(page.locator("#linebar")).to_be_hidden()
    assert melody(page) == before
    assert page.locator("#melodyroll svg.drawline").count() == 0

    # Draw it again and keep it: one edit, the drawn notes selected.
    draw_staircase(page)
    page.click("#linekeep")
    expect(page.locator("#status")).to_contain_text("Draw a melody line of 2 notes")
    expect(page.locator("#linebar")).to_be_hidden()
    assert melody(page) == before[:4] + ["MIDI 67 at 1.8s", "MIDI 60 at 2.4s"]
    assert page.locator("#melodyroll .note.drawn").count() == 0
    sel = page.eval_on_selector_all("#melodyroll .note.sel", "els => els.map(b => Number(b.dataset.i))")
    assert sel == [4, 5]

    # One Undo takes the whole line back.
    page.click("#undo")
    expect(page.locator("#melodyroll .note")).to_have_count(8)
    assert melody(page) == before


def test_draw_line_asks_for_a_key_when_there_is_none(studio):
    page = studio
    show_part(page, "melody")
    page.click("#melodyline")
    box = page.locator("#melodyroll").bounding_box()
    page.mouse.move(box["x"] + 20, box["y"] + 40)
    page.mouse.down()
    page.mouse.move(box["x"] + 200, box["y"] + 40, steps=10)
    page.mouse.up()
    expect(page.locator("#lineinfo")).to_contain_text("Choose a key in the harmony key menu")
    expect(page.locator("#melodyroll .note")).to_have_count(0)
    # With a key chosen the same stroke makes notes.
    show_part(page, "harmony")
    page.select_option("#harmonykey", "9:minor")
    show_part(page, "melody")
    box = page.locator("#melodyroll").bounding_box()
    page.mouse.move(box["x"] + 20, box["y"] + 40)
    page.mouse.down()
    page.mouse.move(box["x"] + 200, box["y"] + 40, steps=10)
    page.mouse.up()
    expect(page.locator("#linebar")).to_be_visible()
    page.click("#linekeep")
    notes = page.eval_on_selector_all("#melodyroll .note", "els => els.map(b => Number(b.title.split(' ')[1]))")
    assert len(notes) == 1 and notes[0] % 12 in {9, 11, 0, 2, 4, 5, 7}
