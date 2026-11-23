"""EXP.2: the MusicXML that notation.js writes is valid MusicXML 4.0 and reads back as the song.

tests/fixtures/notation.musicxml is what musicXml writes for tests/fixtures/notation-project.json
(tests/notation.test.mjs checks that it still does; tests/fixtures/make_notation_fixture.mjs writes
both). Here it is validated against the official MusicXML 4.0 schema (W3C Music Notation Community
Group, tests/fixtures/musicxml-4.0/) and parsed with music21, a MusicXML reader that is not ours.
"""

import json
from fractions import Fraction
from pathlib import Path

import music21
import pytest
from lxml import etree

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCORE = FIXTURES / "notation.musicxml"
# SHEET.1: a short song whose chords have a flat root, sevenths and one struck inside a held melody note.
CHORDS = FIXTURES / "notation-chords.musicxml"
XSD = FIXTURES / "musicxml-4.0"
# What the fixture melody is: [MIDI pitch, onset, length] in beats, as it was meant before it was
# sung a little early, late and short (make_notation_fixture.mjs).
MELODY = [
    (65, 0, 1), (67, 1, 1), (69, 2, 0.5), (70, 2.5, 0.5), (72, 3, 2),
    (70, 5, 0.75), (69, 5.75, 0.25), (67, 6, 1.5),
    (65, 9, 0.5), (64, 9.5, 0.5), (62, 10, 1), (60, 11, 0.5), (61, 11.5, 0.5), (65, 12, 4),
]


def schema():
    # The schema imports xml.xsd and xlink.xsd from musicxml.org; read the local copies instead.
    text = (XSD / "musicxml.xsd").read_text(encoding="utf-8")
    for name in ("xml.xsd", "xlink.xsd"):
        text = text.replace(f"http://www.musicxml.org/xsd/{name}", (XSD / name).as_uri())
    return etree.XMLSchema(etree.fromstring(text.encode("utf-8"), base_url=XSD.as_uri() + "/"))


@pytest.fixture(scope="module")
def score():
    return music21.converter.parse(str(SCORE), format="musicxml").stripTies()


def notes(part):
    """The notes and chords sounding, without the chord symbols (SHEET.1), which music21 reads as chords too."""
    return [n for n in part.flatten().notes if not isinstance(n, music21.harmony.ChordSymbol)]


def sounding(part):
    """(MIDI pitches, onset, length) of every note or chord, ties joined, in quarter notes."""
    out = []
    for n in notes(part):
        pitches = tuple(sorted(p.midi for p in n.pitches))
        out.append((pitches, Fraction(n.offset), Fraction(n.quarterLength)))
    return out


def test_the_score_is_valid_musicxml_4():
    xsd = schema()
    doc = etree.parse(str(SCORE))
    assert xsd.validate(doc), xsd.error_log.filter_from_errors()


def test_the_schema_rejects_a_broken_score():
    # The validator is not a formality: the same score with a note's duration missing is refused.
    xsd = schema()
    broken = SCORE.read_text(encoding="utf-8").replace("<duration>4</duration>", "", 1)
    assert not xsd.validate(etree.fromstring(broken.encode("utf-8")))


def test_the_melody_reads_back_with_its_pitches_and_rhythm(score):
    melody, harmony = score.parts
    assert melody.partName == "Melody"
    assert sounding(melody) == [((m,), Fraction(t), Fraction(d)) for m, t, d in MELODY]


def test_the_harmony_reads_back_as_the_generated_chords(score):
    project = json.loads((FIXTURES / "notation-project.json").read_text())["project"]
    beat = project["bpm"] / 60
    chords = {}
    for n in project["harmony"]:
        start = Fraction(round(n["t"] * beat * 4), 4)
        chords.setdefault(start, set()).add(n["m"])
    harmony = score.parts[1]
    assert harmony.partName == "Harmony"
    read = sounding(harmony)
    assert [(set(p), t) for p, t, _ in read] == [(chords[t], t) for t in sorted(chords)]
    # One chord per 4/4 bar, held for the bar.
    assert all(d == 4 for _, _, d in read)


