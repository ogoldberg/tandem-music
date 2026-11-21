"""UI.1: the guided steps (UX.5: Sing / Your song / Share, Your song a hub of change views) and the automatic helpers,
on a phone-sized touch screen.

These tests use fresh browser contexts without conftest's ALL_CONTROLS script, so the studio opens as it does for a
new person: in the guided view. Recordings come from Chromium's fake microphone (a beeping tone)."""
import json
import os
import re
import tempfile
import wave
from contextlib import contextmanager
from pathlib import Path

import httpx
from playwright.sync_api import expect

from test_capture import PHONE
from test_midi import MOCK_MIDI, melody
from test_studio import IDB_DRAFT, count, wait_until

SHOTS = Path(os.environ.get("TANDEM_E2E_SHOTS") or tempfile.gettempdir())

MAC_APP = ["aibaseurl", "aiforget", "aikey", "aimodel", "aiprovider", "aisave", "banddrums", "bandfollows", "bandmute", "bandstyle",
           "downloadband", "genband", "gentimbre", "openfolder", "playband", "playbandtrack", "playtimbretrack", "playvocal",
           "removeband", "removetimbre", "savefolder", "separate", "timbreinstrument", "timbremute", "usefull"]
MIDI_PORTS = ["midichannel", "midiinput", "midioutput", "midirecord"]
# HARM.2: shown only while harmony lines are being tried (after Create harmony).
LINE_TRIAL = ["voice2cancel", "voice2keep", "voice2next"]
# SILENT.2: Keep line and Cancel show only while a drawn line is previewed.
DRAWN_LINE = ["linecancel", "linekeep"]
# TAKE.1: the comp controls, shown once there are two takes.
TAKES = ["compfrom", "compin", "comploop", "comptake", "compto"]
# SONG.1: a section's tools are shown once a section is chosen in the Sections band.
SECTION_TOOLS = ["sectionrepeat", "sectionearlier", "sectionlater", "sectiondelete", "sectionunmark"]
# PRACTICE.1: Stop and Keep pass as a take, shown while practising or with a pass's marks on the roll.
PRACTICE_BAR = ["practiceask", "practicekeep", "practicestop"]
# PRACTICE.2: Forget range and progress, shown once a range or a stretch's progress is kept on the device.
RANGE_BOX = ["practiceforget"]
# SONG.2: Remove it and save and Cancel, shown only when a version is saved at the limit.
VERSION_FULL = ["versionkeep", "versionreplace"]
CONTROL = re.compile(r'<(button|input|select|textarea)\b[^>]*\bid="([^"]+)"')


@contextmanager
def guided_page(browser, server_url, *, init=None, expected_errors=(), **extra):
    options = {**PHONE, "is_mobile": True, "permissions": ["microphone"], "base_url": server_url, **extra}
    context = browser.new_context(**options)
    if init:
        context.add_init_script(init)
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
    # expected_errors: console lines a test causes on purpose (Chromium logs a routed error answer).
    problems = [p for p in problems if p not in expected_errors]
    assert not problems, "Browser reported errors:\n" + "\n".join(problems)


def use_server_transcriber(page):
    # The server's transcriber is quicker than Basic Pitch in CI; Basic Pitch on the device has its own tests.
    page.click("#gsettings")
    page.select_option("#gtranscriber", "server")
    page.click("#ghelpersback")


def back_to_record(page):
    # UX.4: after a take the Sing step shows Your take; Sing it again goes back to the record button.
    if page.locator('[data-panel="take"]').is_visible():
        page.click("#gtakeagain")


def record_take(page, seconds=2.5):
    back_to_record(page)
    page.click("#grecord")
    expect(page.locator("#greclabel")).to_have_text("Tap to stop")
    page.wait_for_timeout(int(seconds * 1000))
    page.click("#grecord")
    page.wait_for_function("/^(Done|Not everything)/.test(document.getElementById('gstatus').textContent)", timeout=90_000)


VIEW_IDS = ["voice", "notes", "timing", "words", "chords", "voice2", "beat", "sound", "ask"]
VIEW_NAMES = ["Voice", "Notes", "Timing", "Words", "Chords", "Second voice", "Beat", "Sound", "Ask Tandem"]


def open_view(page, view):
    # UX.5: Your song's tile opens its change view.
    page.click('#steps [data-step="song"]')
    page.click(f"#gtile-{view}")
    expect(page.locator('[data-panel="view"]')).to_be_visible()
    expect(page.locator(f'.gview[data-view="{view}"]')).to_be_visible()


def plan(page):
    return page.eval_on_selector_all("#gplan li", "els => els.map(e => [e.textContent, e.dataset.state || ''])")


