"""UI.2: the desktop studio. Steps on the left, the parts as track lanes, the chosen part's settings on the right.

The example project is 8 melody notes on the marimba and 16 drum hits at 100 beats a minute, in C major, 8 s long.
"""
from playwright.sync_api import expect

from test_studio import IDB_GET, wait_until

# A control of each part that must be in its side panel, and the panel the step buttons show.
PART_CONTROLS = {
    "voice": ["#mode", "#polish", "#analyze", "#tune", "#detectvocal"],
    "melody": ["#addnote", "#melodydraw", "#instrument", "#bpm", "#quantize", "#phraseup"],
    "harmony": ["#harmonystyle", "#genharmony", "#harmonyinstrument", "#harmonydraw"],
    "voice2": ["#voice2interval", "#voice2dup", "#voice2create", "#singvoice2", "#voice2draw"],
    "drums": ["#drum", "#addhit", "#clearhits"],
    "band": ["#bandnote"],
    "timbre": ["#timbrenote"],
}
STEP_PARTS = {"sing": ("voice", "#record"), "notes": ("melody", "#melodydraw"), "song": ("song", "#prompt"),
              "share": ("share", "#exportwav")}


def shown_panels(page):
    return page.eval_on_selector_all("#partpanel [data-panel-part]", "ps => ps.filter(p => !p.hidden).map(p => p.dataset.panelPart)")


def pick_lane(page, part):
    # A mouse click on the lane's head, so the conftest's picking of parts plays no part in what is tested.
    head = page.locator(f'#lanes .lanehead[data-part="{part}"]')
    head.scroll_into_view_if_needed()
    box = head.bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


def test_each_lane_shows_its_own_controls_in_the_side_panel(studio):
    page = studio
    page.set_viewport_size({"width": 1440, "height": 900})
    for part, controls in PART_CONTROLS.items():
        pick_lane(page, part)
        assert shown_panels(page) == [part]
        expect(page.locator(f'#lanes .lanehead[data-part="{part}"]')).to_have_attribute("aria-pressed", "true")
        assert page.eval_on_selector_all("#lanes .lanehead[aria-pressed=true]", "bs => bs.length") == 1
        for sel in controls:
            expect(page.locator(f'#partpanel [data-panel-part="{part}"] {sel}')).to_be_visible()
        # Every control of the panel is labelled in plain words with the technical name under it.
        for label in page.locator(f'#partpanel [data-panel-part="{part}"] .ctl label').all():
            assert label.locator("span").inner_text().strip() and label.locator("small").inner_text().strip()
    # The Mac app's parts say where they are made on the web.
    pick_lane(page, "band")
    expect(page.locator("#bandnote")).to_contain_text("Mac app")
    expect(page.locator("#bandtrack")).to_be_hidden()


def test_the_steps_pick_their_panel_and_the_parts_mark_their_step(studio):
    page = studio
    page.set_viewport_size({"width": 1440, "height": 900})
    for step, (part, control) in STEP_PARTS.items():
        page.click(f'#rail .railstep[data-rail="{step}"]')
        assert shown_panels(page) == [part]
        expect(page.locator(f'#rail .railstep[data-rail="{step}"]')).to_have_attribute("aria-current", "step")
        expect(page.locator(control)).to_be_visible()
    # A part's lane marks the step it belongs to.
    pick_lane(page, "drums")
    expect(page.locator('#rail .railstep[data-rail="song"]')).to_have_attribute("aria-current", "step")
    expect(page.locator('#rail [aria-current]')).to_have_count(1)


