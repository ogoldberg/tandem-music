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


def sounding(part):
    """(MIDI pitches, onset, length) of every note or chord, ties joined, in quarter notes."""
    out = []
    for n in part.flatten().notes:
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
