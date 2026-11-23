"""GROW.4: Song shape on a 390 px phone with the fake microphone. A hummed take with chords and a beat is one block, the
idea, shown but not written; Play it again twice makes three blocks, the melody, chords, drums and voice each three times
(the voice read from the buffer Play schedules), with the bar grid pinned by the first one. Undo takes one repeat off,
Before plays the one block and After the three, Put it back restores the project byte for byte, and the hub's state line
and strip follow.
"""
import json
import os
import re
import tempfile
from pathlib import Path

from playwright.sync_api import expect

from test_guided import RAW_DRAFT, guided_page, open_view, record_take, use_server_transcriber
from test_sections import WATCH_BUFFERS
from test_studio import wait_until

SHOTS = Path(os.environ.get("TANDEM_E2E_SHOTS") or tempfile.gettempdir())


def project(page):
    return json.loads(page.evaluate(RAW_DRAFT))


def blocks(page):
    return json.loads(page.locator("#sections").get_attribute("data-sections") or "[]")


def in_block(events, b, shift=0.0):
    return sorted((round(e["t"] - b["from"] + shift, 3), e.get("m", e.get("k"))) for e in events if b["from"] - 1e-3 <= e["t"] < b["to"] - 1e-3)


def played_buffers(page, button):
    """Press `button` (a Play), stop, and return the durations of the buffers it scheduled."""
    page.evaluate("window.bufs = []")
    page.click(button)
    wait_until(page, "() => window.bufs.length > 0", "Play scheduled its buffers")
    page.click("#gviewstop")
    return page.evaluate("window.bufs.map(b => b.duration)")


VOICE_AT = """([seconds, starts, from, to]) => {
  const b = window.bufs.find(x => Math.abs(x.duration - seconds) < 0.01);
  if (!b) return null;
  const x = b.getChannelData(0), r = b.sampleRate;
  // The samples of the take's stretch [from, to) at each start, and the largest gap between the first copy and the others.
  const n = Math.floor((to - from) * r), first = Math.round((starts[0] + from) * r);
  let peak = 0, gap = 0;
  // Each copy starts on a whole sample, so it may sit a sample or two off the first: the best of those alignments counts.
  for (const s of starts.slice(1)) {
    const at = Math.round((s + from) * r);
    let best = Infinity;
    for (let off = -2; off <= 2; off++) {
      let g = 0;
      for (let i = 0; i < n; i++) { peak = Math.max(peak, Math.abs(x[first + i])); g = Math.max(g, Math.abs(x[first + i] - x[at + off + i])); }
      best = Math.min(best, g);
    }
    gap = Math.max(gap, best);
  }
  return { peak, gap };
}"""