def test_a_new_person_walks_the_three_steps_on_a_phone(browser, server_url):
    with guided_page(browser, server_url) as page:
        expect(page.locator("#guide")).to_be_visible()
        expect(page.locator("#allcontrols")).to_be_hidden()
        expect(page.locator('#steps [aria-current="step"]')).to_contain_text("Sing")
        expect(page.locator('[data-mode="melody"]')).to_have_attribute("aria-pressed", "true")
        assert plan(page) == [["Clean up the sound", ""], ["Turn your tune into notes", ""], ["Find the speed", ""]]
        use_server_transcriber(page)

        # Step 1: one take, and the helpers clean it up, turn it into notes and find the speed, each shown as done.
        record_take(page)
        expect(page.locator("#gstatus")).to_have_text("Done. Have a listen.")
        assert plan(page) == [["Clean up the sound", "done"], ["Turn your tune into notes", "done"], ["Find the speed", "done"]]
        notes = count(page, "notecount")
        assert notes >= 4, "the fake microphone beeps about once a second"
        assert page.evaluate("document.getElementById('polished').disabled") is False

        # Step 2: Keep this take on Your take opens Your song: its tiles say what each kind holds; Notes has the real melody
        # roll; the speed chip says the speed in plain words and opens Timing.
        expect(page.locator("#gnext")).to_be_hidden()
        page.click("#gtakekeep")
        expect(page.locator('#steps [aria-current="step"]')).to_contain_text("Your song")
        expect(page.locator("#gtile-notes .gtstate")).to_have_text(f"{notes} notes")
        expect(page.locator("#gtile-voice .gtstate")).to_have_text("Cleaned up, pitch as sung")
        open_view(page, "notes")
        expect(page.locator("#slot-roll #melodyroll .note")).to_have_count(notes)
        page.click("#gviewdone")
        bpm = page.evaluate(IDB_DRAFT)["bpm"]
        expect(page.locator("#gspeed")).to_have_text(f"Speed: {bpm} beats a minute")
        page.click("#gspeed")
        expect(page.locator("#gh-view")).to_have_text("Timing")
        page.fill("#gbpm", "90")
        page.locator("#gbpm").press("Tab")
        page.wait_for_function("document.getElementById('bpm').value === '90'")
        expect(page.locator("#gspeed")).to_have_text("Speed: 90 beats a minute")
        # The fake microphone's beeps may or may not give a key (the server transcriber sometimes finds a second pitch):
        # either way, choose one.
        expect(page.locator("#gkey")).to_have_text(re.compile(r"^Key: (not found yet|[A-G][♯♭]? (major|minor))$"))
        page.click('[data-beat="tightly"]')
        expect(page.locator("#gstatus")).to_have_text(re.compile(r"^(Quantize to 1/16 at 90 bpm|Already on the 1/16 grid)$"))
        # Timing's Play plays the voice with the notes.
        expect(page.locator("#gviewplays")).to_have_text("Plays your voice with the notes")
        page.click("#gviewplay")
        expect(page.locator("#gstatus")).to_have_text("Playing your voice with the notes")
        page.click("#gviewstop")
        page.click("#gviewdone")
        expect(page.locator("#gtile-timing .gtstate")).to_have_text("90 beats a minute")
        expect(page.locator("#gtile-timing .gtused")).to_be_visible()
        # The key chip opens Chords, where the key is chosen.
        page.click("#gkey")
        expect(page.locator("#gh-view")).to_have_text("Chords")
        page.select_option("#gkeysel", "0:major")
        expect(page.locator("#gkey")).to_have_text("Key: C major")
        # Fix my singing, in Voice: the sung notes are found and the take tuned on the device.
        page.select_option("#gviewjump", "voice")
        expect(page.locator("#gh-view")).to_have_text("Voice")
        page.eval_on_selector("#gpitch", "el => { el.value = '100'; el.dispatchEvent(new Event('input')) }")
        expect(page.locator("#gpitchvalue")).to_have_text("Perfect")
        page.click("#gfix")
        expect(page.locator("#gfixstate")).to_have_text("Fixed", timeout=90_000)
        assert page.evaluate("document.getElementById('tunestrength').value") == "100"
        page.click("#gviewdone")
        expect(page.locator("#gtile-voice .gtstate")).to_have_text("Cleaned up, pitch fixed")
        expect(page.locator("#gtile-chords")).to_have_attribute("data-suggested", "true")

        # Chords in the chosen key, as one edit that Undo takes back.
        page.click("#gtile-chords")
        expect(page.locator("#gharmkey")).to_have_text("Follows your tune, in C major")
        page.click("#gchords")
        expect(page.locator("#gharmstate")).to_have_text("Chords added")
        assert count(page, "harmonycount") > 0
        expect(page.locator("#gundo")).to_be_enabled()
        page.click("#gundo")
        expect(page.locator("#gharmstate")).to_have_text("Not added")
        page.click("#gredo")
        expect(page.locator("#gharmstate")).to_have_text("Chords added")
        # HARM.2: a harmony line, played at once, tried, and kept beside the chords as one edit.
        expect(page.locator("#gvoice2state")).to_have_text("Not added")
        expect(page.locator("#gvoice2try")).to_be_hidden()
        page.click("#gviewnext")
        expect(page.locator("#gh-view")).to_have_text("Second voice")
        page.click("#gvoice2create")
        expect(page.locator("#gvoice2trial")).to_contain_text("Line 1 of ")
        expect(page.locator("#gvoice2trial")).to_contain_text("Thirds above in ")
        page.click("#gvoice2next")
        expect(page.locator("#gvoice2trial")).to_contain_text("Line 2 of ")
        page.click("#gvoice2next")
        page.click("#gvoice2keep")
        expect(page.locator("#gvoice2try")).to_be_hidden()
        notes = count(page, "notecount")
        voice = count(page, "voice2count")
        assert voice > 0 and count(page, "harmonycount") > 0
        expect(page.locator("#gvoice2state")).to_have_text(f"{voice} notes")
        page.click("#gundo")
        expect(page.locator("#gvoice2state")).to_have_text("Not added")
        expect(page.locator("#gharmstate")).to_have_text("Chords added")
        page.click("#gredo")
        expect(page.locator("#gvoice2state")).to_have_text(f"{voice} notes")
        # HARM.3: the kept line sung in the person's own voice, from the take.
        expect(page.locator("#gvoice2sung")).to_have_text("")
        page.click("#gsingvoice2")
        expect(page.locator("#gvoice2sung")).to_have_text("Sung in your voice", timeout=120_000)
        expect(page.locator("#gsingvoice2")).to_have_text("Sing it again in my voice")
        page.select_option("#gviewjump", "ask")
        expect(page.locator("#slot-chat #chatform")).to_be_visible()
        page.click("#gviewdone")
        expect(page.locator("#gtile-voice2 .gtstate")).to_have_text(f"{voice} notes, sung in your voice")
        expect(page.locator("#gtile-beat")).to_have_attribute("data-suggested", "true")

        # Step 3: a named version, and the song as a WAV file.
        page.click("#gnext")
        expect(page.locator("#gnext")).to_be_hidden()
        page.fill("#gversionname", "First go")
        page.click("#gsaveversion")
        expect(page.locator("#gversions")).to_have_text("1 version saved on this device.")
        expect(page.locator("#gversionname")).to_have_value("")
        # SHARE.1: the other formats are folded under "Open in other music apps"; every file is named after the song.
        expect(page.locator('[data-press="exportwav"]')).to_be_hidden()
        page.click("#gmoreapps summary")
        with page.expect_download(timeout=40_000) as info:
            page.click('[data-press="exportwav"]')
        assert info.value.suggested_filename == "Tandem song.wav"

        # The rail (shown at desktop widths) sums up each step.
        sums = page.eval_on_selector_all("#steps .gsum", "els => els.map(e => e.textContent)")
        assert re.fullmatch(r"Recorded 0:0\d, cleaned up", sums[0]), sums
        assert sums[1:] == [f"{notes} notes, chords and a second voice", "1 version saved"]


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
        expect(page.locator('#steps [aria-current="step"]')).to_contain_text("Your song")
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
        # Visit every step and change view (the roll and the chat move into them), then show every control.
        for view in VIEW_IDS:
            open_view(page, view)
        for step in ["share", "sing"]:
            page.click(f'#steps [data-step="{step}"]')
        page.click("#gsettings")
        page.click("#gshowall")
        expect(page.locator("#guide")).to_be_hidden()
        # UI.2: the side panel shows one part's settings at a time, so each control is checked with its part picked.
        report = page.evaluate("""ids => ids.map(id => {
            const el = document.getElementById(id);
            if (!el) return [id, 'missing'];
            if (!el.closest('#allcontrols')) return [id, 'outside'];
            const panel = el.closest('#partpanel [data-panel-part]');
            if (panel) document.querySelector('#allcontrols [data-part="' + panel.dataset.panelPart + '"]').click();
            // Controls a feature hides where it is not available (the Mac app's, Web MIDI's) and the file pickers.
            if (el.closest('[hidden]') || el.classList.contains('hide')) return [id, 'feature'];
            // UX.3: Stop recording takes Record's place only while a take records.
            if (id === 'finish' && el.disabled) return [id, 'feature'];
            const r = el.getBoundingClientRect();
            return [id, r.width > 0 && r.height > 0 ? 'shown' : 'not shown'];
        })""", ids)
        wrong = [r for r in report if r[1] not in ("shown", "feature")]
        assert not wrong, wrong
        # Hidden here only because the feature is not available or not in use: the Mac app's controls, the MIDI ports
        # (shown after Connect MIDI), the harmony line trial (shown after Create harmony), Keep line and Cancel (shown with a drawn line), the comp controls (shown with two takes), the section tools (shown with a section chosen), the practice bar (shown while practising), the version limit's question (shown at the limit), Stop recording (shown while a take records) and the file pickers behind their buttons.
        assert sorted(r[0] for r in report if r[1] == "feature") == sorted(MAC_APP + MIDI_PORTS + LINE_TRIAL + DRAWN_LINE + TAKES + SECTION_TOOLS + PRACTICE_BAR + RANGE_BOX + VERSION_FULL + ["audiofile", "projectfile", "finish"])
        # The guided view's own controls are not in the studio's layout, and the roll is back in its place.
        assert page.evaluate("document.getElementById('melodyroll').closest('.lane').dataset.lane === 'melody'")
        assert page.evaluate("document.getElementById('melodytools').closest('[data-panel-part]').dataset.panelPart === 'melody'")
        # And back again, from the studio's header.
        page.click("#showguide")
        expect(page.locator("#guide")).to_be_visible()
        expect(page.locator("#slot-roll #melodyroll")).to_be_attached()
        page.reload()
        page.wait_for_function("!document.body.inert")
        expect(page.locator("#guide")).to_be_visible()


