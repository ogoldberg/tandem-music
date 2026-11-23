"""SHEET.1: the song sheet in a real Chromium: the song's name, key and speed, its sections, and the words with each chord
over the syllable sung when it starts; printed (and saved as a PDF) as the sheet alone; Esc closes it and keys pressed on
it do not reach the song; the guided Share step opens it too.

The song is at 120 bpm (a 0.5 s beat, a 2 s bar) in C major: a bar of C alone, then the verse "Here we go now / on and
on _ we" over C, G and Am, and a chorus of one word with no chords.
"""
import json

from playwright.sync_api import expect

from test_guided import guided_page, open_view

C, G, Am = [48, 52, 55], [55, 59, 62], [57, 60, 64]
SONG = {
    "format": "tandem-project", "version": 1, "bpm": 120, "instrument": "piano", "melody_locked": True, "drums": [],
    # Words from 2 s: "Here we go now" a beat each, "on and on" from 4 s with "on" held over two notes, "we" at 7.5 s.
    "notes": [{"m": m, "t": t, "d": 0.45} for m, t in
              [(60, 2), (62, 2.5), (64, 3), (65, 3.5), (67, 4), (65, 4.5), (64, 5), (62, 5.5), (60, 7.5), (64, 8.5)]],
    "harmony": [{"m": m, "t": i * 2, "d": 1.9} for i, ch in enumerate([C, C, G, Am]) for m in ch],
    "lyrics": "Here we go now\non and on _ we\n\nsing",
    "sections": [{"name": "Verse", "from": 0, "to": 8}, {"name": "Chorus", "from": 8, "to": 10}],
}


def open_song(page, tmp_path, song=SONG):
    path = tmp_path / "song.json"
    path.write_text(json.dumps(song))
    page.set_input_files("#projectfile", str(path))
    expect(page.locator("#status")).to_have_text("Project opened")


def sheet_lines(page):
    """Each block's section and its lines, a chord written [X] before the syllable it is over."""
    return page.evaluate("""() => [...document.querySelectorAll('#sheet .sblock')].map(b => [b.dataset.section ?? null,
        [...b.querySelectorAll('.sline')].map(l => [l.dataset.kind, [...l.querySelectorAll('.seg')].map(s =>
          (s.dataset.chords ? '[' + s.dataset.chords + ']' : '') + s.querySelector('.syl').textContent + (s.classList.contains('joined') ? '' : ' ')).join('').trim()])])""")


def test_the_song_sheet_shows_the_words_with_the_chords_over_them_and_prints_alone(studio, tmp_path):
    page = studio
    open_song(page, tmp_path)
    page.fill("#songname", "On and on")
    page.locator("#songname").dispatch_event("change")
    page.click("#songsheet")
    expect(page.locator("#sheetview")).to_be_visible()
    expect(page.locator("#sheetprint")).to_be_focused()
    expect(page.locator("#status")).to_have_text("The song sheet is open: print it or save it as a PDF")
    expect(page.locator("#sheettitle")).to_have_text("On and on")
    expect(page.locator("#sheet .smeta")).to_have_text("C major · 120 bpm")
    assert sheet_lines(page) == [
        ["Verse", [
            # The first bar's C, a bar before the first word, is a line of chords; the second bar's C is the same chord
            # held on, so it is not written again over "Here".
            ["chords", "[C]"],
            ["words", "Here we go now"],
            # G at 4 s on "on"; Am at 6 s after the second "on" (5 s, held over the note at 5.5 s), before "we" on the same
            # line: over that "on".
            ["words", "[G]on and [Am]on we"],
        ]],
        ["Chorus", [["words", "sing"]]],
    ]
    # The chords line sits above the words: each chord's top is above its syllable's.
    tops = page.evaluate("""() => { const s = [...document.querySelectorAll('#sheet .seg[data-chords]')][1];
        return [s.querySelector('.chord').getBoundingClientRect().bottom, s.querySelector('.syl').getBoundingClientRect().top] }""")
    assert tops[0] <= tops[1] + 0.5
    page.screenshot(path=str(tmp_path / "sheet.png"))

    # Printed, only the sheet is on the page: the studio and the sheet's own buttons are not.
    page.evaluate("() => { window.printed = 0; window.print = () => { window.printed++ } }")
    page.click("#sheetprint")
    assert page.evaluate("() => window.printed") == 1
    page.emulate_media(media="print")
    expect(page.locator("#allcontrols")).to_be_hidden()
    expect(page.locator(".sheetbar")).to_be_hidden()
    expect(page.locator("#sheet")).to_be_visible()
    expect(page.locator("#sheet")).to_contain_text("Here")
    pdf = page.pdf()
    assert pdf.startswith(b"%PDF") and len(pdf) > 1000
    page.emulate_media(media="screen")

    # Keys pressed on the sheet, wherever the focus is, stay there: Undo does not change the song under it, Space does
    # not play it. Esc closes it.
    page.click("#sheet h1")
    page.keyboard.press("Control+z")
    page.keyboard.press("Space")
    page.wait_for_timeout(400)
    assert not page.get_attribute("#timeline", "data-t"), "Space played the song under the sheet"
    page.keyboard.press("Escape")
    expect(page.locator("#sheetview")).to_be_hidden()
    expect(page.locator("#songsheet")).to_be_focused()
    expect(page.locator("#lyrics")).to_have_value(SONG["lyrics"])
    # Printed with the sheet closed, the studio prints as before.
    page.emulate_media(media="print")
    expect(page.locator("#allcontrols")).to_be_visible()
    page.emulate_media(media="screen")

    # The sheet is drawn from the song as it is when it opens: a word changed shows the next time.
    page.fill("#lyrics", "Here we go then\non and on _ we\n\nsing")
    page.locator("#lyrics").blur()
    page.click("#songsheet")
    assert sheet_lines(page)[0][1][1] == ["words", "Here we go then"]
    page.click("#sheetclose")
    expect(page.locator("#sheetview")).to_be_hidden()


def test_with_neither_words_nor_chords_the_studio_says_so(studio, tmp_path):
    page = studio
    open_song(page, tmp_path, {**SONG, "harmony": [], "lyrics": "", "sections": []})
    page.click("#songsheet")
    expect(page.locator("#status")).to_have_text("Nothing for a song sheet yet: write the words or add chords first.")
    expect(page.locator("#sheetview")).to_be_hidden()


def test_the_guided_share_step_opens_the_song_sheet(browser, server_url):
    with guided_page(browser, server_url) as page:
        page.click("#gdemo")
        open_view(page, "words")
        page.fill("#lyrics", "Twin-kle twin-kle")
        page.locator("#lyrics").blur()
        page.click('#steps [data-step="share"]')
        page.click("#gsongsheet")
        expect(page.locator("#sheetview")).to_be_visible()
        # The example has no chords: the words alone.
        assert sheet_lines(page) == [[None, [["words", "Twinkle twinkle"]]]]
        page.click("#sheetclose")
        expect(page.locator("#sheetview")).to_be_hidden()
        # Closing it gives the focus back to the guided button that opened it, not the hidden studio one.
        expect(page.locator("#gsongsheet")).to_be_focused()
