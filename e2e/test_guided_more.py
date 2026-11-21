"""UX.7: every studio control has a place in the guided view, at phone width.

guide.js CONTROL_PLACES names, for every control of index.html, the guided screen or fold that shows it (or the guided control
that drives it); these tests open each place on a 390 px phone and find its controls inside it and visible, make one edit
through each view's More fold, and check every element the guided view moves in is back in its place under Show every control.
"""
import re

from playwright.sync_api import expect

from test_guided import (DRAWN_LINE, LINE_TRIAL, MAC_APP, MIDI_PORTS, PRACTICE_BAR, RANGE_BOX, SECTION_TOOLS, TAKES,
                         VERSION_FULL, guided_page, open_view, record_take, use_server_transcriber)
from test_playhead import drag_loop

TABLE = """async () => { const g = await import('/guide.js');
  return { places: g.PLACES, controls: g.CONTROL_PLACES, moves: g.MOVES, more: g.MORE_VIEWS, views: g.VIEWS.map(v => v.id) }; }"""

# Shown only in a state the example song is not in: the Mac app's controls, the MIDI ports (after Connect MIDI), the harmony
# line trial (after Create harmony), a drawn line's Keep and Cancel, the comp controls (two takes), a chosen section's tools,
# the practice bar and range, the version limit's question, the sung harmony's
# own controls (once it is sung) and the Mac app's folder buttons.
STATE = set(MAC_APP + MIDI_PORTS + LINE_TRIAL + DRAWN_LINE + TAKES + SECTION_TOOLS + PRACTICE_BAR + RANGE_BOX + VERSION_FULL
            + ["gvoice2next", "gvoice2keep", "gvoice2cancel", "gopenfolder", "gsavefolder",
               "playvoice2sung", "voice2sungmute", "removevoice2sung", "gsharevoice"])

CHECK = """([ids, controls, holder]) => ids.map(id => {
  const { via } = controls[id], el = via ? document.querySelector(via) : document.getElementById(id);
  if (!el) return [id, 'missing'];
  if (!el.closest('#guide')) return [id, 'outside the guided view'];
  if (!el.closest(holder)) return [id, 'not in ' + holder];
  if (el.closest('[hidden]')) return [id, 'state'];
  const r = el.getBoundingClientRect();
  return [id, r.width > 0 && r.height > 0 ? 'shown' : 'not shown'];
})"""


def ids_of(table, place):
    return sorted(id for id, c in table["controls"].items() if c["place"] == place)


def check(page, table, place, *, shown=True):
    report = page.evaluate(CHECK, [ids_of(table, place), table["controls"], table["places"][place]])
    wrong = [r for r in report if r[1] not in ("shown", "state")]
    assert not wrong, (place, wrong)
    if shown:
        hidden = sorted(r[0] for r in report if r[1] == "state")
        assert set(hidden) <= STATE, (place, set(hidden) - STATE)
    return report


def open_fold(page, selector):
    page.locator(selector + " > summary").scroll_into_view_if_needed()
    if not page.eval_on_selector(selector, "d => d.open"):
        page.click(selector + " > summary")


def test_every_place_shows_its_controls_inside_the_guided_view_on_a_phone(browser, server_url):
    with guided_page(browser, server_url) as page:
        page.click("#gdemo")
        page.wait_for_function("document.querySelectorAll('#melodyroll .note').length > 0")
        table = page.evaluate(TABLE)
        places = set(table["places"])
        done = set()

        def at(place, **kw):
            check(page, table, place, **kw)
            done.add(place)

        at("top")
        at("song")
        at("nav", shown=False)
        for view in table["views"]:
            open_view(page, view)
            if view == table["views"][0]:
                at("frame")
            at("view:" + view)
            if view in table["more"]:
                fold = table["places"]["view:" + view + ":more"]
                # Closed until it is opened, and its controls are not on screen meanwhile.
                assert page.eval_on_selector(fold, "d => !d.open"), view
                open_fold(page, fold)
                at("view:" + view + ":more")
            assert page.evaluate("document.scrollingElement.scrollWidth") <= 390, view
        page.click("#gviewback")
        page.click('#steps [data-step="sing"]')
        at("sing")
        open_fold(page, "#grecopts")
        at("sing:options")
        # Your take shows after a take; its controls are in it (UX.4's tests play them).
        at("take", shown=False)
        page.click('#steps [data-step="share"]')
        at("share")
        open_fold(page, "#gmoreapps")
        at("share:apps")
        page.click("#gsettings")
        at("settings")
        at("settings:ai")
        assert page.evaluate("document.scrollingElement.scrollWidth") <= 390
        # The fixed buttons, the studio's own header and rail, and the file pickers are the only places not visited.
        assert places - done == {"fixed", "studio", "file"}, places - done