def test_recording_a_beat_after_singing_keeps_the_sung_song_as_a_version_first(browser, server_url):
    with guided_page(browser, server_url) as page:
        use_server_transcriber(page)
        page.click('[data-mode="vocal"]')
        record_take(page)
        assert page.evaluate("document.getElementById('playtuned').disabled") is False

        # A beat take becomes the recording the song uses, so Record a beat asks first, and Cancel leaves everything as it was.
        open_view(page, "beat")
        page.click("#gbeat")
        expect(page.locator("#gbeatwarn")).to_be_visible()
        expect(page.locator('#steps [aria-current="step"]')).to_contain_text("Your song")
        page.click("#gbeatno")
        expect(page.locator("#gbeatwarn")).to_be_hidden()

        page.click("#gbeat")
        expect(page.locator("#gbeatyes")).to_have_text("Keep a version and record a beat")
        page.dblclick("#gbeatyes")  # a double tap keeps one version
        expect(page.locator('#steps [aria-current="step"]')).to_contain_text("Sing")
        expect(page.locator('[data-mode="rhythm"]')).to_have_attribute("aria-pressed", "true")
        expect(page.locator("#gversions")).to_have_text("1 version saved on this device.")
        expect(page.locator("#gstatus")).to_have_text('Your song is kept as the version "Before the beat". Record your beat.')
        record_take(page)
        assert page.evaluate("document.getElementById('playtuned').disabled") is True
        # TAKE.1: the singing is kept as Take 1 beside the beat take.
        assert page.evaluate("[...document.querySelectorAll('#takelist .takerow')].map(r => r.dataset.used)") == ["false", "true"]

        # The sung take, cleaned up and pitch-fixed, comes back with the version.
        page.click("#gsettings")
        page.click("#gshowall")
        page.click("#versionlist .version:has-text('Before the beat') >> text=Restore")
        page.wait_for_function("!document.getElementById('playtuned').disabled")
        assert page.evaluate("document.getElementById('polished').disabled") is False


def test_without_recording_storage_record_a_beat_says_the_take_is_lost_and_saves_no_version(browser, server_url):
    # No Origin Private File System: versions cannot keep recordings, so no version can keep the voice.
    # FIX.1 (review of #82): the warning's Download your voice is a button beside it, and the page reports no errors.
    with guided_page(browser, server_url, init="delete StorageManager.prototype.getDirectory;") as page:
        use_server_transcriber(page)
        page.click('[data-mode="vocal"]')
        record_take(page)
        open_view(page, "beat")
        page.click("#gbeat")
        expect(page.locator("#gbeatmsg")).to_have_text(
            "A beat take becomes the recording the song uses; your singing stays as Take 1 only until this page is closed, "
            "as this browser cannot keep recordings. Download your voice first if you want to keep it.")
        expect(page.locator("#gbeatdownload")).to_be_visible()
        with page.expect_download() as info:
            page.click("#gbeatdownload")
        assert info.value.suggested_filename == "Tandem song - my voice.wav"
        with wave.open(str(info.value.path())) as w:
            assert w.getnframes() / w.getframerate() > 2
        expect(page.locator("#gstatus")).to_have_text("Downloaded your voice.")
        expect(page.locator("#gbeatyes")).to_have_text("Record a beat anyway")
        page.click("#gbeatyes")
        expect(page.locator('#steps [aria-current="step"]')).to_contain_text("Sing")
        expect(page.locator('[data-mode="rhythm"]')).to_have_attribute("aria-pressed", "true")
        assert page.evaluate("document.getElementById('versionlist').textContent") == "No saved versions yet."

def test_try_an_example_opens_your_song_with_play_in_view(browser, server_url):
    # UX.5 (open question 7): the example has no take, so it opens Your song, whose Play is on the first screen.
    with guided_page(browser, server_url) as page:
        page.click("#gdemo")
        expect(page.locator('#steps [aria-current="step"]')).to_contain_text("Your song")
        expect(page.locator("#gstatus")).to_have_text("Example loaded: tap Play the song to hear it.")
        box = page.locator("#gplay").bounding_box()
        assert box["y"] >= 0 and box["y"] + box["height"] < 844 - 70, "Play is on the first screen, above the bottom bar"
        expect(page.locator("#gtile-notes .gtstate")).to_have_text("8 notes")
        page.click("#gplay")
        expect(page.locator("#gstatus")).not_to_have_text("Example loaded: tap Play the song to hear it.")
        page.wait_for_function("Number(document.getElementById('timeline').dataset.t || 0) > 0.2", timeout=20_000)
        page.click("#gstop")
        page.click('#steps [data-step="sing"]')
        page.click("#gdemo")
        expect(page.locator("#gstatus")).to_have_text("Example loaded: tap Play the song to hear it.")
        page.click("#gtile-notes")
        expect(page.locator("#slot-roll #melodyroll .note")).to_have_count(8)
        expect(page.locator("#gstatus")).to_have_text("")
        # The studio's own Example button, in the all-controls view, keeps its message: that view has Play.
        page.click("#gsettings")
        page.click("#gshowall")
        page.click("#demo")
        expect(page.locator("#status")).to_have_text("Example loaded — press Play")