def test_play_it_again_twice_makes_three_blocks_of_every_part_and_the_voice(browser, server_url):
    with guided_page(browser, server_url) as page:
        page.evaluate(WATCH_BUFFERS)
        use_server_transcriber(page)
        record_take(page, 3)
        page.click("#gtakekeep")
        # Chords and a beat, and the voice in the song.
        open_view(page, "chords")
        # The fake microphone's beeps may not give a key: choose one.
        page.select_option("#gkeysel", "0:major")
        page.click("#gchords")
        expect(page.locator("#gharmstate")).to_have_text("Chords added")
        open_view(page, "beat")
        page.click("#ggrooveadd")
        expect(page.locator("#gdrumstate")).to_have_text(re.compile(r"^\d+ hits$"))
        page.click("#gviewdone")
        if not page.locator("#gvoicein").is_checked():
            page.click("#gvoicein")
        expect(page.locator("#gvoicein")).to_be_checked()
        # The hub: one part, Song shape suggested, no strip yet.
        expect(page.locator("#gtile-sections .gtstate")).to_have_text(re.compile(r"^One part, 0:\d\d$"))
        expect(page.locator("#gtile-sections .gtsuggest")).to_be_visible()
        expect(page.locator("#gstrip")).to_be_hidden()

        wait_until(page, f"async () => (await ({RAW_DRAFT})()).includes('\"drums\":[{{')", "the beat in the draft")
        start = page.evaluate(RAW_DRAFT)
        before = json.loads(start)
        assert not before.get("sections") and before.get("grid") is None

        # Song shape: the whole song is one block, Your idea, and nothing is written.
        open_view(page, "sections")
        expect(page.locator("#gh-view")).to_have_text("Song shape")
        expect(page.locator("#sections .secblock")).to_have_count(1)
        expect(page.locator("#sections .secblock strong")).to_have_text("Your idea")
        expect(page.locator("#sections .secblock small")).to_have_text(re.compile(r"^\d+ bars?$"))
        assert blocks(page) == []
        # The hum is shorter than the four-bar beat: the block can be only as long as the tune, and back.
        expect(page.locator("#gideafitbox")).to_be_visible()
        whole = page.locator("#sections .secblock small").text_content()
        page.check("#gideafit")
        expect(page.locator("#sections .secblock small")).not_to_have_text(whole)
        assert int(page.locator("#sections .secblock small").text_content().split()[0]) < int(whole.split()[0])
        page.uncheck("#gideafit")
        expect(page.locator("#sections .secblock small")).to_have_text(whole)
        assert page.evaluate(RAW_DRAFT) == start
        expect(page.locator("#sectionedit")).to_be_hidden()
        expect(page.locator("#gviewplays")).to_have_text("Plays the song")
        page.click('#sections .secblock[data-section="0"]')
        expect(page.locator("#sectionedit")).to_be_visible()
        expect(page.locator("#gviewplays")).to_have_text("Plays Your idea, round and round")
        # Choosing it wrote nothing.
        assert page.evaluate(RAW_DRAFT) == start

        page.click("#sectionrepeat")
        expect(page.locator("#sections .secblock")).to_have_count(2)
        # The first action wrote the block and pinned the bar grid in the same edit.
        wait_until(page, "async () => { const p = JSON.parse(await (" + RAW_DRAFT + ")()); return p.sections && p.sections.length === 2 && !!p.grid }",
                   "the draft has the blocks and the pinned grid")
        expect(page.locator("#bpmpinned")).to_be_attached()
        # The copy is chosen, so Play it again again makes the third.
        expect(page.locator('#sections .secblock[data-section="1"]')).to_have_attribute("aria-pressed", "true")
        page.click("#sectionrepeat")
        expect(page.locator("#sections .secblock")).to_have_count(3)
        three = blocks(page)
        assert [b["name"] for b in three] == ["Your idea"] * 3
        length = round(three[0]["to"] - three[0]["from"], 3)
        assert all(abs((b["to"] - b["from"]) - length) < 2e-3 for b in three)
        assert abs(three[1]["from"] - three[0]["to"]) < 2e-3 and abs(three[2]["from"] - three[1]["to"]) < 2e-3
        wait_until(page, "async () => JSON.parse(await (" + RAW_DRAFT + ")()).sections.length === 3", "three blocks in the draft")
        p = project(page)
        # The melody, chords and drums are each three times: each block holds what the first one does, shifted.
        for part in ("notes", "harmony", "drums"):
            first = in_block(p[part], three[0])
            assert first, part
            for b in three[1:]:
                copy = in_block(p[part], b)
                assert len(copy) == len(first) and all(abs(x[0] - y[0]) < 2e-3 and x[1] == y[1] for x, y in zip(copy, first)), part
            # Nothing outside the blocks was added: before the first block (a pickup) is as it was.
            assert [e for e in p[part] if e["t"] < three[0]["from"] - 1e-3] == [e for e in before[part] if e["t"] < three[0]["from"] - 1e-3], part
            assert len(p[part]) == len(before[part]) + 2 * len(in_block(before[part], three[0])), part
        # The voice plays at each block: its clips in the project, and the buffer Play schedules.
        # The take plays whole from zero (what is before the first block is its lead-in, heard once), and its stretch in the
        # first block plays again at the start of each copy.
        clips = sorted(p["placed"]["voice"], key=lambda c: c["at"])
        assert len(clips) == 3 and clips[0]["at"] == 0 and clips[0]["from"] == 0, clips
        for k in (1, 2):
            assert abs(clips[k]["from"] - three[0]["from"]) < 2e-3 and clips[k]["to"] == clips[0]["to"], clips
            assert abs(clips[k]["at"] - three[k]["from"]) < 2e-3, (clips, three)
        starts = [b["from"] for b in three]
        placed_end = max(c["at"] + c["to"] - c["from"] for c in clips)

        # Nothing chosen, Play plays the song: the voice laid out over three blocks, each copy the same samples.
        page.click('#sections .secblock[data-section="2"]')
        expect(page.locator("#gviewplays")).to_have_text("Plays the song")
        durations = played_buffers(page, "#gviewplay")
        assert any(abs(d - placed_end) < 0.01 for d in durations), (durations, placed_end)
        got = page.evaluate(VOICE_AT, [placed_end, starts, 0.05, clips[1]["to"] - clips[1]["from"] - 0.05])
        assert got and got["peak"] > 0.01 and got["gap"] < 1e-4, got

        # Undo takes one repeat off; Redo brings it back.
        page.click("#gundo")
        expect(page.locator("#sections .secblock")).to_have_count(2)
        page.click("#gredo")
        expect(page.locator("#sections .secblock")).to_have_count(3)
        page.click('#sections .secblock[data-section="0"]')
        expect(page.locator("#sectionearlier")).to_be_disabled()
        expect(page.locator("#sectionlater")).to_be_enabled()
        assert page.evaluate("document.scrollingElement.scrollWidth") <= 390
        page.screenshot(path=str(SHOTS / "grow4-shape.png"), full_page=True)
        page.click('#sections .secblock[data-section="0"]')
        # Before plays the song as the view opened (one block: the take whole, from zero); After the three.
        page.click("#gbefore")
        expect(page.locator("#gviewplays")).to_contain_text("Before")
        durations = played_buffers(page, "#gviewplay")
        assert not any(abs(d - placed_end) < 0.01 for d in durations), durations
        assert any(abs(d - clips[0]["to"]) < 0.01 for d in durations), (durations, clips[0])
        page.click("#gafter")
        durations = played_buffers(page, "#gviewplay")
        assert any(abs(d - placed_end) < 0.01 for d in durations), durations

        # Put it back: the project as it was when the view opened, byte for byte; Redo brings the three blocks back.
        page.click("#gputback")
        expect(page.locator("#status")).to_contain_text("made in Song shape")
        expect(page.locator("#sections .secblock")).to_have_count(1)
        wait_until(page, f"async () => (await ({RAW_DRAFT})()) === {json.dumps(start)}", "the draft as it was")
        page.click("#gredo")
        page.click("#gredo")
        expect(page.locator("#sections .secblock")).to_have_count(3)

        # The hub's state line and strip follow.
        page.click("#gviewdone")
        expect(page.locator("#gtile-sections .gtstate")).to_have_text(re.compile(r"^Your idea, Your idea, Your idea, \d:\d\d$"))
        expect(page.locator("#gstrip button")).to_have_count(3)
        expect(page.locator("#gtile-sections .gtsuggest")).to_be_hidden()
        assert page.evaluate("document.scrollingElement.scrollWidth") <= 390
        page.screenshot(path=str(SHOTS / "grow4-hub-tile.png"))
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(SHOTS / "grow4-hub.png"))
        # A tap on the strip plays the song from that block.
        page.click('#gstrip button[data-block="1"]')
        wait_until(page, f"() => {{ const t = Number(document.getElementById('timeline').dataset.t); return t >= {three[1]['from'] - 0.05} }}",
                   "playing from the second block")
        page.click("#gstop")
        # Undo on the hub takes the last repeat off, and the state line and strip follow.
        page.click("#gundo")
        expect(page.locator("#gtile-sections .gtstate")).to_have_text(re.compile(r"^Your idea, Your idea, \d:\d\d$"))
        expect(page.locator("#gstrip button")).to_have_count(2)


