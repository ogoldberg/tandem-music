"""CHORD.1: chord symbols above the chords roll in a real Chromium: generate chords, see their names above the roll
where their notes are, change one (its notes follow, as one edit), undo and redo; and a bass line follows a chord the
key would not give.

The example project is at 100 bpm (a 2.4 s bar): 8 melody notes 0.45 s apart (60 64 67 69 67 64 62 60), in C major.
"""
import re

from playwright.sync_api import expect

from conftest import show_part


def strip(page):
    """The chord symbols above the chords roll, in time order: (name, start)."""
    return page.eval_on_selector_all("#chordstrip .chordsym", "els => els.map(b => [b.dataset.name, Number(b.dataset.t)])")


def harmony_notes(page):
    return page.eval_on_selector_all("#harmonyroll .note", "els => els.map(b => b.title)")


def generate(page, style):
    show_part(page, "harmony")
    page.select_option("#harmonystyle", style)
    page.select_option("#harmonykey", "0:major")
    page.click("#genharmony")
    expect(page.locator("#status")).to_contain_text("in C major")


def test_chords_show_above_the_roll_and_changing_one_moves_its_notes_as_one_edit(studio):
    page = studio
    page.click("#demo")
    expect(page.locator("#chordstrip")).to_be_hidden()
    generate(page, "chords")
    # The symbols are the chords Generate made (its status lists them), one a bar from the first note.
    made = page.locator("#status").inner_text().split(": ", 1)[1].split()
    assert [n for n, _ in strip(page)] == made
    assert [t for _, t in strip(page)] == [0, 2.4][: len(made)]
    # A symbol starts where its chord's notes start in the roll below.
    first = page.locator("#chordstrip .chordsym").first.bounding_box()
    note = page.locator("#harmonyroll .note").first.bounding_box()
    assert abs(first["x"] - note["x"]) <= 1.5

    before = harmony_notes(page)
    expect(page.locator("#chordroot")).to_be_disabled()
    page.locator("#chordstrip .chordsym").first.click()
    expect(page.locator("#chordstrip .chordsym").first).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#chordinfo")).to_have_text(f"{made[0]} from 0.0 to 2.4 s is chosen.")
    expect(page.locator("#chordroot")).to_be_enabled()
    # The key's chords are offered too; the chosen chord's is marked.
    expect(page.locator("#chordkeypicks button")).to_have_text(["C", "Dm", "Em", "F", "G", "Am"])
    expect(page.locator(f'#chordkeypicks button[aria-pressed="true"]')).to_have_text(made[0])

    page.locator("#chordkeypicks button", has_text=re.compile("^Am$")).click()
    expect(page.locator("#undo")).to_have_attribute("title", f"Undo: Change chord {made[0]} to Am")
    assert [n for n, _ in strip(page)] == ["Am"] + made[1:]
    after = harmony_notes(page)
    assert after != before
    # Only the first bar's notes changed; the chord stays chosen, so it can be changed again.
    assert after[3:] == before[3:]
    expect(page.locator("#chordstrip .chordsym").first).to_have_attribute("aria-pressed", "true")

    page.select_option("#chordquality", "dom7")
    expect(page.locator("#undo")).to_have_attribute("title", "Undo: Change chord Am to A7")
    assert strip(page)[0][0] == "A7"
    assert len(harmony_notes(page)) == len(before) + 1

    page.click("#undo")
    assert strip(page)[0][0] == "Am"
    assert harmony_notes(page) == after
    page.click("#undo")
    assert [n for n, _ in strip(page)] == made
    assert harmony_notes(page) == before
    page.click("#redo")
    assert strip(page)[0][0] == "Am"

    # The roll's own edits change the symbols too: delete the first bar's notes and its chord goes.
    page.click("#harmonyall")
    page.click("#harmonydelete")
    expect(page.locator("#chordstrip")).to_be_hidden()
    expect(page.locator("#chordinfo")).to_have_text("No chords yet: generate them, or add notes to the chords part.")


def test_a_bass_line_follows_a_chord_from_outside_the_key(studio):
    page = studio
    page.click("#demo")
    generate(page, "bass")
    made = page.locator("#status").inner_text().split(": ", 1)[1].split()
    assert [n for n, _ in strip(page)] == made
    page.locator("#chordstrip .chordsym").first.click()
    page.select_option("#chordroot", "2")
    page.select_option("#chordquality", "major")
    # D major is not a chord of C major: the bass plays its F sharp, so the notes read as D, not Dm.
    expect(page.locator("#chordstrip .chordsym").first).to_have_attribute("data-name", "D")
    assert "MIDI 38 at 0s" in harmony_notes(page)
    assert any(t.startswith("MIDI 42 ") for t in harmony_notes(page))