def test_your_song_sends_you_back_to_sing_when_there_is_nothing_yet(browser, server_url):
    with guided_page(browser, server_url) as page:
        page.click('#steps [data-step="song"]')
        empty = page.locator('[data-panel="song"] .gempty')
        expect(empty).to_be_visible()
        expect(empty).to_contain_text("Nothing to work on yet: sing your idea first")
        # Chords: nothing to make chords or a bass line from, so those buttons are off, and no talk of "these notes".
        open_view(page, "chords")
        expect(page.locator("#gchords")).to_be_disabled()
        expect(page.locator("#gbass")).to_be_disabled()
        expect(page.locator("#gharmkey")).not_to_contain_text("these notes")
        open_view(page, "voice2")
        expect(page.locator("#gvoice2create")).to_be_disabled()
        open_view(page, "timing")
        for beat in ["gently", "tightly", "swung"]:
            expect(page.locator(f'[data-beat="{beat}"]')).to_be_disabled()
        # Its button goes back to Sing.
        page.click('#steps [data-step="song"]')
        empty.locator("button").click()
        expect(page.locator('#steps [aria-current="step"]')).to_contain_text("Sing")
        # With a tune there is something to work on.
        page.click("#gdemo")
        expect(empty).to_be_hidden()
        open_view(page, "timing")
        expect(page.locator('[data-beat="tightly"]')).to_be_enabled()
        open_view(page, "chords")
        expect(page.locator("#gchords")).to_be_enabled()
        expect(page.locator("#gbass")).to_be_enabled()
        expect(page.locator("#gharmkey")).to_have_text(re.compile(r"^Follows your tune, in "))


def voice_muted(page):
    return page.evaluate("document.getElementById('mute-voice').getAttribute('aria-pressed') === 'true'")


def test_singing_with_words_puts_your_voice_in_the_song(browser, server_url):
    # MIX.1 mutes the voice by default and the guided view has no mixer: a take with words unmutes it in the take's own
    # edit, and the Song step's switch is the voice's mute.
    with guided_page(browser, server_url) as page:
        use_server_transcriber(page)
        page.click("#gchange")
        for helper in ["cleanup", "notes", "fixpitch"]:
            page.uncheck(f'[data-helper="{helper}"]')
        page.click("#ghelpersback")
        page.click('#steps [data-step="song"]')
        expect(page.locator("#gvoicein")).to_be_disabled()
        expect(page.locator("#gvoicein")).not_to_be_checked()
        page.click('#steps [data-step="sing"]')
        page.click('[data-mode="vocal"]')
        page.click("#grecord")
        expect(page.locator("#greclabel")).to_have_text("Tap to stop")
        page.wait_for_timeout(2500)
        page.click("#grecord")
        page.wait_for_function("document.getElementById('mute-voice').getAttribute('aria-pressed') === 'false'", timeout=60_000)
        page.click('#steps [data-step="song"]')
        expect(page.locator("#gvoicein")).to_be_enabled()
        expect(page.locator("#gvoicein")).to_be_checked()
        # The switch mutes and unmutes the voice, each one edit.
        page.uncheck("#gvoicein")
        assert voice_muted(page)
        page.click("#gundo")
        expect(page.locator("#gvoicein")).to_be_checked()
        page.uncheck("#gvoicein")
        assert voice_muted(page)
        # A second take with words unmutes it again, in the same edit as the take: one Undo takes both back.
        page.click('#steps [data-step="sing"]')
        page.click("#grecord")
        expect(page.locator("#greclabel")).to_have_text("Tap to stop")
        page.wait_for_timeout(1500)
        page.click("#grecord")
        page.wait_for_function("document.getElementById('mute-voice').getAttribute('aria-pressed') === 'false'", timeout=60_000)
        wait_until(page, "async () => ((await (" + IDB_DRAFT + ")())?.takes?.list?.length ?? 0) === 2", "the draft keeps two takes")
        page.click("#gundo")
        page.wait_for_function("document.getElementById('mute-voice').getAttribute('aria-pressed') === 'true'")
        page.click('#steps [data-step="song"]')
        expect(page.locator("#gvoicein")).not_to_be_checked()


def test_a_tune_take_leaves_the_voice_out_of_the_song(browser, server_url):
    with guided_page(browser, server_url) as page:
        use_server_transcriber(page)
        record_take(page)
        page.click('#steps [data-step="song"]')
        expect(page.locator("#gvoicein")).to_be_enabled()
        expect(page.locator("#gvoicein")).not_to_be_checked()
        assert voice_muted(page)