def test_a_block_is_named_and_moved_and_the_studio_has_the_same_tools(browser, server_url):
    with guided_page(browser, server_url) as page:
        page.click("#gdemo")
        page.wait_for_function("document.querySelectorAll('#melodyroll .note').length > 0")
        open_view(page, "sections")
        page.click('#sections .secblock[data-section="0"]')
        # Naming the idea writes it, with the grid pinned, as one edit.
        page.select_option("#sectionrename", "Verse")
        expect(page.locator("#gstatus")).to_have_text("Called Your idea Verse")
        assert [b["name"] for b in blocks(page)] == ["Verse"]
        page.click("#sectionrepeat")
        page.select_option("#sectionrename", "Chorus")
        assert [b["name"] for b in blocks(page)] == ["Verse", "Chorus"]
        page.click("#sectionearlier")
        assert [b["name"] for b in blocks(page)] == ["Chorus", "Verse"]
        expect(page.locator('#sections .secblock[data-section="0"]')).to_have_attribute("aria-pressed", "true")
        page.click("#gundo")
        assert [b["name"] for b in blocks(page)] == ["Verse", "Chorus"]
        # Copy the phrase is not offered in the guided view.
        expect(page.locator("#phrasecopy")).to_be_hidden()
        # In the studio the band has the blocks and the same tools.
        page.click("#gsettings")
        page.click("#gshowall")
        expect(page.locator("#lanes #sections .secblock")).to_have_count(2)
        page.click('#sections .secblock[data-section="1"]')
        expect(page.locator("#sectionrepeat")).to_be_visible()
        expect(page.locator("#sectionrename")).to_have_value("Chorus")


# A one-bar tune at 120 bpm (2 s bars) over a four-bar beat: the idea can be the beat's four bars or the tune's one.
SHORT_TUNE = {"format": "tandem-project", "version": 1, "bpm": 120, "instrument": "piano", "melody_locked": True,
              "notes": [{"m": m, "t": i * 0.5, "d": 0.5} for i, m in enumerate([60, 62, 64, 65])],
              "drums": [{"k": "kick" if q % 2 == 0 else "snare", "t": q * 0.5} for q in range(16)]}


def test_a_new_song_starts_with_the_whole_idea_not_only_the_tune(browser, server_url, tmp_path):
    """Only as long as the tune belongs to the song it was ticked for: the next song opened starts on the whole idea."""
    path = tmp_path / "short.json"
    path.write_text(json.dumps(SHORT_TUNE))
    with guided_page(browser, server_url) as page:
        for song in range(2):
            page.set_input_files("#projectfile", str(path))
            wait_until(page, "() => document.getElementById('notecount').textContent.startsWith('4')", "the tune opened")
            open_view(page, "sections")
            expect(page.locator("#gideafitbox")).to_be_visible()
            # Each song opens on the whole idea, the beat's four bars, with the box clear.
            expect(page.locator("#gideafit")).not_to_be_checked()
            expect(page.locator("#sections .secblock small")).to_have_text("4 bars")
            if song == 0:
                page.check("#gideafit")
                expect(page.locator("#sections .secblock small")).to_have_text("1 bar")
                page.click("#gviewback")
