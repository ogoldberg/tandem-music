"""SILENT.1: see each melody note against the chord under it, in a real Chromium. Fit is off by default; turned on, every
melody note is coloured as a chord tone, in the key or outside the key, a phrase ending on I or V is marked, and an
edit to a note changes its colour at once. It also shows in the guided Notes step.

The example project is at 100 bpm (a 2.4 s bar): 8 melody notes 0.45 s apart (60 64 67 69 67 64 62 60), in C major.
"""
from playwright.sync_api import expect

from conftest import show_part
from test_guided import guided_page

NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
C_MAJOR = {0, 2, 4, 5, 7, 9, 11}


def fits(page):
    return page.eval_on_selector_all("#melodyroll .note", "els => els.map(b => b.dataset.fit ?? null)")


def chord_tones(name):
    """Pitch classes of a major or minor triad named like the chord strip does (C, Am, F#m)."""
    minor = name.endswith("m")
    root = NAMES.index(name[:-1] if minor else name)
    return {root, (root + (3 if minor else 4)) % 12, (root + 7) % 12}


def test_fit_colours_the_melody_on_its_chords_marks_phrase_endings_and_follows_an_edit(studio):
    page = studio
    page.click("#demo")
    show_part(page, "melody")
    # Off by default: no colours, no marks, no summary.
    expect(page.locator("#melodyfit")).to_have_attribute("aria-pressed", "false")
    assert fits(page) == [None] * 8
    expect(page.locator("#melodyroll")).not_to_have_class("fit")
    expect(page.locator("#melodyfitinfo")).to_be_hidden()

    # On with no chords part: every note of the example is in C major, none can be a chord tone yet.
    show_part(page, "harmony")
    page.select_option("#harmonykey", "0:major")
    show_part(page, "melody")
    page.click("#melodyfit")
    expect(page.locator("#melodyfit")).to_have_attribute("aria-pressed", "true")
    assert fits(page) == ["key"] * 8
    expect(page.locator("#melodyfitinfo")).to_have_text(
        "0 chord tones, 8 in the key, 0 outside the key. No chords under the melody yet: make chords to see chord tones and phrase endings.")
    assert page.locator("#melodyroll .cadence").count() == 0

    # Make chords in C major; each note is then read against the chord the strip shows over it.
    show_part(page, "harmony")
    page.select_option("#harmonystyle", "chords")
    page.click("#genharmony")
    expect(page.locator("#status")).to_contain_text("in C major")
    chords = page.eval_on_selector_all("#chordstrip .chordsym", "els => els.map(b => [b.dataset.name, Number(b.dataset.t)])")
    assert chords and all(n.rstrip("m") in NAMES for n, _ in chords)
    starts = [0.45 * i for i in range(8)]
    pitches = [60, 64, 67, 69, 67, 64, 62, 60]

    def under(t):
        return [n for n, s in chords if s <= t + 1e-6][-1]

    expected = ["chord" if p % 12 in chord_tones(under(t)) else "key" if p % 12 in C_MAJOR else "outside" for p, t in zip(pitches, starts)]
    show_part(page, "melody")
    assert fits(page) == expected
    assert "chord" in expected
    note = page.locator('#melodyroll .note[data-i="1"]')
    expect(note).to_have_attribute("title", f"MIDI 64 at 0.45s, a chord tone (over {under(0.45)})")
    # The notes are one phrase; it ends over the last chord: home on I over C, open on V over G, else no mark.
    last = under(starts[-1])
    marks = page.eval_on_selector_all("#melodyroll .cadence", "els => els.map(m => [m.dataset.kind, m.textContent])")
    assert marks == ([["tonic", "I"]] if last == "C" else [["dominant", "V"]] if last == "G" else [])

    # An edit updates the colours: E (a chord tone of C) up a semitone is F, in the key but not in C; down two is E flat.
    assert under(0.45) == "C"
    note.click()
    page.keyboard.press("Alt+ArrowUp")
    expect(note).to_have_attribute("data-fit", "key")
    expect(note).to_have_attribute("title", "MIDI 65 at 0.45s, in the key, not in the chord (over C)")
    page.keyboard.press("Alt+ArrowDown")
    page.keyboard.press("Alt+ArrowDown")
    expect(note).to_have_attribute("data-fit", "outside")
    expect(page.locator("#melodyfitinfo")).to_contain_text("1 outside the key")
    page.click("#undo")
    page.click("#undo")
    page.click("#undo")
    expect(note).to_have_attribute("data-fit", "chord")

    # Off again: the roll is as before.
    page.click("#melodyfit")
    assert fits(page) == [None] * 8
    expect(page.locator("#melodyfitinfo")).to_be_hidden()


def test_fit_shows_in_the_guided_notes_step(browser, server_url):
    with guided_page(browser, server_url) as page:
        page.click("#gdemo")
        page.click('#steps [data-step="notes"]')
        fit = page.locator("#slot-roll #melodyfit")
        expect(fit).to_be_visible()
        fit.click()
        expect(page.locator("#slot-roll #melodyfitinfo")).to_contain_text("8 in the key")
        assert page.eval_on_selector_all("#melodyroll .note", "els => els.every(b => b.dataset.fit === 'key')")
