"""UI.1: the guided steps (Sing / Notes / Song / Share) and the automatic helpers, on a phone-sized touch screen.

These tests use fresh browser contexts without conftest's ALL_CONTROLS script, so the studio opens as it does for a
new person: in the guided view. Recordings come from Chromium's fake microphone (a beeping tone)."""
import re
from contextlib import contextmanager

import httpx
from playwright.sync_api import expect

from test_capture import PHONE
from test_studio import IDB_DRAFT, count

MAC_APP = ["aibaseurl", "aiforget", "aikey", "aimodel", "aiprovider", "aisave", "bandfollows", "bandmute", "bandstyle",
           "downloadband", "genband", "gentimbre", "openfolder", "playband", "playbandtrack", "playtimbretrack", "playvocal",
           "removeband", "removetimbre", "savefolder", "separate", "timbreinstrument", "timbremute", "usefull"]
MIDI_PORTS = ["midichannel", "midiinput", "midioutput", "midirecord"]
CONTROL = re.compile(r'<(button|input|select|textarea)\b[^>]*\bid="([^"]+)"')


@contextmanager
def guided_page(browser, server_url, **extra):
    options = {**PHONE, "is_mobile": True, "permissions": ["microphone"], "base_url": server_url, **extra}
    context = browser.new_context(**options)
    page = context.new_page()
    problems = []
    page.on("pageerror", lambda exc: problems.append(f"pageerror: {exc}"))
    page.on("console", lambda msg: problems.append(f"console.{msg.type}: {msg.text}") if msg.type == "error" else None)
    page.goto("/")
    page.wait_for_function("document.getElementById('notecount').textContent !== '' && !document.body.inert")
    try:
        yield page
    finally:
        context.close()
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


def use_server_transcriber(page):
    # The server's transcriber is quicker than Basic Pitch in CI; Basic Pitch on the device has its own tests.
    page.click("#gsettings")
    page.select_option("#gtranscriber", "server")
    page.click("#ghelpersback")


def record_take(page, seconds=2.5):
    page.click("#grecord")
    expect(page.locator("#greclabel")).to_have_text("Tap to stop")
    page.wait_for_timeout(int(seconds * 1000))
    page.click("#grecord")
    page.wait_for_function("/^(Done|Not everything)/.test(document.getElementById('gstatus').textContent)", timeout=90_000)


def plan(page):
    return page.eval_on_selector_all("#gplan li", "els => els.map(e => [e.textContent, e.dataset.state || ''])")


def test_a_new_person_walks_the_four_steps_on_a_phone(browser, server_url):
    with guided_page(browser, server_url) as page:
        expect(page.locator("#guide")).to_be_visible()
        expect(page.locator("#allcontrols")).to_be_hidden()
        expect(page.locator('#steps [aria-current="step"]')).to_contain_text("Sing")
        expect(page.locator('[data-mode="melody"]')).to_have_attribute("aria-pressed", "true")
        assert plan(page) == [["Clean up the sound", ""], ["Turn your tune into notes", ""], ["Find the speed", ""]]
        use_server_transcriber(page)

        # Step 1: one take, and the helpers clean it up, turn it into notes and find the speed, each shown as done.
        record_take(page)
        expect(page.locator("#gstatus")).to_have_text("Done. Check your notes next.")
        assert plan(page) == [["Clean up the sound", "done"], ["Turn your tune into notes", "done"], ["Find the speed", "done"]]
        notes = count(page, "notecount")
        assert notes >= 4, "the fake microphone beeps about once a second"
        assert page.evaluate("document.getElementById('polished').disabled") is False

        # Step 2: the real melody roll is in the step, with the speed in plain words.
        page.click("#gnext")
        expect(page.locator('#steps [aria-current="step"]')).to_contain_text("Notes")
        expect(page.locator("#slot-roll #melodyroll .note")).to_have_count(notes)
        bpm = page.evaluate(IDB_DRAFT)["bpm"]
        expect(page.locator("#gspeed")).to_have_text(f"Speed: {bpm} beats a minute")
        page.click("#gkeyspeed")
        page.fill("#gbpm", "90")
        page.locator("#gbpm").press("Tab")
        page.wait_for_function("document.getElementById('bpm').value === '90'")
        expect(page.locator("#gspeed")).to_have_text("Speed: 90 beats a minute")
        # The fake microphone beeps one pitch, so no key can be found from it: choose one.
        expect(page.locator("#gkey")).to_have_text("Key: not found yet")
        page.select_option("#gkeysel", "0:major")
        expect(page.locator("#gkey")).to_have_text("Key: C major")
        page.click('[data-beat="tightly"]')
        expect(page.locator("#gstatus")).to_have_text(re.compile(r"^(Quantize to 1/16 at 90 bpm|Already on the 1/16 grid)$"))
        page.click("#gboth")
        expect(page.locator("#gstatus")).to_have_text("Playing your voice with the notes")
        page.click("#gstopnotes")
        # Fix my singing: the sung notes are found and the take tuned on the device.
        page.eval_on_selector("#gpitch", "el => { el.value = '100'; el.dispatchEvent(new Event('input')) }")
        expect(page.locator("#gpitchvalue")).to_have_text("Perfect")
        page.click("#gfix")
        expect(page.locator("#gfixstate")).to_have_text("Fixed", timeout=90_000)
        assert page.evaluate("document.getElementById('tunestrength').value") == "100"

        # Step 3: chords in the chosen key, as one edit that Undo takes back.
        page.click("#gnext")
        expect(page.locator("#gharmkey")).to_have_text("Follows your tune, in C major")
        page.click("#gchords")
        expect(page.locator("#gharmstate")).to_have_text("Chords added")
        assert count(page, "harmonycount") > 0
        expect(page.locator("#gundo")).to_be_enabled()
        page.click("#gundo")
        expect(page.locator("#gharmstate")).to_have_text("Not added")
        page.click("#gredo")
        expect(page.locator("#gharmstate")).to_have_text("Chords added")
        expect(page.locator("#slot-chat #chatform")).to_be_visible()

        # Step 4: a named version, and the song as a WAV file.
        page.click("#gnext")
        expect(page.locator("#gnext")).to_be_hidden()
        page.fill("#gversionname", "First go")
        page.click("#gsaveversion")
        expect(page.locator("#gversions")).to_have_text("1 version saved on this device.")
        expect(page.locator("#gversionname")).to_have_value("")
        with page.expect_download(timeout=40_000) as info:
            page.click('[data-press="exportwav"]')
        assert info.value.suggested_filename == "tandem-arrangement.wav"

        # The rail (shown at desktop widths) sums up each step.
        sums = page.eval_on_selector_all("#steps .gsum", "els => els.map(e => e.textContent)")
        assert re.fullmatch(r"Recorded 0:0\d, cleaned up", sums[0]), sums
        assert sums[1:] == [f"{notes} notes, pitch fixed", "Chords added", "1 version saved"]


