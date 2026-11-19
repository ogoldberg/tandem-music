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


def tones(pitches=(), seconds=3.0, each=0.6, step=1.0, start=0.2, rate=RATE):
    """`seconds` of samples with a sine tone of `each` seconds every `step` seconds from `start`, one per MIDI pitch."""
    x = np.zeros(int(rate * seconds))
    t = np.arange(int(rate * each)) / rate
    env = np.minimum(1, np.minimum(t, each - t) / 0.02)
    for i, m in enumerate(pitches):
        at = int(rate * (start + i * step))
        x[at:at + len(t)] += 0.4 * env * np.sin(2 * np.pi * 440 * 2 ** ((m - 69) / 12) * t)
    return x


def write_wav(path, channels, rate=RATE):
    """A 16-bit WAV with one column of `channels` per channel."""
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels.shape[1])
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((channels * 32767).astype("<i2").tobytes())
    path.write_bytes(out.getvalue())
    return path


def take_wav(path, pitches=(), seconds=3.0, each=0.6, step=1.0, start=0.2):
    """A mono 16-bit WAV of `tones`."""
    return write_wav(path, tones(pitches, seconds, each, step, start)[:, None])


def draft_notes(page):
    draft = page.evaluate(IDB_DRAFT)
    return (json.loads(draft) if isinstance(draft, str) else draft)["notes"]


def record_analyze_uploads(page):
    """Keep each /api/analyze upload's WAV, read in the page: Playwright does not give a FormData body back."""
    page.evaluate("""() => { window.analyzeBytes = []; window.analyzeWavs = []; const send = window.fetch;
      window.fetch = async (url, opts) => {
        if (String(url).includes('/api/analyze') && opts && opts.body) {
          window.analyzeBytes.push((await new Response(opts.body).arrayBuffer()).byteLength);
          window.analyzeWavs.push(opts.body.get('file')); }
        return send(url, opts); }; }""")


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
        before = draft_notes(page)

        import_take(page, take_wav(tmp_path / "silent.wav", seconds=3))
        expect(page.locator("#gstatus")).to_have_text(
            "Nothing was heard in the take, so your notes are as they were. Sing closer to the microphone and record again.")
        assert notes(page) == 6
        # The same notes: pitch, start and length, not only as many.
        assert draft_notes(page) == before
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
        record_analyze_uploads(page)
        import_take(page, take_wav(tmp_path / "long.wav", [60, 64] * 35, seconds=70, each=0.6, step=1.0))
        expect(page.locator("#gstatus")).to_have_text(
            "Done. Check your notes next. The take is 70 seconds long, so the notes are from its first 60 seconds.")
        starts = [n["t"] for n in draft_notes(page)]
        assert len(starts) >= 55, starts
        assert max(starts) < 60 and max(starts) > 58, starts
        # Vercel refuses a request body over 4.5 MB: the minute goes up as mono at 22,050 Hz, about 2.6 MB.
        sizes = page.evaluate("window.analyzeBytes")
        assert len(sizes) == 1 and 2_000_000 < sizes[0] < 4_500_000, sizes


def test_a_long_take_sung_only_after_the_first_minute_says_so(browser, server_url, tmp_path):
    with guided_page(browser, server_url) as page:
        use_server_transcriber(page)
        import_take(page, take_wav(tmp_path / "tune.wav", [60, 62, 64], seconds=3.5))
        before = draft_notes(page)
        assert len(before) == 3
        import_take(page, take_wav(tmp_path / "late.wav", [60, 64, 67], seconds=70, start=64))
        expect(page.locator("#gstatus")).to_have_text(
            "Nothing was heard in the first 60 seconds of the 70-second take, so your notes are as they were. "
            "Start singing sooner, or record a shorter take.")
        assert draft_notes(page) == before
        assert plan(page)[1] == ["Turn your tune into notes", "failed"]


def test_a_multichannel_take_goes_up_as_the_average_of_its_channels(browser, server_url, tmp_path):
    """The melody upload is the plain average of the take's live channels, as before it was resampled: a voice on a
    5.1 file's fourth (LFE) channel is not dropped by Web Audio's speaker mix."""
    with guided_page(browser, server_url) as page:
        use_server_transcriber(page)
        record_analyze_uploads(page)
        rate = 44100
        voice = tones([60, 62, 64, 65], seconds=4.5, rate=rate)
        # The other channels are live (a quiet hum 40 dB down), so REC.1 keeps all six.
        hum = 0.004 * np.sin(2 * np.pi * 50 * np.arange(len(voice)) / rate)
        six = np.stack([hum, hum, hum, voice, hum, hum], axis=1)
        import_take(page, write_wav(tmp_path / "six.wav", six, rate=rate))
        # The channel count and rate are read from the uploaded WAV's own header: decoding resamples to its context.
        level = page.evaluate("""async () => { const bytes = await window.analyzeWavs.at(-1).arrayBuffer(), h = new DataView(bytes);
          const buf = await new OfflineAudioContext(1, 1, 22050).decodeAudioData(bytes.slice(0));
          const x = buf.getChannelData(0); let peak = 0; for (const v of x) peak = Math.max(peak, Math.abs(v));
          return {channels: h.getUint16(22, true), rate: h.getUint32(24, true), peak}; }""")
        # The voice's peak is 0.4, so a sixth of it is about 0.067; the speaker mix drops it and leaves the hum (< 0.01).
        assert level["channels"] == 1 and level["rate"] == 22050, level
        assert 0.05 < level["peak"] < 0.09, level
        assert len(draft_notes(page)) == 4


def test_transcribe_uses_the_listener_chosen_when_it_started(browser, server_url, tmp_path):
    """Changing the transcriber while the take is still being decoded does not move the running job to the server."""
    with guided_page(browser, server_url) as page:
        use_server_transcriber(page)
        import_take(page, take_wav(tmp_path / "tune.wav", [60, 62, 64, 65], seconds=4.5))
        record_analyze_uploads(page)
        page.evaluate("""async () => { const t = document.getElementById('transcriber');
          document.getElementById('mode').value = 'melody'; t.value = 'basic-pitch';
          const run = document.getElementById('analyze').onclick(); t.value = 'heuristic'; await run; }""")
        assert page.evaluate("window.analyzeBytes.length") == 0
        expect(page.locator("#status")).to_have_text("Transcription complete")
        assert len(draft_notes(page)) >= 3


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