def test_top_bar_lanes_and_steps_show_the_song(studio):
    page = studio
    page.set_viewport_size({"width": 1440, "height": 900})
    expect(page.locator("#lanesub-melody")).to_have_text("No notes yet")
    expect(page.locator('#rail [data-rail="sing"] .rsum')).to_have_text("Nothing recorded yet")
    page.click("#demo")
    expect(page.locator("#keyspeed")).to_have_text("C major · 100 BPM")
    expect(page.locator("#clock")).to_have_text("0:00.0 / 0:08.0")
    expect(page.locator("#lanesub-melody")).to_have_text("8 notes on Marimba")
    expect(page.locator("#lanesub-drums")).to_have_text("16 hits")
    expect(page.locator("#lanesub-harmony")).to_have_text("Not added")
    expect(page.locator("#lanesub-band")).to_have_text("Made in the Mac app")
    expect(page.locator('#rail [data-rail="notes"] .rsum')).to_have_text("8 notes")
    # The speed follows the tempo, and chords show on their lane.
    page.fill("#bpm", "120")
    page.press("#bpm", "Enter")
    expect(page.locator("#keyspeed")).to_have_text("C major · 120 BPM")
    page.click("#genharmony")
    expect(page.locator("#lanesub-harmony")).to_have_text("Chords on Piano")
    # The clock runs while the song plays.
    page.click("#play")
    page.wait_for_function("parseFloat(document.getElementById('clock').textContent.split(':')[1]) > 0.5", timeout=10000)
    page.click("#stop")
    expect(page.locator("#clock")).to_have_text("0:00.0 / 0:08.0")


def test_space_plays_and_stops_and_number_keys_pick_the_steps(studio):
    page = studio
    page.set_viewport_size({"width": 1440, "height": 900})
    page.click("#demo")
    page.locator("#lanes h2").click()  # focus on the page, not on a control
    page.keyboard.press("4")
    assert shown_panels(page) == ["share"]
    page.keyboard.press("2")
    assert shown_panels(page) == ["melody"]
    page.keyboard.press("Space")
    page.wait_for_function("document.getElementById('timeline').dataset.t > ''", timeout=10000)
    page.keyboard.press("Space")
    page.wait_for_function("document.getElementById('timeline').dataset.t === ''", timeout=10000)
    # Typed into a field, the keys are text, not shortcuts.
    page.click("#songname")
    page.keyboard.type("Song 1 ")
    expect(page.locator("#songname")).to_have_value("Song 1 ")
    assert shown_panels(page) == ["melody"]
    expect(page.locator("#timeline")).to_have_attribute("data-t", "")


def test_the_song_name_is_kept_and_names_a_version_saved_without_a_name(studio):
    page = studio
    page.click("#demo")
    page.fill("#songname", "Morning hum")
    page.press("#songname", "Tab")
    # The name is written to IndexedDB after the change event: reload only once it is stored.
    wait_until(page, "async () => (await (" + IDB_GET + ")('song-name')) === 'Morning hum'", "the song name is stored")
    page.reload()
    page.wait_for_function("!document.body.inert")
    expect(page.locator("#songname")).to_have_value("Morning hum")
    page.click("#saveversion")
    expect(page.locator("#status")).to_have_text("Saved version: Morning hum")
    expect(page.locator("#versionlist")).to_contain_text("Morning hum")


def test_tablet_width_puts_the_steps_above_and_the_panel_beside_the_tracks(studio):
    page = studio
    page.set_viewport_size({"width": 1024, "height": 768})
    rail, lanes, panel = (page.locator(s).bounding_box() for s in ("#rail", "#lanes", "#partpanel"))
    assert rail["y"] + rail["height"] <= lanes["y"] + 1
    assert lanes["x"] + lanes["width"] <= panel["x"] + 1 and abs(panel["y"] - lanes["y"]) < 2
    assert page.evaluate("document.documentElement.scrollWidth") <= 1024
    # The four steps sit side by side.
    tops = page.eval_on_selector_all("#rail .railstep", "bs => bs.map(b => Math.round(b.getBoundingClientRect().top))")
    assert len(set(tops)) == 1


