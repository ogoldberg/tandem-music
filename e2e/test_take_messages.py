"""FIX.5: a take that is silent, short or long is said plainly in the guided Sing step, and the count-in keeps
the record button round with the count in it."""
import io
import json
import wave

import numpy as np
from playwright.sync_api import expect

from test_guided import guided_page, plan, use_server_transcriber
from test_studio import IDB_DRAFT, wait_until

RATE = 22050


def take_wav(path, pitches=(), seconds=3.0, each=0.6, step=1.0):
    """A mono 16-bit WAV `seconds` long with a sine tone of `each` seconds every `step` seconds, one per MIDI pitch."""
    x = np.zeros(int(RATE * seconds))
    t = np.arange(int(RATE * each)) / RATE
    env = np.minimum(1, np.minimum(t, each - t) / 0.02)
    for i, m in enumerate(pitches):
        at = int(RATE * (0.2 + i * step))
        x[at:at + len(t)] += 0.4 * env * np.sin(2 * np.pi * 440 * 2 ** ((m - 69) / 12) * t)
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    path.write_bytes(out.getvalue())
    return path


def import_take(page, path):
    with page.expect_file_chooser() as chooser:
        page.click("#gimport")
    chooser.value.set_files(str(path))
    page.wait_for_function("/^(Done|Not everything|Nothing)/.test(document.getElementById('gstatus').textContent)",
                           timeout=90_000)


def notes(page):
    return page.evaluate("Number(document.getElementById('notecount').textContent.split(' ')[0])")


def test_a_silent_take_keeps_the_melody_and_says_nothing_was_heard(browser, server_url, tmp_path):
    with guided_page(browser, server_url) as page:
        use_server_transcriber(page)
        import_take(page, take_wav(tmp_path / "tune.wav", [60, 62, 64, 65, 67, 65], seconds=6.5))
        expect(page.locator("#gstatus")).to_have_text("Done. Check your notes next.")
        assert notes(page) == 6

        import_take(page, take_wav(tmp_path / "silent.wav", seconds=3))
        expect(page.locator("#gstatus")).to_have_text(
            "Nothing was heard in the take, so your notes are as they were. Sing closer to the microphone and record again.")
        assert notes(page) == 6
        assert plan(page) == [["Clean up the sound", "done"], ["Turn your tune into notes", "failed"],
                              ["Find the speed", ""]]


def test_a_two_note_take_skips_the_speed_and_says_why(browser, server_url, tmp_path):
    with guided_page(browser, server_url) as page:
        use_server_transcriber(page)
        # A beat already in the song does not count towards the take's notes: the speed is still not looked for.
        page.evaluate("() => document.getElementById('addgroove').click()")
        wait_until(page, f"""async () => {{ const d = await ({IDB_DRAFT})(); const p = typeof d === 'string' ? JSON.parse(d) : d;
                               return !!p && p.drums.length >= 16; }}""", "the starter beat in the draft")
        bpm = page.evaluate("Number(document.getElementById('bpm').value)")
        import_take(page, take_wav(tmp_path / "two.wav", [64, 67], seconds=2.5))
        expect(page.locator("#gstatus")).to_have_text(
            "Done. Check your notes next. Too short to find the speed: sing a little longer, or carry on.")
        assert notes(page) == 2
        assert plan(page) == [["Clean up the sound", "done"], ["Turn your tune into notes", "done"],
                              ["Find the speed", "skipped"]]
        assert page.evaluate("Number(document.getElementById('bpm').value)") == bpm


def test_a_take_over_a_minute_is_transcribed_for_its_first_minute(browser, server_url, tmp_path):
    with guided_page(browser, server_url) as page:
        use_server_transcriber(page)
        # The multipart body's size, read in the page: Playwright does not give a FormData body back.
        page.evaluate("""() => { window.analyzeBytes = []; const send = window.fetch;
          window.fetch = async (url, opts) => {
            if (String(url).includes('/api/analyze') && opts && opts.body)
              window.analyzeBytes.push((await new Response(opts.body).arrayBuffer()).byteLength);
            return send(url, opts); }; }""")
        import_take(page, take_wav(tmp_path / "long.wav", [60, 64] * 35, seconds=70, each=0.6, step=1.0))
        expect(page.locator("#gstatus")).to_have_text(
            "Done. Check your notes next. The take is 70 seconds long, so the notes are from its first 60 seconds.")
        draft = page.evaluate(IDB_DRAFT)
        starts = [n["t"] for n in (json.loads(draft) if isinstance(draft, str) else draft)["notes"]]
        assert len(starts) >= 55, starts
        assert max(starts) < 60 and max(starts) > 58, starts
        # Vercel refuses a request body over 4.5 MB: the minute goes up as mono at 22,050 Hz, about 2.6 MB.
        sizes = page.evaluate("window.analyzeBytes")
        assert len(sizes) == 1 and 2_000_000 < sizes[0] < 4_500_000, sizes


def test_the_count_in_keeps_the_record_button_round_and_shows_the_count(browser, server_url):
    with guided_page(browser, server_url) as page:
        use_server_transcriber(page)
        # A slow tempo makes the four-beat count-in last four seconds, long enough to look at.
        page.evaluate("() => { const b = document.getElementById('bpm'); b.value = '60'; b.onchange(); }")
        expect(page.locator("#gspeed")).to_have_text("Speed: 60 beats a minute")
        page.click("#grecord")
        page.wait_for_function("/^[1-4]$/.test(document.getElementById('grecord').textContent)")
        shape = page.evaluate("getComputedStyle(document.getElementById('grecord')).borderRadius")
        assert shape == "50%", shape
        expect(page.locator("#greclabel")).to_have_text("Count-in… tap to cancel")
        expect(page.locator("#greclabel")).to_have_text("Tap to stop", timeout=10_000)
        assert page.evaluate("document.getElementById('grecord').textContent") == ""
        assert page.evaluate("getComputedStyle(document.getElementById('grecord')).borderRadius") == "28px"
        page.click("#grecord")
        page.wait_for_function("/^(Done|Not everything|Nothing)/.test(document.getElementById('gstatus').textContent)",
                               timeout=90_000)