def test_key_time_and_tempo_read_back(score):
    project = json.loads((FIXTURES / "notation-project.json").read_text())
    key = score.parts[0].flatten().getElementsByClass(music21.key.Key).first()
    assert (key.sharps, key.mode) == (-1, "major")
    assert project["key"] == {"tonic": 5, "mode": "major"}
    ts = score.parts[0].flatten().getElementsByClass(music21.meter.TimeSignature).first()
    assert ts.ratioString == "4/4"
    tempo = score.flatten().getElementsByClass(music21.tempo.MetronomeMark).first()
    assert tempo.number == project["project"]["bpm"]
    # As written (before ties are joined), every measure of every part is full: 4 quarter notes.
    written = music21.converter.parse(str(SCORE), format="musicxml")
    assert len(written.parts[0].getElementsByClass(music21.stream.Measure)) == 4
    for part in written.parts:
        for measure in part.getElementsByClass(music21.stream.Measure):
            assert measure.duration.quarterLength == 4


# LYR.1: the words the fixture's lyrics put on each melody note, as music21 reads them: (syllable,
# syllabic) per note, None for the note "it" is held over.
WORDS = [
    ("Sing", "single"), ("it", "single"), ("slow", "begin"), ("ly,", "end"), ("sing", "single"),
    ("it", "single"), None, ("low,", "single"), ("and", "single"), ("let", "single"), ("the", "single"),
    ("morn", "begin"), ("ing", "end"), ("come", "single"),
]


def test_the_lyrics_read_back_syllable_by_syllable_on_the_melody(score):
    melody, harmony = score.parts
    read = []
    for n in notes(melody):
        lyric = n.lyrics[0] if n.lyrics else None
        read.append((lyric.text, lyric.syllabic) if lyric and lyric.text else None)
    assert read == WORDS
    # music21 joins the syllables into the words as sung (the held note's empty lyric adds a space).
    assert " ".join(music21.text.assembleLyrics(melody).split()) == "Sing it slowly, sing it low, and let the morning come"
    assert not any(n.lyrics for n in notes(harmony))


def symbols(part):
    return [(c.figure, c.chordKind, Fraction(c.offset)) for c in part.flatten().getElementsByClass(music21.harmony.ChordSymbol)]


def test_the_chord_symbols_read_back_over_the_melody(score):
    # SHEET.1: the chords part's chords as chord symbols on the melody, one where each starts.
    melody, harmony = score.parts
    assert symbols(melody) == [("F", "major", 0), ("C", "major", 4), ("B-", "major", 8), ("F", "major", 12)]
    assert not symbols(harmony)


def test_the_chords_fixture_is_valid_and_its_symbols_name_the_chords_under_them():
    # A flat root, the sevenths, and C7 halfway through the held last note, written as an offset into it.
    assert schema().validate(etree.parse(str(CHORDS)))
    melody, harmony = music21.converter.parse(str(CHORDS), format="musicxml").stripTies().parts
    assert symbols(melody) == [("F", "major", 0), ("Gm7", "minor-seventh", 4), ("B-maj7", "major-seventh", 8), ("F", "major", 12),
                               ("C7", "dominant-seventh", 14)]
    for c in melody.flatten().getElementsByClass(music21.harmony.ChordSymbol):
        under = [n for n in notes(harmony) if n.offset == c.offset]
        assert under and {p.pitchClass for p in under[0].pitches} == {p.pitchClass for p in c.pitches}
    # The symbols are not notes: the melody reads back as its six notes.
    assert [(p, t) for p, t, _ in sounding(melody)] == [((65,), 0), ((67,), 2), ((69,), 4), ((70,), 6), ((72,), 8), ((70,), 12)]


def test_the_held_syllable_draws_its_extend_line_to_the_note_it_is_held_over():
    doc = etree.parse(str(SCORE))
    melody = doc.find("part[@id='P1']")
    # As written: the tied second piece of a note carries no lyric, so look at the written lyrics.
    lyrics = [n.find("lyric") for n in melody.iter("note") if n.find("lyric") is not None]
    held_from, held_to = lyrics[5], lyrics[6]
    assert held_from.findtext("text") == "it" and held_from.find("extend").get("type") == "start"
    assert held_to.find("text") is None and held_to.find("extend").get("type") == "stop"
