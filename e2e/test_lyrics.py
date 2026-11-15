"""LYR.1: lyrics on the melody notes in a real Chromium: type the words, see each syllable under its note, undo,
edit the notes and see the words flow again, keep them across a reload and write them into Export MusicXML.

The example project is at 100 bpm: 8 melody notes 0.45 s apart (60 64 67 69 67 64 62 60).
"""
from playwright.sync_api import expect

from test_guided import guided_page
from test_studio import download, wait_until

WORDS = "Twin-kle twin-kle lit-tle _ star"


def roll_words(page):
    """The syllable shown on each melody note, in the roll's order (the example's notes are in time order)."""
    return page.eval_on_selector_all("#melodyroll .note", "els => els.map(b => b.querySelector('.lyric')?.textContent ?? null)")


def type_words(page, text):
    page.fill("#lyrics", text)
    # Leaving the box keeps the words as one edit.
    page.locator("#lyrics").blur()


def test_words_are_typed_onto_the_melody_shown_in_the_roll_undone_and_flow_after_a_note_edit(studio):
    page = studio
    page.click("#demo")
    assert roll_words(page) == [None] * 8
    expect(page.locator("#lyricsinfo")).to_have_text("")

    # While typing, the roll already shows the words, before anything is kept.
    page.fill("#lyrics", "Twin-kle")
    assert roll_words(page) == ["Twin-", "kle"] + [None] * 6
    expect(page.locator("#lyricsinfo")).to_have_text("2 syllables on the notes; 6 notes have no word.")
    type_words(page, WORDS)
    # One syllable a note; "_" holds "tle" over the seventh note, which shows a line, no word.
    assert roll_words(page) == ["Twin-", "kle", "twin-", "kle", "lit-", "tle", "", "star"]
    expect(page.locator("#lyricsinfo")).to_have_text("7 syllables on the notes.")
    expect(page.locator('#melodyroll .note[data-i="7"]')).to_have_attribute("title", "MIDI 60 at 3.15s, sung star")
    expect(page.locator('#melodyroll .note[data-i="6"]')).to_have_attribute("data-lyric", "_")
    expect(page.locator("#undo")).to_have_attribute("title", "Undo: Words")

    page.click("#undo")
    expect(page.locator("#lyrics")).to_have_value("")
    assert roll_words(page) == [None] * 8
    page.click("#redo")
    expect(page.locator("#lyrics")).to_have_value(WORDS)
    assert roll_words(page)[0] == "Twin-"

    # Delete the first note: the words do not stay on the deleted note's neighbours, they flow onto the notes in order.
    page.click('#melodyroll .note[data-i="0"]')
    page.click("#melodydelete")
    expect(page.locator("#notecount")).to_have_text("7 notes")
    assert roll_words(page) == ["Twin-", "kle", "twin-", "kle", "lit-", "tle", ""]
    expect(page.locator("#lyricsinfo")).to_have_text("6 syllables on the notes; 1 more has no note yet.")
    page.click("#undo")
    expect(page.locator("#notecount")).to_have_text("8 notes")
    assert roll_words(page)[-1] == "star"

    # The words are part of the draft: a reload brings them back on the notes.
    wait_until(page, f"""async () => {{ const db = await new Promise(r => {{ const q = indexedDB.open('tandem'); q.onsuccess = () => r(q.result) }});
        const d = await new Promise(r => {{ const q = db.transaction('kv').objectStore('kv').get('draft'); q.onsuccess = () => r(q.result) }});
        db.close(); return !!(d && d.notes.length === 8 && d.lyrics === {WORDS!r}) }}""", "the draft keeps the words")
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent === '8 notes'")
    expect(page.locator("#lyrics")).to_have_value(WORDS)
    assert roll_words(page) == ["Twin-", "kle", "twin-", "kle", "lit-", "tle", "", "star"]


def test_export_musicxml_writes_the_words_under_the_melody(studio, tmp_path):
    import music21
    page = studio
    page.click("#demo")
    page.click("#genharmony")
    type_words(page, WORDS)
    score = music21.converter.parse(str(download(page, "#exportmusicxml", tmp_path)), format="musicxml").stripTies()
    melody, harmony = score.parts
    read = [(n.lyrics[0].text, n.lyrics[0].syllabic) if n.lyrics and n.lyrics[0].text else None for n in melody.flatten().notes]
    assert read == [("Twin", "begin"), ("kle", "end"), ("twin", "begin"), ("kle", "end"), ("lit", "begin"), ("tle", "end"), None, ("star", "single")]
    assert " ".join(music21.text.assembleLyrics(melody).split()) == "Twinkle twinkle little star"
    assert not any(n.lyrics for n in harmony.flatten().notes)


def test_the_words_box_is_in_the_guided_notes_step(browser, server_url):
    with guided_page(browser, server_url) as page:
        page.click('#steps [data-step="notes"]')
        expect(page.locator("#slot-roll #lyrics")).to_be_visible()
