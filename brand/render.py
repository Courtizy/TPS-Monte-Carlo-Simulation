"""Render PNG images from the brand assets. Needs Playwright:

    pip install playwright && playwright install chromium
    python brand/render.py

Writes, next to this file:
    icons/<app>-32.png, icons/<app>-180.png     favicon + Apple touch icon
    banners/<app>-readme.png   1280×320        top of each README
    banners/<app>-social.png   1280×640        GitHub Settings → Social preview
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

import palette as p

HERE = Path(__file__).resolve().parent
D = p.SURFACE["dark"]


def _tile(key: str, size: int) -> str:
    svg = (HERE / "icons" / f"{key}.svg").read_text(encoding="utf-8")
    return svg.replace('width="64" height="64"', f'width="{size}" height="{size}"', 1)


def _banner_html(key: str, w: int, h: int) -> str:
    social = h > 400
    if key == "core":
        name, question, step, stripe = p.CORE_NAME, p.CORE_QUESTION, "Foundation · Monte Carlo", p.CORE_OUTLINE
    else:
        name, question, step, stripe = p.APP_NAMES[key], p.APP_QUESTIONS[key], p.APP_STEP[key], p.BRAND_FILL[key]
    tile = 220 if social else 168
    name_size = 72 if social else 58
    footer = (f'<div style="position:absolute;left:96px;right:96px;bottom:56px;font-size:20px;'
              f'color:{D["ink_secondary"]}">{p.DISCLAIMER}</div>') if social else ""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="{p.FONTS['google_css']}">
<style>body{{margin:0}}</style></head><body>
<div style="position:relative;width:{w}px;height:{h}px;background:{D['page']};color:{D['ink']};
font-family:{p.FONTS['sans']};border-top:10px solid {stripe};box-sizing:border-box;
display:flex;align-items:center;gap:56px;padding:0 96px">
  {_tile(key, tile)}
  <div style="display:flex;flex-direction:column;gap:{14 if social else 10}px">
    <div style="font-size:{20 if social else 18}px;font-weight:500;letter-spacing:3px;color:{D['ink_secondary']}">{step.upper()}</div>
    <div style="font-size:{name_size}px;font-weight:700;line-height:1.05">{name}</div>
    <div style="font-size:{30 if social else 28}px;font-weight:500">{question}</div>
    <div style="font-size:{24 if social else 20}px;color:{D['ink_secondary']}">{p.ENDORSEMENT}</div>
  </div>
  {footer}
</div></body></html>"""


def main() -> None:
    (HERE / "banners").mkdir(exist_ok=True)
    keys = [*p.APPS, "core"]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        for key in keys:
            for size in (32, 180):
                page.set_viewport_size({"width": size, "height": size})
                page.set_content(f'<body style="margin:0">{_tile(key, size)}</body>')
                page.screenshot(path=str(HERE / "icons" / f"{key}-{size}.png"), omit_background=True)
            for kind, (w, h) in {"readme": (1280, 320), "social": (1280, 640)}.items():
                page.set_viewport_size({"width": w, "height": h})
                page.set_content(_banner_html(key, w, h))
                page.wait_for_load_state("networkidle")
                page.evaluate("document.fonts.ready")
                if not page.evaluate("[...document.fonts].some(f => f.family.includes('Space Grotesk') && f.status === 'loaded')"):
                    raise SystemExit("Space Grotesk didn't load (no internet?). Banners not rendered; try again online.")
                page.screenshot(path=str(HERE / "banners" / f"{key}-{kind}.png"))
        browser.close()
    print("Rendered favicons, README banners and social previews for", ", ".join(keys))


if __name__ == "__main__":
    main()
