"""Security audit H1: names from an opened project are text, never markup.

A shared project (a JSON file or a Tandem file) can carry a recorded layer's name. The mixer strip put that
name into aria-label attributes through innerHTML, so a name that closes the attribute could add an element
with an event handler and run script in the studio's origin. The name must reach the page only as text.
"""
import json

from playwright.sync_api import expect

PAYLOAD = '"><img src=x onerror="window.__pwned=1">'


def test_a_layer_name_from_an_opened_project_is_text_not_markup(studio, tmp_path):
    page = studio
    lid = "abcdefabcdef"
    project = {"format": "tandem-project", "version": 1, "bpm": 100, "instrument": "piano", "melody_locked": True,
               "notes": [{"m": 60, "t": 0, "d": 0.5}], "drums": [],
               "layers": [{"id": lid, "name": PAYLOAD, "seconds": 2}]}
    assert len(PAYLOAD) <= 40
    path = tmp_path / "shared.json"
    path.write_text(json.dumps(project))
    page.set_input_files("#projectfile", str(path))
    expect(page.locator("#status")).to_have_text("Project opened")
    strip = page.locator(f'.mixstrip[data-mix="layer-{lid}"]')
    expect(strip).to_have_count(1)
    assert page.locator(".mixstrip img").count() == 0
    assert page.evaluate("window.__pwned") is None
    expect(page.locator(f"#mute-layer-{lid}")).to_have_attribute("aria-label", "Mute " + PAYLOAD)
    expect(page.locator(f"#solo-layer-{lid}")).to_have_attribute("aria-label", "Solo " + PAYLOAD)
    expect(page.locator(f"#level-layer-{lid}")).to_have_attribute("aria-label", "Level of " + PAYLOAD)