def test_one_edit_through_each_views_more_fold(browser, server_url):
    with guided_page(browser, server_url) as page:
        page.click("#gdemo")
        page.wait_for_function("document.querySelectorAll('#melodyroll .note').length > 0")

        def edit_in(view, fold, act):
            open_view(page, view)
            expect(page.locator("#gputback")).to_be_disabled()
            open_fold(page, fold)
            act()
            # Put it back is enabled once the open view has made an edit (UX.6).
            expect(page.locator("#gputback")).to_be_enabled()
            page.click("#gviewdone")
            expect(page.locator(f"#gtile-{view} .gtused")).to_be_visible()

        notes = page.locator("#melodyroll .note").count()
        edit_in("notes", "#gmoretools", lambda: page.click("#gmoretools #addnote"))
        open_view(page, "notes")
        expect(page.locator("#melodyroll .note")).to_have_count(notes + 1)

        def quantize():
            page.select_option("#gmore-timing #grid", "4")
            page.select_option("#gmore-timing #qstrength", "1")
            page.click("#gmore-timing #quantize")
        edit_in("timing", "#gmore-timing", quantize)

        open_view(page, "chords")
        page.click("#gchords")
        expect(page.locator("#gharmstate")).to_have_text("Chords added")
        # The chord names and Change a chord are in view.
        expect(page.locator('.gview[data-view="chords"] #chordstrip')).to_be_visible()
        expect(page.locator('.gview[data-view="chords"] #chordroot')).to_be_visible()
        page.click("#gviewdone")
        first = page.locator("#harmonyroll .note").first
        pitch = int(first.get_attribute("title").split()[1])

        def octave():
            page.click("#gmore-chords #harmonyall")
            page.click("#gmore-chords #harmonyoctup")
        edit_in("chords", "#gmore-chords", octave)
        expect(first).to_have_attribute("title", re.compile(rf"^MIDI {pitch + 12} "))

        edit_in("voice2", "#gmore-voice2", lambda: page.click("#gmore-voice2 #voice2dup"))
        expect(page.locator("#gvoice2state")).to_have_text(re.compile(r"^\d+ notes$"))
        expect(page.locator("#gmore-voice2 #voice2roll .note").first).to_be_attached()

        hits = int(page.locator("#hitcount").text_content().split()[0])
        edit_in("beat", "#gmore-beat", lambda: page.click("#gmore-beat #addhit"))
        assert int(page.locator("#hitcount").text_content().split()[0]) == hits + 1

        # Sound's More holds MIDI out, which is not an edit; its everyday controls hold the mixer: a mute is one edit.
        open_view(page, "sound")
        # The sung harmony's row shows only once it is sung.
        expect(page.locator("#slot-mix-voice2_sung")).to_be_hidden()
        mute = page.locator('.gview[data-view="sound"] #mute-melody')
        expect(mute).to_have_attribute("aria-pressed", "false")
        mute.click()
        expect(mute).to_have_attribute("aria-pressed", "true")
        expect(page.locator("#gputback")).to_be_enabled()
        open_fold(page, "#gmore-sound")
        assert page.evaluate("!!document.getElementById('midioutput').closest('#gmore-sound')")


def test_an_edit_through_the_voice_views_more_fold(browser, server_url):
    # The pitch line's key and scale need a take.
    with guided_page(browser, server_url) as page:
        use_server_transcriber(page)
        page.click('[data-mode="melody"]')
        record_take(page)
        open_view(page, "voice")
        expect(page.locator("#gputback")).to_be_disabled()
        open_fold(page, "#gmore-voice")
        for el in ("#original", "#tunekey", "#tunescale", "#detectvocal", "#vocalnoteeditor"):
            expect(page.locator("#gmore-voice " + el)).to_be_visible()
        # The key follows the scale: chromatic (the default) has none.
        expect(page.locator("#gmore-voice #tunekey")).to_be_disabled()
        page.select_option("#gmore-voice #tunescale", "major")
        expect(page.locator("#gmore-voice #tunekey")).to_be_enabled()
        expect(page.locator("#gputback")).to_be_enabled()
        page.click("#gviewdone")
        expect(page.locator("#gtile-voice .gtused")).to_be_visible()


