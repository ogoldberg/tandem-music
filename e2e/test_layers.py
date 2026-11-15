"""TRACK.1: several recorded layers, each a track of its own. Chromium's fake microphone (a beeping tone) is the input:
the take is recorded over a starter beat, then a second layer over the song, which is transcribed into the chords part,
muted in its lane, found again after a reload and exported as a stem of its own."""
import io
import json
import wave
import zipfile

import numpy as np
from playwright.sync_api import expect

from test_studio import wait_until

RATE = 44100


def samples(data):
    with wave.open(io.BytesIO(data)) as w:
        assert w.getframerate() == RATE and w.getnchannels() == 1
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32767


def stems(page):
    with page.expect_download(timeout=60_000) as info:
        page.click("#exportstems")
    with open(info.value.path(), "rb") as f:
        z = zipfile.ZipFile(io.BytesIO(f.read()))
    return {name: samples(z.read(name)) for name in z.namelist() if name.endswith(".wav")}


def record(page, seconds):
    page.click("#record")
    expect(page.locator("#status")).to_have_text("Recording…", timeout=10000)
    page.wait_for_timeout(int(seconds * 1000))
    page.click("#finish")


def layers(page):
    return page.evaluate("() => [...document.querySelectorAll('#layerlanes .lane')].map(l => ({id: l.dataset.layer, name: l.querySelector('strong').textContent, sub: l.querySelector('.layerhead small').textContent}))")


def test_two_layers_over_a_groove_each_a_track_transcribed_muted_kept_and_exported(studio):
    page = studio
    page.fill("#bpm", "120")
    page.dispatch_event("#bpm", "change")
    page.select_option("#groove", "straight")
    page.select_option("#groovebars", "4")
    page.click("#addgroove")
    expect(page.locator("#hitcount")).not_to_have_text("0 hits")
    page.uncheck("#countin")
    # Until there is a take, a new layer cannot be asked for: the first recording is the take.
    expect(page.locator("#reclayer")).to_be_disabled()
    record(page, 1.5)
    expect(page.locator("#status")).to_contain_text("Recorded", timeout=10000)
    expect(page.locator("#reclayer")).to_be_enabled()
    take_before = page.locator("#finish").get_attribute("data-take")

    # The second layer, over the song (the groove and the take), keeps the take.
    page.check("#reclayer")
    record(page, 2.0)
    expect(page.locator("#status")).to_contain_text("Recorded Layer 2 as a track of its own", timeout=10000)
    assert page.locator("#finish").get_attribute("data-take") != take_before
    got = layers(page)
    assert [l["name"] for l in got] == ["Layer 2"]
    lid = got[0]["id"]
    assert json.loads(page.locator("#finish").get_attribute("data-take"))["song"] is True
    expect(page.locator("#original")).to_be_enabled()
    expect(page.locator("#undo")).to_have_attribute("title", "Undo: Record a layer")

    # Transcribed into the chords part with the server's listener; the melody is left as it was.
    melody_before = page.locator("#notecount").text_content()
    page.select_option("#transcriber", "heuristic")
    page.select_option(f"#layerinto-{lid}", "harmony")
    page.click(f"#layertranscribe-{lid}")
    expect(page.locator("#status")).to_contain_text("Transcribed Layer 2 into the chords part", timeout=30000)
    expect(page.locator("#harmonycount")).not_to_have_text("0 notes")
    expect(page.locator("#notecount")).to_have_text(melody_before)
    expect(page.locator(f'#layerlanes .lane[data-layer="{lid}"] .layerhead small')).to_contain_text("in the chords part")
    harmony = page.locator("#harmonycount").text_content()

    # Heard while playing on a bus of its own, and muted at once from its lane.
    page.click("#play")
    page.wait_for_function(f"JSON.parse(document.getElementById('timeline').dataset.mix || '{{}}')['layer-{lid}'] === 1")
    page.click(f"#mute-layer-{lid}")
    page.wait_for_function(f"JSON.parse(document.getElementById('timeline').dataset.mix || '{{}}')['layer-{lid}'] === 0")
    page.click("#stop")
    expect(page.locator(f'.mixstrip[data-mix="layer-{lid}"]')).to_have_attribute("data-gain", "0")

    # Both tracks are kept on this device: after a reload the take, the layer, its mute and the chords are back.
    wait_until(page, f"""async () => {{ const db = await new Promise(r => {{ const q = indexedDB.open('tandem'); q.onsuccess = () => r(q.result) }});
        const links = await new Promise(r => {{ const q = db.transaction('kv').objectStore('kv').get('draft-audio'); q.onsuccess = () => r(q.result) }});
        db.close(); return !!(links && links.original && links['layer-{lid}']) }}""", "the draft links the take and the layer")
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    expect(page.locator("#status")).to_contain_text("Restored the draft and its recording", timeout=10000)
    assert [l["id"] for l in layers(page)] == [lid]
    expect(page.locator(f"#layerplay-{lid}")).to_be_enabled()
    expect(page.locator(f"#mute-layer-{lid}")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#harmonycount")).to_have_text(harmony)
    expect(page.locator("#original")).to_be_enabled()

    # In the stems: the take as recorded and the layer as a stem of its own; the muted layer is not in the mix.
    out = stems(page)
    assert {"vocal-original.wav", "layer-2.wav", "harmony.wav", "drums.wav", "mix.wav"} <= set(out)
    layer = out["layer-2.wav"]
    assert np.abs(layer).max() > 0.01
    assert len({len(x) for x in out.values()}) == 1
    parts = sum(out[n] for n in out if n not in ("mix.wav", "layer-2.wav") and not n.startswith("vocal-"))
    # mix.wav is the parts summed, clipped to full scale as every WAV is.
    assert np.abs(out["mix.wav"] - np.clip(parts, -1, 1)).max() < 2e-4

    # Unmuted, the layer joins the mix.
    page.click(f"#mute-layer-{lid}")
    out = stems(page)
    with_layer = sum(out[n] for n in out if n != "mix.wav" and not n.startswith("vocal-"))
    # Chromium's fake microphone beeps at full scale, so the layer's own stem is clipped there: compare where no stem is.
    unclipped = np.all([np.abs(out[n]) < 0.999 for n in out], axis=0)
    assert unclipped.mean() > 0.9
    assert np.abs(out["mix.wav"] - with_layer)[unclipped].max() < 3e-4
    assert np.abs(out["mix.wav"] - np.clip(parts, -1, 1)).max() > 0.01, "the layer is heard in the mix"
    page.locator("#layerlanes").scroll_into_view_if_needed()
    page.screenshot(path=str(__import__("tempfile").gettempdir() + "/studio-layers.png"))

    # Removing the layer is one edit, and Undo brings it back with its recording.
    page.click(f"#layerremove-{lid}")
    assert layers(page) == []
    page.click("#undo")
    assert [l["id"] for l in layers(page)] == [lid]
    expect(page.locator(f"#layerplay-{lid}")).to_be_enabled()