def test_the_chat_folds_its_connection_settings_and_says_in_a_sentence_what_is_sent(studio):
    """UX.3: the API server and token are in a closed Connection (advanced) fold; the disclosure is one sentence
    with the rest behind What is sent."""
    page = studio
    show_part = page.locator('#rail .railstep[data-part="song"]')
    show_part.click()
    note = page.locator("#chatnote")
    expect(note).to_be_visible()
    assert len(note.text_content().split()) <= 25
    assert "never your recordings" in note.text_content()
    for fold, inside in (("#connection", "#token"), ("#whatsent", "#whatsent p")):
        assert page.evaluate(f"document.querySelector('{fold}').open") is False
        expect(page.locator(inside)).to_be_hidden()
    expect(page.locator("#connection summary")).to_have_text("Connection (advanced)")
    expect(page.locator("#api")).to_be_hidden()
    page.click("#whatsent summary")
    expect(page.locator("#whatsent p")).to_contain_text("the recent chat")
    page.click("#connection summary")
    expect(page.locator("#api")).to_be_visible()
    expect(page.locator("#connect")).to_be_visible()


def test_at_tablet_width_the_shortcuts_fold_so_the_tracks_show(studio):
    """UX.3: up to 1180 px, where the steps sit above the tracks, the shortcuts are a closed fold."""
    page = studio
    assert page.evaluate("document.getElementById('shortcuts').open") is True
    expect(page.locator("#shortcuts dl")).to_be_visible()
    page.set_viewport_size({"width": 1024, "height": 768})
    page.wait_for_function("!document.getElementById('shortcuts').open")
    expect(page.locator("#shortcuts dl")).to_be_hidden()
    lane = page.locator('#lanes .lanehead[data-part="voice"]').bounding_box()
    assert lane["y"] + lane["height"] <= 768, lane
    # Still there for whoever wants it.
    page.click("#shortcuts summary")
    expect(page.locator("#shortcuts dl")).to_be_visible()
    page.set_viewport_size({"width": 1300, "height": 800})
    page.wait_for_function("document.getElementById('shortcuts').open")


def test_at_phone_width_a_lane_scrolls_to_its_settings_and_back_to_tracks_returns(studio):
    """UX.3: at phone width the panel is under every lane: picking a lane scrolls to it, Back to tracks scrolls back
    to the lane picked."""
    page = studio
    expect(page.locator("#backtotracks")).to_be_hidden()
    page.set_viewport_size({"width": 390, "height": 844})
    pick_lane(page, "voice")
    heading = page.locator("#ph-voice")
    page.wait_for_function("(() => { const r = document.getElementById('ph-voice').getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; })()")
    expect(heading).to_be_in_viewport()
    expect(page.locator("#backtotracks")).to_be_in_viewport()
    page.click("#backtotracks")
    head = page.locator('#lanes .lanehead[data-part="voice"]')
    expect(head).to_be_in_viewport()
    expect(head).to_be_focused()
    expect(heading).not_to_be_in_viewport()


def test_record_becomes_stop_recording_and_the_voice_lane_says_why_it_is_silent(studio):
    """UX.3: while a take records, Record is replaced by Stop recording; the voice lane says it is muted, and why
    it is silent while another part is soloed."""
    page = studio
    page.click("#demo")
    page.uncheck("#countin")
    expect(page.locator("#record")).to_be_visible()
    expect(page.locator("#finish")).to_be_hidden()
    page.click("#record")
    expect(page.locator("#status")).to_have_text("Recording…", timeout=8000)
    expect(page.locator("#finish")).to_be_visible()
    expect(page.locator("#record")).to_be_hidden()
    page.wait_for_timeout(1200)
    page.click("#finish")
    expect(page.locator("#record")).to_be_visible()
    expect(page.locator("#finish")).to_be_hidden()
    sub = page.locator("#lanesub-voice")
    expect(sub).to_contain_text("Muted: the song plays without your voice until you unmute it")
    page.click("#mute-voice")
    expect(sub).not_to_contain_text("Muted")
    expect(sub).not_to_contain_text("Silent")
    page.click("#solo-melody")
    expect(sub).to_contain_text("Silent: another part is soloed")
    page.click("#solo-melody")
    expect(sub).not_to_contain_text("Silent")