def test_the_notes_view_listens_first_and_folds_the_expert_tools_on_a_phone(browser, server_url):
    # UX.2, UX.5: on a 390 px phone the Notes view's Play comes before the roll, the expert melody tools and the Timeline
    # are folded (closed), the tools have plain labels, the gear says Settings, and the Share step ends with Show every control.
    with guided_page(browser, server_url) as page:
        page.click("#gdemo")
        open_view(page, "notes")
        page.evaluate("window.scrollTo(0, 0)")
        tops = page.evaluate("""ids => ids.map(id => document.getElementById(id).getBoundingClientRect().top + scrollY)""",
                             ["gh-view", "gviewplay", "melodyroll", "melodydraw", "gmoretools", "gtimeline"])
        assert tops == sorted(tops), tops
        # Play is on the first screen.
        assert page.locator("#gviewplay").bounding_box()["y"] + 44 < 844
        expect(page.locator("#gviewplays")).to_have_text("Plays the song")
        for fold in ("#gmoretools", "#gtimeline"):
            assert page.eval_on_selector(fold, "d => d.open") is False
        for hidden in ("#melodyoctdown", "#melodyoctup", "#melodykeydown", "#melodykeyup", "#melodyfit", "#practice",
                       "#warmup", "#addwarmup", "#timeline", "#marksection"):
            expect(page.locator(hidden)).to_be_hidden()
        for shown in ("#melodydraw", "#melodyline", "#melodyall", "#melodydelete", "#melodysemidown", "#melodysemiup"):
            expect(page.locator(shown)).to_be_visible()
        expect(page.locator("#melodysemidown")).to_have_text("Down a semitone")
        expect(page.locator("#melodysemiup")).to_have_text("Up a semitone")
        assert page.evaluate("document.scrollingElement.scrollWidth") <= 390

        page.click("#gmoretools summary")
        expect(page.locator("#gmoretools #melodykeydown")).to_have_text("Down a note in the key")
        expect(page.locator("#gmoretools #melodykeyup")).to_have_text("Up a note in the key")
        expect(page.locator("#gmoretools #melodyoctdown")).to_have_text("Down an octave")
        expect(page.locator("#gmoretools #melodyfit")).to_have_text("Show which notes fit the chords")
        for shown in ("#melodyoctdown", "#melodykeydown", "#melodyfit", "#practice", "#warmup", "#addwarmup"):
            expect(page.locator(shown)).to_be_visible()
        assert page.evaluate("document.scrollingElement.scrollWidth") <= 390
        # The folded tools drive the same handlers: Up an octave moves the selected notes up 12.
        first = page.locator("#melodyroll .note").first
        before = int(first.get_attribute("title").split()[1])
        page.click("#melodyall")
        page.click("#melodyoctup")
        expect(first).to_have_attribute("title", re.compile(rf"^MIDI {before + 12} "))

        page.click("#gtimeline summary")
        expect(page.locator("#gtimeline #timeline")).to_be_visible()
        expect(page.locator("#gtimeline #marksection")).to_be_visible()

        # The gear is labelled Settings and fits the top bar.
        settings = page.locator("#gsettings")
        expect(settings).to_have_accessible_name("Settings")
        box = settings.bounding_box()
        assert box["x"] + box["width"] <= 390

        # Show every control ends the Share step, and leads to the studio with every tool back in its place.
        page.click('#steps [data-step="share"]')
        last = page.evaluate("""() => { const c = [...document.querySelectorAll('[data-panel="share"] button, [data-panel="share"] input, [data-panel="share"] select')];
            return c[c.length - 1].id }""")
        assert last == "gshareall"
        page.click("#gshareall")
        expect(page.locator("#guide")).to_be_hidden()
        assert page.evaluate("""() => document.getElementById('melodymore').parentElement.id === 'melodytools'
            && !!document.getElementById('transport').closest('#lanes')""")
        expect(page.locator("#melodyfit")).to_be_attached()


HOLD_ANALYZE = """() => { const send = window.fetch; window.analyzeHeld = 0;
  let open; window.analyzeGate = new Promise(r => { open = r; }); window.releaseAnalyze = () => open();
  window.fetch = async (url, opts) => {
    if (String(url).includes('/api/analyze')) { window.analyzeHeld++; await window.analyzeGate; }
    return send(url, opts); }; }"""


def take_t(page):
    return page.eval_on_selector("#gtakewave", "w => Number(w.dataset.t || 0)")


def draft(page):
    d = page.evaluate(IDB_DRAFT)
    return json.loads(d) if isinstance(d, str) else d


def test_a_take_opens_on_your_take_and_plays_while_tandem_works_on_it(browser, server_url):
    # UX.4: after Stop the Sing step's second face, Your take, shows at once; its Play plays the take as sung while a
    # helper is still running; then What Tandem did, the listen row, and one choice: keep, sing again, share.
    with guided_page(browser, server_url) as page:
        use_server_transcriber(page)
        expect(page.locator("#gplanline")).to_have_text(
            "When you stop, Tandem will clean up the sound, turn your tune into notes and find the speed, then let you hear it.")
        expect(page.locator('[data-panel="take"]')).to_be_hidden()
        page.evaluate(HOLD_ANALYZE)
        page.click("#grecord")
        expect(page.locator("#greclabel")).to_have_text("Tap to stop")
        page.wait_for_timeout(3000)
        page.click("#grecord")

        take = page.locator('[data-panel="take"]')
        expect(take).to_be_visible(timeout=20_000)
        expect(page.locator('[data-panel="sing"]')).to_be_hidden()
        expect(page.locator('#steps [aria-current="step"]')).to_contain_text("Sing")
        page.wait_for_function("window.analyzeHeld > 0", timeout=30_000)
        # The notes are still being found: the helpers' list shows it, the choices wait, the waveform is here.
        assert ["Turn your tune into notes", "running"] in plan(page)
        expect(page.locator("#gtakework")).to_be_visible()
        expect(page.locator("#gtakewave #wave")).to_be_visible()
        expect(page.locator("#glistenrow")).to_be_hidden()
        for choice in ("#gtakekeep", "#gtakeagain", "#gtakeshare"):
            expect(page.locator(choice)).to_be_disabled()
        expect(page.locator("#gtakeplay")).to_have_text("Play my take")
        page.click("#gtakeplay")
        expect(page.locator("#gstatus")).to_have_text("Playing your take as you sang it")
        expect(page.locator("#gtakeplay")).to_have_text("Stop")
        page.wait_for_function("Number(document.getElementById('gtakewave').dataset.t || 0) > 0.3")
        assert ["Turn your tune into notes", "running"] in plan(page), "played while a helper was still running"
        page.click("#gtakeplay")
        expect(page.locator("#gtakeplay")).to_have_text("Play my take")
        assert take_t(page) == 0
        assert page.evaluate("document.scrollingElement.scrollWidth") <= 390

        page.evaluate("window.releaseAnalyze()")
        page.wait_for_function("/^(Done|Not everything)/.test(document.getElementById('gstatus').textContent)", timeout=90_000)
        expect(page.locator("#gstatus")).to_have_text(re.compile(r"^Done\. Have a listen\."))
        expect(page.locator("#gtakework")).to_be_hidden()
        report = page.eval_on_selector_all("#gtakereport li", "els => els.map(e => [e.textContent, e.dataset.state])")
        assert [r[1] for r in report] == ["done", "done", "done"], report
        assert report[0][0] == "Cleaned up the sound" and report[1][0].startswith("Turned your tune into notes"), report
        assert report[2][0].startswith("Found the speed"), report
        # The listen row has moved here: The notes plays the melody (the Timeline's playhead moves).
        expect(page.locator("#slot-takelisten #glistenrow")).to_be_visible()
        page.click("#gnotes")
        page.wait_for_function("Number(document.getElementById('timeline').dataset.t || 0) > 0.2", timeout=20_000)
        page.click("#gstopnotes")
        # Play now plays the best take, cleaned up.
        expect(page.locator("#gtakeplay")).to_have_text("Play")
        page.click("#gtakeplay")
        expect(page.locator("#gstatus")).to_have_text("Playing your take")
        page.wait_for_function("Number(document.getElementById('gtakewave').dataset.t || 0) > 0.2")
        assert page.evaluate("document.scrollingElement.scrollWidth") <= 390

        # Keep this take: on to Your song, the playback stopped.
        page.click("#gtakekeep")
        expect(page.locator('#steps [aria-current="step"]')).to_contain_text("Your song")
        expect(take).to_be_hidden()
        assert take_t(page) == 0


