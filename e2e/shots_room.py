"""FX.1 screenshots (not collected: run by path with SHOTS=<dir>)."""
import os

from playwright.sync_api import expect

from conftest import show_part
from test_guided import guided_page, open_view
from test_room import import_take, set_room
from test_mixer import open_song

SHOTS = os.environ.get("SHOTS", "/tmp")


def test_room_shots(studio, browser, server_url, tmp_path):
    page = studio
    page.set_viewport_size({"width": 1440, "height": 900})
    open_song(page, tmp_path)
    import_take(page, tmp_path)
    set_room(page, 0.3)
    show_part(page, "voice")
    page.locator("#roomgroup").scroll_into_view_if_needed()
    page.screenshot(path=f"{SHOTS}/studio-room.png")
    page.locator("#roomgroup").screenshot(path=f"{SHOTS}/studio-room-group.png")
    with guided_page(browser, server_url) as g:
        open_view(g, "sound")
        g.locator("#slot-room-voice").scroll_into_view_if_needed()
        expect(g.locator("#room-voice")).to_be_visible()
        g.screenshot(path=f"{SHOTS}/guided-sound-room.png")
