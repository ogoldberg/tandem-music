"""TAKE.1: every take kept, one picked or sections comped. Chromium's fake microphone (a beeping tone) is the input:
two takes of different lengths are recorded, the first is picked, a section of the second is comped in, Undo and
Redo walk back through them (with the polished vocal made from a take coming back with it), and the takes and the
comp are found again after a reload and in the exported take."""
import io
import json
import tempfile
import wave
import zipfile

import numpy as np
from playwright.sync_api import expect

from test_studio import wait_until

RATE = 44100


def record(page, seconds):
    page.click("#record")
    expect(page.locator("#status")).to_have_text("Recording…", timeout=10000)
    page.wait_for_timeout(int(seconds * 1000))
    page.click("#finish")


def takes(page):
    return page.evaluate("""() => [...document.querySelectorAll('#takelist .takerow')].map(r => ({id: r.dataset.take, used: r.dataset.used === 'true',
        text: r.querySelector('span.grow').textContent}))""")


def shown(page):
    """The comp the loaded take is, and its length in seconds."""
    el = page.locator("#takes")
    return json.loads(el.get_attribute("data-comp") or "null"), float(el.get_attribute("data-seconds") or 0)


def wait_comp(page, comp):
    page.wait_for_function("want => document.getElementById('takes').dataset.comp === want", arg=json.dumps(comp, separators=(",", ":")) if comp else "")


def take_stem(page):
    with page.expect_download(timeout=60_000) as info:
        page.click("#exportstems")
    with open(info.value.path(), "rb") as f:
        z = zipfile.ZipFile(io.BytesIO(f.read()))
    with wave.open(io.BytesIO(z.read("vocal-original.wav"))) as w:
        assert w.getframerate() == RATE
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32767


def test_two_takes_kept_one_picked_a_section_comped_undone_and_kept(studio):
    page = studio
    page.uncheck("#countin")
    page.uncheck("#recsong")
    record(page, 1.5)
    expect(page.locator("#status")).to_contain_text("Recorded", timeout=10000)
    # One take is just the recording, as before: no takes list.
    expect(page.locator("#takes")).to_be_hidden()
    first_seconds = shown(page)[1]
    assert 1.2 < first_seconds < 2.0

    # A second recording keeps the first: Take 1 and Take 2, the new one in use.
    record(page, 3.0)
    expect(page.locator("#status")).to_contain_text("Recorded Take 2. Every take is kept", timeout=10000)
    expect(page.locator("#takes")).to_be_visible()
    got = takes(page)
    assert [t["text"].split(" · ")[0] for t in got] == ["Take 1", "Take 2"]
    one, two = got[0]["id"], got[1]["id"]
    assert [t["used"] for t in got] == [False, True]
    assert "in use" in got[1]["text"]
    comp, seconds = shown(page)
    assert [s["take"] for s in comp] == [two] and 2.7 < seconds < 3.5
    second_seconds = seconds
    expect(page.locator("#undo")).to_have_attribute("title", "Undo: Record Take 2")
    expect(page.locator(f"#removetake-{two}")).to_be_disabled()

    # Use Take 1: the song's take is the first recording again, and Polish works on it.
    page.click(f"#usetake-{one}")
    wait_comp(page, [{"take": one, "from": 0, "to": round(first_seconds, 3)}])
    assert abs(shown(page)[1] - first_seconds) < 0.01
    expect(page.locator("#takesinfo")).to_have_text("The song uses Take 1")
    page.click("#polish")
    expect(page.locator("#polished")).to_be_enabled(timeout=30000)

    # Comp in a section of Take 2: the take in use is Take 1 then Take 2. Without a section marked on the Timeline,
    # Use the Timeline section says how to mark one.
    page.click("#comploop")
    expect(page.locator("#status")).to_have_text("Mark a section on the Timeline first: drag across it.")
    page.fill("#compfrom", "1")
    page.fill("#compto", "9")
    page.select_option("#comptake", two)
    page.click("#compin")
    want = [{"take": one, "from": 0, "to": 1}, {"take": two, "from": 1, "to": round(second_seconds, 3)}]
    wait_comp(page, want)
    assert abs(shown(page)[1] - second_seconds) < 0.01
    expect(page.locator("#takesinfo")).to_contain_text("The song uses a comp: Take 1 0:00.0-0:01.0, Take 2 0:01.0-")
    assert page.locator("#compstrip .compsec").count() == 2
    assert [t["used"] for t in takes(page)] == [True, True]
    # The polished vocal was made from Take 1 alone: the comp has none until it is polished.
    expect(page.locator("#polished")).to_be_disabled()
    assert page.locator("#undo").get_attribute("title").startswith("Undo: Comp in Take 2 from 0:01.0 to 0:0")
    stem = take_stem(page)
    assert abs(len(stem) / RATE - second_seconds) < 0.01
    page.locator("#takes").scroll_into_view_if_needed()
    page.screenshot(path=tempfile.gettempdir() + "/studio-takes.png")

    # Undo: Take 1 again, with the polished vocal made from it; again: Take 2 whole; Redo walks forward.
    page.click("#undo")
    wait_comp(page, [{"take": one, "from": 0, "to": round(first_seconds, 3)}])
    expect(page.locator("#polished")).to_be_enabled()
    page.click("#undo")
    wait_comp(page, [{"take": two, "from": 0, "to": round(second_seconds, 3)}])
    expect(page.locator("#polished")).to_be_disabled()
    page.click("#undo")
    # Before Take 2 was recorded: the one take, no list.
    wait_comp(page, None)
    expect(page.locator("#takes")).to_be_hidden()
    assert abs(shown(page)[1] - first_seconds) < 0.01
    for _ in range(3):
        page.click("#redo")
    wait_comp(page, want)

    # Kept on this device: after a reload both takes, the comp and its recording are back.
    wait_until(page, f"""async () => {{ const db = await new Promise(r => {{ const q = indexedDB.open('tandem'); q.onsuccess = () => r(q.result) }});
        const links = await new Promise(r => {{ const q = db.transaction('kv').objectStore('kv').get('draft-audio'); q.onsuccess = () => r(q.result) }});
        db.close(); return !!(links && links.original && links['take-{one}'] && links['take-{two}']) }}""", "the draft links the comp and both takes")
    page.reload()
    page.wait_for_function("document.getElementById('notecount').textContent !== ''")
    expect(page.locator("#status")).to_contain_text("Restored the draft and its recording", timeout=10000)
    wait_comp(page, want)
    assert [t["id"] for t in takes(page)] == [one, two]
    expect(page.locator(f"#playtake-{one}")).to_be_enabled()
    expect(page.locator(f"#usetake-{two}")).to_be_enabled()
    assert abs(len(take_stem(page)) / RATE - second_seconds) < 0.01

    # A take the comp does not use can be removed, as one edit.
    page.click(f"#usetake-{two}")
    wait_comp(page, [{"take": two, "from": 0, "to": round(second_seconds, 3)}])
    page.click(f"#removetake-{one}")
    assert [t["id"] for t in takes(page)] == [two]
    page.click("#undo")
    assert [t["id"] for t in takes(page)] == [one, two]