def test_sing_it_again_keeps_both_takes_and_share_it_as_it_is_goes_to_share(browser, server_url):
    with guided_page(browser, server_url) as page:
        use_server_transcriber(page)
        record_take(page)
        expect(page.locator('[data-panel="take"]')).to_be_visible()
        page.click("#gtakeagain")
        expect(page.locator('[data-panel="sing"]')).to_be_visible()
        expect(page.locator('[data-panel="take"]')).to_be_hidden()
        record_take(page)
        expect(page.locator('[data-panel="take"]')).to_be_visible()
        # Played to its end, the take says so no longer: the status goes back to Ready.
        page.click("#gtakeplay")
        expect(page.locator("#gstatus")).to_have_text("Playing your take")
        expect(page.locator("#gtakeplay")).to_have_text("Play", timeout=15_000)
        expect(page.locator("#gstatus")).to_have_text("Ready")
        wait_until(page, f"""async () => {{ const d = await ({IDB_DRAFT})(); const p = typeof d === 'string' ? JSON.parse(d) : d;
                               return !!p?.takes && p.takes.list.length === 2; }}""", "two takes in the draft")
        page.click("#gtakeshare")
        expect(page.locator('#steps [aria-current="step"]')).to_contain_text("Share")
        # The rail's Sing goes back to the record button, not Your take.
        page.click('#steps [data-step="sing"]')
        expect(page.locator('[data-panel="sing"]')).to_be_visible()


def test_an_imported_take_opens_your_take_and_a_failed_helper_is_named_there(browser, server_url, tmp_path):
    busy = "console.error: Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
    with guided_page(browser, server_url, expected_errors=(busy,)) as page:
        use_server_transcriber(page)
        page.route("**/api/analyze?*", lambda route: route.fulfill(status=503, content_type="application/json",
                                                                 body='{"detail": "The server is busy."}'))
        path = tmp_path / "take.wav"
        rate, seconds = 22050, 2.0
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            import math
            w.writeframes(b"".join(int(8000 * math.sin(2 * math.pi * 440 * i / rate)).to_bytes(2, "little", signed=True)
                                   for i in range(int(rate * seconds))))
        with page.expect_file_chooser() as chooser:
            page.click("#gimport")
        chooser.value.set_files(str(path))
        page.wait_for_function("/^(Done|Not everything)/.test(document.getElementById('gstatus').textContent)", timeout=90_000)
        expect(page.locator('[data-panel="take"]')).to_be_visible()
        report = page.eval_on_selector_all("#gtakereport li", "els => els.map(e => [e.textContent, e.dataset.state])")
        assert report[0] == ["Cleaned up the sound", "done"], report
        assert report[1][1] == "failed" and report[1][0].startswith("Could not turn your tune into notes: "), report
        assert report[2] == ["Not done: find the speed", "notrun"], report
        expect(page.locator("#gtakekeep")).to_be_enabled()


def tile_state(page, view):
    return page.locator(f"#gtile-{view} .gtstate").text_content()


def done_shows(page, view, line):
    # Done goes back to Your song, focused on the tile it came from, with the tile's state line and its Changed mark.
    page.click("#gviewdone")
    expect(page.locator('[data-panel="song"]')).to_be_visible()
    expect(page.locator(f"#gtile-{view}")).to_be_focused()
    expect(page.locator(f"#gtile-{view} .gtstate")).to_have_text(line)
    expect(page.locator(f"#gtile-{view} .gtused")).to_be_visible()


def test_every_change_view_makes_its_edit_and_done_shows_it_on_your_song(browser, server_url):
    # UX.5: on a 390 px phone each view's own controls are in it and work: one edit from each, then Done back to the hub.
    # Voice is in the walk above (Fix my singing needs a take). The example: 8 notes at 100 bpm, no chords, beat or words.
    import tandem_backend as server
    with guided_page(browser, server_url) as page:
        page.click("#gdemo")
        assert page.eval_on_selector_all("#gtiles .gtile", "els => els.map(e => e.dataset.view)") == VIEW_IDS
        assert page.eval_on_selector_all("#gtiles .glabel", "els => els.map(e => e.textContent)") == ["Fix your tune", "Add to it", "Or ask for it"]
        expect(page.locator("#gtiles .gtused:visible")).to_have_count(0)
        expect(page.locator("#gtile-chords")).to_have_attribute("data-suggested", "true")
        expect(page.locator("#gtile-chords .gtsuggest")).to_be_visible()
        expect(page.locator("#gtiles .gtsuggest:visible")).to_have_count(1)
        assert page.evaluate("document.scrollingElement.scrollWidth") <= 390

        def check_view(view):
            open_view(page, view)
            expect(page.locator("#gh-view")).to_have_text(VIEW_NAMES[VIEW_IDS.index(view)])
            assert page.evaluate("document.scrollingElement.scrollWidth") <= 390, view

        check_view("notes")
        page.locator("#melodyroll .note").first.click()
        page.click("#melodydelete")
        done_shows(page, "notes", "7 notes")

        check_view("timing")
        page.fill("#gbpm", "120")
        page.locator("#gbpm").press("Tab")
        done_shows(page, "timing", "120 beats a minute")
        expect(page.locator("#gspeed")).to_have_text("Speed: 120 beats a minute")

        check_view("words")
        expect(page.locator(".gview[data-view=words] #lyrics")).to_be_visible()
        page.fill("#lyrics", "Twin-kle twin-kle lit-tle star")
        page.locator("#lyrics").press("Tab")
        expect(page.locator("#melodyroll .note .lyric").first).to_have_text("Twin-")
        done_shows(page, "words", "4 words")

        check_view("chords")
        page.click("#gchords")
        expect(page.locator("#gharmstate")).to_have_text("Chords added")
        done_shows(page, "chords", "Chords added")
        # The example already has a beat: with chords in, the suggestion is Share, on the bottom bar.
        expect(page.locator("#gtiles .gtsuggest:visible")).to_have_count(0)
        expect(page.locator("#gnext")).to_have_attribute("data-suggested", "true")

        check_view("voice2")
        page.click("#gvoice2create")
        page.click("#gvoice2keep")
        voice = count(page, "voice2count")
        assert voice > 0
        done_shows(page, "voice2", f"{voice} notes")

        check_view("beat")
        page.click("#ggrooveadd")
        expect(page.locator("#gdrumstate")).to_have_text(re.compile(r"^\d+ hits$"))
        hits = count(page, "hitcount")
        done_shows(page, "beat", f"{hits} hits")

        check_view("sound")
        for menu in ("#ggenre", "#ginstrument", "#gharminst", "#gvoice2inst"):
            expect(page.locator(menu)).to_be_visible()
        page.select_option("#ggenre", "jazz")
        expect(page.locator("#genre")).to_have_value("jazz")
        melody = page.eval_on_selector("#instrument", "s => s.selectedOptions[0].text")
        done_shows(page, "sound", f"Jazz, melody on {melody}")

        # Ask Tandem: the chat makes its edit from the view (the model's text canned; the server validates it).
        check_view("ask")
        expect(page.locator(".gview[data-view=ask] #chatform")).to_be_visible()

        def answer(route):
            req = server.ChatRequest.model_validate(json.loads(route.request.post_data))
            route.fulfill(status=200, json=server.chat_plan(json.dumps({"reply": "Slower.", "actions": [{"type": "set_tempo", "bpm": 90}]}), req))
        page.route("**/api/chat", answer)
        page.fill("#prompt", "slower please")
        page.click("#chatform button[type=submit]")
        page.wait_for_function("document.getElementById('bpm').value === '90'")
        done_shows(page, "ask", "Your melody is protected")
        expect(page.locator("#gtile-timing .gtstate")).to_have_text("90 beats a minute")
        # Every view was used, Voice aside.
        assert page.eval_on_selector_all("#gtiles .gtile", "els => els.filter(e => e.dataset.used === 'true').map(e => e.dataset.view)") == VIEW_IDS[1:]
        page.screenshot(path=str(SHOTS / "ux5-hub.png"), full_page=True)


