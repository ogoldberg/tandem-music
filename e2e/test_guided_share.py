"""UX.8: Share plays the song it is about to send, and lists what is in it.

On a 390 px phone: Play on Share plays the song as the mixer has it (#timeline's data-mix while it plays), "In your song" has
one line for each part the song has and none for a part it lacks, each line's Change opens that part's view, and Done there
comes back to Share (the view's own way back still goes to Your song).
"""
import json

from playwright.sync_api import expect

from test_guided import guided_page

LINES = "() => [...document.querySelectorAll('#gsongparts li')].map(li => [li.dataset.view, li.querySelector('span').textContent])"


def to_share(page):
    page.click('#steps [data-step="share"]')
    expect(page.locator('[data-panel="share"]')).to_be_visible()


def test_share_plays_the_song_and_lists_only_the_parts_it_has(browser, server_url):
    with guided_page(browser, server_url) as page:
        # Nothing yet: no lines, and the card says so.
        to_share(page)
        expect(page.locator("#gsongparts li")).to_have_count(0)
        expect(page.locator("#gsongnone")).to_be_visible()

        # The example has a tune and a beat, and nothing else.
        page.click('#steps [data-step="sing"]')
        page.click("#gdemo")
        page.wait_for_function("document.querySelectorAll('#melodyroll .note').length > 0")
        to_share(page)
        assert page.evaluate(LINES) == [["notes", "Notes: 8 notes"], ["beat", "Beat: 16 hits"]]
        expect(page.locator("#gsongnone")).to_be_hidden()
        for absent in ("voice", "words", "chords", "voice2"):
            expect(page.locator(f'#gsongparts li[data-view="{absent}"]')).to_have_count(0)

        # Play on Share plays the mix: the playhead moves and the gains of the parts present are set.
        page.click("#gshareplay")
        page.wait_for_function("Number(document.getElementById('timeline').dataset.t || 0) > 0.2", timeout=20_000)
        mix = json.loads(page.get_attribute("#timeline", "data-mix"))
        assert mix.get("melody", 0) > 0 and mix.get("drums", 0) > 0, mix
        page.click("#gsharestop")

        # Change on Beat opens the Beat view; Done comes back to Share.
        page.click('#gsongparts li[data-view="beat"] button')
        expect(page.locator('[data-panel="view"]')).to_be_visible()
        expect(page.locator('.gview[data-view="beat"]')).to_be_visible()
        expect(page.locator("#gh-view")).to_have_text("Beat")
        page.click("#gviewdone")
        expect(page.locator('[data-panel="share"]')).to_be_visible()
        expect(page.locator('#steps [aria-current="step"]')).to_contain_text("Share")

        # Change on Notes, a step to the next view, and an edit there: Done still comes back to Share, which now lists it.
        page.click('#gsongparts li[data-view="notes"] button')
        expect(page.locator('.gview[data-view="notes"]')).to_be_visible()
        page.click("#gviewprev")
        page.click("#gviewnext")
        page.click("#gviewnext")
        page.click("#gviewnext")
        expect(page.locator('.gview[data-view="words"]')).to_be_visible()
        page.fill("#lyrics", "la la la")
        page.locator("#lyrics").blur()
        page.click("#gviewdone")
        expect(page.locator('[data-panel="share"]')).to_be_visible()
        assert [v for v, _ in page.evaluate(LINES)] == ["notes", "words", "beat"]
        expect(page.locator('#gsongparts li[data-view="words"] span')).to_have_text("Words: 3 words")

        # The view's own way back still goes to Your song, and Done from a tile goes there too.
        page.click('#gsongparts li[data-view="words"] button')
        page.click("#gviewback")
        expect(page.locator('[data-panel="song"]')).to_be_visible()
        page.click("#gtile-beat")
        page.click("#gviewdone")
        expect(page.locator('[data-panel="song"]')).to_be_visible()
        to_share(page)
        assert page.evaluate("document.scrollingElement.scrollWidth") <= 390