def test_helpers_turned_off_are_not_run_and_the_settings_are_kept(browser, server_url):
    with guided_page(browser, server_url) as page:
        use_server_transcriber(page)
        page.click("#gchange")
        expect(page.locator("#ghelpers")).to_be_visible()
        page.uncheck('[data-helper="notes"]')
        page.select_option("#gcleanup", "studio")
        page.select_option("#gpitchname", "light")
        expect(page.locator("#gpitchdetail")).to_have_text("Correction strength 50%, vibrato kept")
        page.click("#ghelpersback")
        page.click('[data-mode="vocal"]')
        assert plan(page) == [["Clean up the sound", ""], ["Fix the pitch of your singing", ""]]

        # A take with words: cleaned up with the Studio preset and pitch-fixed at 50%, and no notes written.
        record_take(page)
        assert plan(page) == [["Clean up the sound", "done"], ["Fix the pitch of your singing", "done"]]
        assert count(page, "notecount") == 0
        assert page.evaluate("document.getElementById('polishstyle').value") == "studio"
        assert page.evaluate("document.getElementById('tunestrength').value") == "50"
        assert page.evaluate("document.getElementById('playtuned').disabled") is False

        # The view, the step and the helpers are kept on this device.
        page.click('#steps [data-step="song"]')
        page.reload()
        page.wait_for_function("!document.body.inert")
        expect(page.locator('#steps [aria-current="step"]')).to_contain_text("Song")
        page.click("#gsettings")
        expect(page.locator('[data-helper="notes"]')).not_to_be_checked()
        expect(page.locator("#gcleanup")).to_have_value("studio")
        expect(page.locator("#gtranscriber")).to_have_value("server")
        page.click("#greset")
        expect(page.locator('[data-helper="notes"]')).to_be_checked()
        expect(page.locator('[data-helper="lineup"]')).not_to_be_checked()
        expect(page.locator("#gcleanup")).to_have_value("natural")
        expect(page.locator("#gpitchname")).to_have_value("natural")


def test_every_control_of_the_studio_is_in_the_all_controls_view(browser, server_url):
    source = httpx.get(server_url + "/").text
    main = source[source.index('<main id="allcontrols">'):source.index("</main>")]
    ids = [m.group(2) for m in CONTROL.finditer(main)]
    assert len(ids) > 100 and "melodydraw" in ids and "prompt" in ids
    with guided_page(browser, server_url) as page:
        # Visit every step (the roll and the chat move into them), then show every control.
        for step in ["notes", "song", "share", "sing"]:
            page.click(f'#steps [data-step="{step}"]')
        page.click("#gsettings")
        page.click("#gshowall")
        expect(page.locator("#guide")).to_be_hidden()
        report = page.evaluate("""ids => ids.map(id => {
            const el = document.getElementById(id);
            if (!el) return [id, 'missing'];
            if (!el.closest('#allcontrols')) return [id, 'outside'];
            // Controls a feature hides where it is not available (the Mac app's, Web MIDI's) and the file pickers.
            if (el.closest('[hidden]') || el.classList.contains('hide')) return [id, 'feature'];
            const r = el.getBoundingClientRect();
            return [id, r.width > 0 && r.height > 0 ? 'shown' : 'not shown'];
        })""", ids)
        wrong = [r for r in report if r[1] not in ("shown", "feature")]
        assert not wrong, wrong
        # Hidden here only because the feature is not available: the Mac app's controls, the MIDI ports (shown after
        # Connect MIDI) and the file pickers behind their buttons.
        assert sorted(r[0] for r in report if r[1] == "feature") == sorted(MAC_APP + MIDI_PORTS + ["audiofile", "projectfile"])
        # The guided view's own controls are not in the studio's layout, and the roll is back in its place.
        assert page.evaluate("document.getElementById('melodyroll').closest('.track').contains(document.getElementById('addnote'))")
        # And back again, from the studio's header.
        page.click("#showguide")
        expect(page.locator("#guide")).to_be_visible()
        expect(page.locator("#slot-roll #melodyroll")).to_be_attached()
        page.reload()
        page.wait_for_function("!document.body.inert")
        expect(page.locator("#guide")).to_be_visible()