def test_a_chat_reply_that_lands_in_another_view_marks_the_view_it_was_asked_from(browser, server_url):
    # UX.5 review: an action that finishes later marks the view it was started in, not the one open when it lands.
    import tandem_backend as server
    with guided_page(browser, server_url) as page:
        page.click("#gdemo")
        open_view(page, "ask")
        held = []
        page.route("**/api/chat", lambda route: held.append(route))
        page.fill("#prompt", "slower please")
        page.click("#chatform button[type=submit]")
        for _ in range(100):
            if held:
                break
            page.wait_for_timeout(50)
        assert held, "the chat request was not sent"
        page.select_option("#gviewjump", "beat")
        expect(page.locator('.gview[data-view="beat"]')).to_be_visible()
        req = server.ChatRequest.model_validate(json.loads(held[0].request.post_data))
        held[0].fulfill(status=200, json=server.chat_plan(json.dumps({"reply": "Slower.", "actions": [{"type": "set_tempo", "bpm": 90}]}), req))
        page.wait_for_function("document.getElementById('bpm').value === '90'")
        page.click("#gviewdone")
        expect(page.locator('[data-panel="song"]')).to_be_visible()
        expect(page.locator("#gtile-ask .gtused")).to_be_visible()
        expect(page.locator("#gtile-beat .gtused")).to_be_hidden()


def test_prev_next_and_the_jump_menu_walk_the_views_and_the_roll_is_in_one_view_at_a_time(browser, server_url):
    with guided_page(browser, server_url) as page:
        page.click("#gdemo")
        open_view(page, "voice")
        expect(page.locator("#gviewprev")).to_be_disabled()
        expect(page.locator("#gback")).to_be_hidden()
        expect(page.locator("#gnext")).to_be_hidden()
        assert page.eval_on_selector_all("#gviewjump option", "els => els.map(e => e.textContent)") == VIEW_NAMES
        seen = [page.locator("#gh-view").text_content()]
        while page.locator("#gviewnext").is_enabled():
            label = page.locator("#gviewnext").text_content()
            page.click("#gviewnext")
            seen.append(page.locator("#gh-view").text_content())
            assert label == seen[-1] + " ›", label
            expect(page.locator("#gviewprev")).to_have_text("‹ " + seen[-2])
            expect(page.locator("#gviewjump")).to_have_value(VIEW_IDS[len(seen) - 1])
            # The roll and the Timeline fold are in the open view when it shows them, and nowhere on screen otherwise.
            view = VIEW_IDS[len(seen) - 1]
            if view in ("notes", "timing", "words"):
                assert page.evaluate("document.getElementById('melodyroll').closest('.gview').dataset.view") == view
                assert page.evaluate("document.getElementById('gtimeline').closest('.gview').dataset.view") == view
                expect(page.locator("#melodyroll")).to_be_visible()
                expect(page.locator("#gtimeline")).to_be_visible()
            else:
                expect(page.locator("#melodyroll")).to_be_hidden()
                expect(page.locator("#gtimeline")).to_be_hidden()
            assert page.evaluate("document.querySelectorAll('#melodyroll').length") == 1
            assert page.evaluate("document.scrollingElement.scrollWidth") <= 390, view
        assert seen == VIEW_NAMES
        while page.locator("#gviewprev").is_enabled():
            page.click("#gviewprev")
        expect(page.locator("#gh-view")).to_have_text("Voice")
        # The jump menu goes straight to any view.
        page.select_option("#gviewjump", "words")
        expect(page.locator("#gh-view")).to_have_text("Words")
        assert page.evaluate("document.getElementById('melodyroll').closest('.gview').dataset.view") == "words"
        # The back link and the rail's Your song return to the hub.
        page.click("#gviewback")
        expect(page.locator('[data-panel="song"]')).to_be_visible()
        expect(page.locator("#gtile-words")).to_be_focused()
        expect(page.locator("#gnext")).to_be_visible()
        open_view(page, "timing")
        page.click('#steps [data-step="song"]')
        expect(page.locator('[data-panel="song"]')).to_be_visible()
        # Show every control puts the roll and the Timeline back in their lanes; the guided view takes them again.
        open_view(page, "timing")
        page.click("#gsettings")
        page.click("#gshowall")
        assert page.evaluate("document.getElementById('melodyroll').closest('.lane').dataset.lane") == "melody"
        assert page.evaluate("!!document.getElementById('transport').closest('#lanes')")
        page.click("#showguide")
        assert page.evaluate("document.getElementById('melodyroll').closest('.gview').dataset.view") == "timing"
        expect(page.locator("#melodyroll")).to_be_visible()


def test_a_step_kept_from_before_opens_your_song(browser, server_url):
    # UX.5: the Notes and Song steps are now Your song; a person who left the guided view on either comes back to it.
    init = "localStorage.setItem('tandem-guide', JSON.stringify({view: 'guided', step: 'notes'}))"
    with guided_page(browser, server_url, init=init) as page:
        expect(page.locator('#steps [aria-current="step"]')).to_contain_text("Your song")
        expect(page.locator('[data-panel="song"]')).to_be_visible()
        assert page.eval_on_selector_all("#steps [data-step]", "els => els.map(e => e.dataset.step)") == ["sing", "song", "share"]


