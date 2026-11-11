"""Render the app icons (MOB.2) from icons/icon.svg and icons/icon-maskable.svg with headless Chromium.

    python -m pip install -r requirements-e2e.txt && python -m playwright install chromium
    python tools/icons/build.py

Writes icons/icon-192.png and icons/icon-512.png (rounded, transparent corners, manifest purpose "any"),
icons/icon-maskable-512.png (full bleed, purpose "maskable") and icons/apple-touch-icon.png (180x180,
full bleed and opaque, because iOS rounds the corners itself and shows transparency as black).
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

ICONS = Path(__file__).resolve().parents[2] / "icons"
OUTPUTS = (("icon.svg", "icon-192.png", 192), ("icon.svg", "icon-512.png", 512),
           ("icon-maskable.svg", "icon-maskable-512.png", 512), ("icon-maskable.svg", "apple-touch-icon.png", 180))


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for source, target, size in OUTPUTS:
            page = browser.new_page(viewport={"width": size, "height": size}, device_scale_factor=1)
            svg = (ICONS / source).read_text()
            page.set_content(f'<style>html,body{{margin:0;background:transparent}}svg{{display:block;width:{size}px;height:{size}px}}</style>{svg}')
            page.screenshot(path=str(ICONS / target), omit_background=True, clip={"x": 0, "y": 0, "width": size, "height": size})
            page.close()
            print("wrote", ICONS / target)
        browser.close()


if __name__ == "__main__":
    main()
