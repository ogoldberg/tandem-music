"""EXP.3: the project.xml and metadata.xml that dawproject.js writes are valid DAWproject 1.0.

tests/fixtures/dawproject-project.xml and dawproject-metadata.xml are what projectXml and metadataXml
write for the notation fixture's song with drums, two vocal takes, the separated music and a muted
band (tests/fixtures/make_dawproject_fixture.mjs writes them; tests/dawproject.test.mjs checks that
it still does). Here they are validated against the official DAWproject schemas (Bitwig,
tests/fixtures/dawproject-1.0/) and read back with lxml, not with the module's own reader.
"""

import json
from pathlib import Path

import pytest
from lxml import etree

FIXTURES = Path(__file__).resolve().parent / "fixtures"
XSD = FIXTURES / "dawproject-1.0"
PROJECT = FIXTURES / "dawproject-project.xml"
METADATA = FIXTURES / "dawproject-metadata.xml"
SONG = json.loads((FIXTURES / "notation-project.json").read_text(encoding="utf-8"))


def schema(name):
    return etree.XMLSchema(etree.parse(str(XSD / name)))


def assert_valid(xsd, doc):
    assert xsd.validate(doc), xsd.error_log.filter_from_errors()


@pytest.fixture(scope="module")
def project():
    return etree.parse(str(PROJECT))


def tracks(doc):
    """{track name: (Track element, its arrangement Lanes element)}."""
    lanes = {l.get("track"): l for l in doc.iter("Lanes") if l.get("track")}
    return {t.get("name"): (t, lanes[t.get("id")]) for t in doc.find("Structure").iter("Track")}


def test_the_project_is_valid_dawproject(project):
    assert_valid(schema("Project.xsd"), project)


def test_the_metadata_is_valid_dawproject():
    doc = etree.parse(str(METADATA))
    assert_valid(schema("MetaData.xsd"), doc)
    assert doc.findtext("Title") == "Notation fixture"
    assert doc.findtext("Comment") == "Key: F major"


def test_the_schema_rejects_a_broken_project():
    # The validator is not a formality: a note without its key is refused.
    broken = PROJECT.read_text(encoding="utf-8").replace(' key="65"', "", 1)
    assert broken != PROJECT.read_text(encoding="utf-8")
    assert not schema("Project.xsd").validate(etree.fromstring(broken.encode("utf-8")))


def test_the_transport_is_the_project_tempo_in_4_4(project):
    tempo = project.find("Transport/Tempo")
    assert (tempo.get("unit"), float(tempo.get("value"))) == ("bpm", SONG["project"]["bpm"])
    sig = project.find("Transport/TimeSignature")
    assert (sig.get("numerator"), sig.get("denominator")) == ("4", "4")
    assert project.find("Arrangement/Lanes").get("timeUnit") == "beats"


def test_the_melody_and_harmony_are_the_song_in_beats(project):
    bpm = SONG["project"]["bpm"]
    found = tracks(project)
    for name, key, channel in (("Melody", "notes", "0"), ("Harmony", "harmony", "1")):
        track, lane = found[name]
        assert track.get("contentType") == "notes"
        notes = [(int(n.get("key")), float(n.get("time")), float(n.get("duration")), n.get("channel")) for n in lane.iter("Note")]
        want = [(n["m"], n["t"] * bpm / 60, n["d"] * bpm / 60, channel) for n in SONG["project"][key]]
        assert len(notes) == len(want)
        for got, exp in zip(notes, want):
            assert got[0] == exp[0] and got[3] == exp[3]
            assert got[1] == pytest.approx(exp[1], abs=1e-6) and got[2] == pytest.approx(exp[2], abs=1e-6)


def test_the_drums_are_general_midi_keys_on_channel_10(project):
    _, lane = tracks(project)["Drums"]
    # The fixture's hits are on the beat and the offbeat, in seconds rounded to the millisecond.
    assert [(n.get("key"), float(n.get("time")), n.get("channel")) for n in lane.iter("Note")] == [
        ("36", 0.0, "9"), ("42", pytest.approx(0.5, abs=0.002), "9"), ("38", pytest.approx(1.0, abs=0.002), "9"), ("42", pytest.approx(1.5, abs=0.002), "9")]


def test_the_recordings_are_audio_tracks_from_zero(project):
    bpm = SONG["project"]["bpm"]
    found = tracks(project)
    expected = {"Band": (12, True, 0.8, "audio/band.wav"), "Vocal (tuned)": (10.5, False, 1, "audio/vocal-tuned.wav"),
                "Vocal (original)": (10.5, True, 1, "audio/vocal-original.wav"), "Music (separated)": (10.5, False, 1, "audio/accompaniment.wav")}
    assert [n for n, (t, _) in found.items() if t.get("contentType") == "audio"] == list(expected)
    master = found["Master"][0].find("Channel")
    assert master.get("role") == "master"
    for name, (seconds, muted, gain, path) in expected.items():
        track, lane = found[name]
        channel = track.find("Channel")
        assert channel.get("destination") == master.get("id")
        assert channel.find("Mute").get("value") == str(muted).lower()
        assert float(channel.find("Volume").get("value")) == gain
        clip = lane.find("Clips/Clip")
        assert float(clip.get("time")) == 0 and float(clip.get("duration")) == pytest.approx(seconds * bpm / 60)
        audio = clip.find("Warps/Audio")
        assert (audio.find("File").get("path"), float(audio.get("duration")), audio.get("sampleRate"), audio.get("channels")) == (path, seconds, "44100", "1")
        warps = [(float(w.get("time")), float(w.get("contentTime"))) for w in clip.find("Warps").iter("Warp")]
        assert warps == [(0, 0), (pytest.approx(seconds * bpm / 60), seconds)]