def use_midi_output(page):
    # The playback tests read what Play schedules from a mocked MIDI output; its controls are in the all-controls view.
    page.evaluate("document.getElementById('midiconnect').click()")
    page.wait_for_function("document.getElementById('midiinfo').textContent === '1 input, 1 output'")
    page.evaluate("(() => { const s = document.getElementById('midioutput'); s.value = 'out-1'; s.dispatchEvent(new Event('change')); })()")


def played_onsets(page, n):
    # The first n melody note-ons Play sent, in seconds from the first (drums are on channel 10).
    page.evaluate("window.__midiSent.length = 0")
    page.click("#gviewplay")
    page.wait_for_function(f"window.__midiSent.filter(e => (e.data[0] & 0xf0) === 0x90 && e.data[2] > 0 && (e.data[0] & 15) !== 9).length >= {n}", timeout=10_000)
    page.click("#gviewstop")
    due = [e["due"] for e in page.evaluate("window.__midiSent") if (e["data"][0] & 0xF0) == 0x90 and e["data"][2] > 0 and (e["data"][0] & 15) != 9][:n]
    return [round((d - due[0]) / 1000, 2) for d in due]


RAW_DRAFT = f"async () => {{ const d = await ({IDB_DRAFT})(); return typeof d === 'string' ? d : JSON.stringify(d); }}"


def from_first(notes):
    return [round(t - notes[0][1], 2) for _, t in notes]


def close(a, b, within=0.02):
    return len(a) == len(b) and all(abs(x - y) <= within for x, y in zip(a, b))


def test_before_and_after_in_timing_play_the_song_as_it_was_and_put_it_back_undoes_the_view(browser, server_url):
    # UX.6: Before is the project as it was when the view opened, played through the same scheduling as Play; After is
    # the song now. Put it back takes this view's Undo steps, so the project is byte for byte as it was and Redo returns.
    with guided_page(browser, server_url, init=MOCK_MIDI) as page:
        page.click("#gdemo")
        use_midi_output(page)
        open_view(page, "timing")
        expect(page.locator("#gbefore")).to_be_disabled()
        expect(page.locator("#gputback")).to_be_disabled()
        expect(page.locator("#gviewplays")).to_have_text("Plays the song")
        wait_until(page, f"async () => (await ({RAW_DRAFT})()).includes('\"m\":')", "the example in the draft")
        start, notes_then = page.evaluate(RAW_DRAFT), melody(page)
        # Lined up on 120's beat the example's notes (on 100's sixteenths) move.
        page.fill("#gbpm", "120")
        page.locator("#gbpm").press("Tab")
        page.click('[data-beat="tightly"]')
        notes_now = melody(page)
        assert not close(from_first(notes_now), from_first(notes_then)), (notes_then, notes_now)
        expect(page.locator("#gbefore")).to_be_enabled()
        expect(page.locator("#gputback")).to_be_enabled()
        expect(page.locator("#gputback")).to_have_attribute("title", "Undo the 2 changes made here")

        page.click("#gbefore")
        expect(page.locator("#gbefore")).to_have_attribute("aria-pressed", "true")
        expect(page.locator("#gviewplays")).to_have_text("Before: the song as it was when you opened Timing. Choose After to change it.")
        expect(page.locator('.gview[data-view="timing"]')).to_have_class(re.compile(r"\bdimmed\b"))
        assert page.eval_on_selector('.gview[data-view="timing"]', "e => e.inert")
        page.screenshot(path=str(SHOTS / "ux6-timing-before.png"))
        heard = played_onsets(page, len(notes_then))
        assert close(heard, from_first(notes_then)), (heard, notes_then)
        # Comparing changed nothing.
        assert melody(page) == notes_now

        page.click("#gafter")
        expect(page.locator("#gafter")).to_have_attribute("aria-pressed", "true")
        assert not page.eval_on_selector('.gview[data-view="timing"]', "e => e.inert")
        heard = played_onsets(page, len(notes_now))
        assert close(heard, from_first(notes_now)), (heard, notes_now)

        page.click("#gputback")
        expect(page.locator("#status")).to_have_text("Put back the 2 changes made in Timing. Redo brings them back.")
        assert melody(page) == notes_then
        page.wait_for_function("document.getElementById('bpm').value === '100'")
        wait_until(page, f"async () => (await ({RAW_DRAFT})()) === {json.dumps(start)}", "the draft as it was")
        expect(page.locator("#gbefore")).to_be_disabled()
        expect(page.locator("#gputback")).to_be_disabled()
        page.click("#gredo")
        page.click("#gredo")
        assert melody(page) == notes_now
        expect(page.locator("#gputback")).to_be_enabled()


def test_switching_while_it_plays_keeps_the_place_and_leaving_the_view_forgets_before(browser, server_url):
    with guided_page(browser, server_url, init=MOCK_MIDI) as page:
        page.click("#gdemo")
        use_midi_output(page)
        open_view(page, "timing")
        page.fill("#gbpm", "120")
        page.locator("#gbpm").press("Tab")
        page.click("#gbefore")
        page.click("#gviewplay")
        page.wait_for_function("Number(document.getElementById('timeline').dataset.t) > 1")
        page.click("#gafter")
        expect(page.locator("#status")).to_contain_text("Playing to Test Synth from ")
        at = float(re.search(r"from ([\d.]+) s", page.locator("#status").text_content()).group(1))
        assert at >= 1, at
        page.click("#gviewstop")
        # A view opened again starts from the song as it is then: nothing of its own to compare yet.
        page.click("#gviewdone")
        open_view(page, "timing")
        expect(page.locator("#gbefore")).to_be_disabled()
        expect(page.locator("#gputback")).to_be_disabled()


def test_in_voice_before_plays_the_take_as_sung(browser, server_url):
    with guided_page(browser, server_url) as page:
        use_server_transcriber(page)
        record_take(page)
        open_view(page, "voice")
        # The automatic clean-up made the best take; Before is the take as recorded.
        expect(page.locator("#gbefore")).to_be_enabled()
        expect(page.locator("#gputback")).to_be_disabled()
        page.click("#gbefore")
        expect(page.locator("#gviewplays")).to_have_text("Before: your take as you sang it. Choose After to hear it as it is now.")
        page.click("#gviewplay")
        expect(page.locator("#gviewplays")).to_have_attribute("data-take", "original")
        expect(page.locator("#status")).to_have_text("Playing your take as you sang it")
        page.wait_for_timeout(800)
        page.click("#gafter")
        expect(page.locator("#gviewplays")).to_have_attribute("data-take", "best")
        expect(page.locator("#status")).to_have_text("Playing your voice")
        assert float(page.get_attribute("#gviewplays", "data-from")) >= 0.5
        page.click("#gviewstop")