def test_sections_takes_and_practise_views(browser, server_url):
    with guided_page(browser, server_url) as page:
        page.click("#gdemo")
        page.wait_for_function("document.querySelectorAll('#melodyroll .note').length > 0")
        expect(page.locator("#gtiles .glabel")).to_have_text(["Fix your tune", "Add to it", "More", "Or ask for it"])
        expect(page.locator("#gtile-sections .gtstate")).to_have_text("No sections yet")
        # Sections: the Timeline is open there, and marking a stretch is one edit.
        open_view(page, "sections")
        assert page.eval_on_selector("#gtimeline", "d => d.open")
        expect(page.locator('.gview[data-view="sections"] #timeline')).to_be_visible()
        drag_loop(page, 1.2, 2.4)
        page.select_option("#sectionname", "Chorus")
        page.click("#marksection")
        expect(page.locator("#sections .secblock")).to_have_count(1)
        page.click("#gviewdone")
        expect(page.locator("#gtile-sections .gtstate")).to_have_text("1 section")
        # The Timeline is folded again in the views that show it closed.
        open_view(page, "notes")
        assert page.eval_on_selector("#gtimeline", "d => !d.open")

        # Takes: no take yet, so nothing to record on top of.
        open_view(page, "takes")
        expect(page.locator("#gtakesline")).to_have_text("Nothing recorded yet")
        expect(page.locator("#grecordlayer")).to_be_disabled()

        # Practise: its own group, with the roll and the Timeline fold.
        open_view(page, "practise")
        for el in ("#practice", "#warmup", "#addwarmup", "#melodyroll", "#gtimeline"):
            expect(page.locator('.gview[data-view="practise"] ' + el)).to_be_visible()
        assert page.evaluate("document.scrollingElement.scrollWidth") <= 390


def test_record_a_part_on_top_from_takes_adds_a_layer_shown_there(browser, server_url):
    with guided_page(browser, server_url) as page:
        use_server_transcriber(page)
        page.click('[data-mode="melody"]')
        record_take(page)
        open_view(page, "takes")
        expect(page.locator("#gtakesline")).to_have_text("1 take")
        expect(page.locator("#glayersline")).to_have_text("No layers yet: Record a part on top makes one")
        page.click("#grecordlayer")
        expect(page.locator('#steps [aria-current="step"]')).to_contain_text("Sing")
        open_fold(page, "#grecopts")
        expect(page.locator("#grecopts #reclayer")).to_be_checked()
        page.click("#grecord")
        expect(page.locator("#greclabel")).to_have_text("Tap to stop")
        page.wait_for_timeout(1500)
        page.click("#grecord")
        page.wait_for_function("document.querySelectorAll('#layerlanes .lane[data-layer]').length === 1", timeout=60_000)
        open_view(page, "takes")
        expect(page.locator('.gview[data-view="takes"] #layerlanes .lane[data-layer]')).to_have_count(1)
        expect(page.locator("#glayersline")).to_have_text("1 layer")
        expect(page.locator("#gtakesline")).to_have_text("1 take")


def test_everything_moved_in_goes_back_to_its_place_under_show_every_control(browser, server_url):
    with guided_page(browser, server_url) as page:
        page.click("#gdemo")
        table = page.evaluate(TABLE)
        page.click("#gsettings")
        page.click("#gshowall")
        expect(page.locator("#guide")).to_be_hidden()
        where = """sels => sels.map(s => { const el = document.querySelector(s); if (!el) return [s, null];
          const p = el.parentElement; return [s, (p.id || p.className) + ':' + [...p.children].indexOf(el)]; })"""
        sels = [m[0] for m in table["moves"]]
        home = page.evaluate(where, sels)
        assert all(h[1] for h in home), [h for h in home if not h[1]]
        assert not page.evaluate("sels => sels.some(s => document.querySelector(s).closest('#guide'))", sels)
        page.click("#showguide")
        for view in table["views"]:
            open_view(page, view)
        assert page.evaluate("sels => sels.filter(s => !document.querySelector(s).closest('#guide'))", sels) == []
        page.click("#gviewback")
        page.click("#gsettings")
        page.click("#gshowall")
        assert page.evaluate(where, sels) == home
