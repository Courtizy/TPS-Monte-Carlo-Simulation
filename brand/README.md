# brand/

Drop-in brand kit for the Decision Models portfolio (Turn Pattern Sustainability, Project ROI, Valuation Model, Shared Core). Copy this whole folder into each repo. It's the same folder everywhere; one attribute on each page picks the app.

## Use it on a GitHub Pages site

1. Copy `brand/` into the folder Pages publishes (the repo root, or `docs/` if Pages serves from there).
2. In each page's `<head>`, swap `tps` for `roi`, `valuation` or `core` as needed:

```html
<html lang="en" data-app="tps">
<link rel="stylesheet" href="brand/css/brand.css">
<link rel="icon" type="image/svg+xml" href="brand/icons/tps.svg">
<link rel="icon" type="image/png" sizes="32x32" href="brand/icons/tps-32.png">
<link rel="apple-touch-icon" href="brand/icons/tps-180.png">
```

3. Use the ready-made pieces: `.brand-header`, `.brand-card`, `.brand-footer` (holds the disclaimer), and `.status--good | --warning | --critical`. `example.html` shows all of them. Copy it next to `brand/` to try it.

**Dark and light mode.** Dark is the default. Light mode follows the visitor's OS setting. To force one, add `data-theme="dark"` or `data-theme="light"` to `<html>`.

**CSS variables you can use:** `--page`, `--panel`, `--line`, `--ink`, `--ink-secondary`, `--brand-fill`, `--accent`, `--series-1` … `--series-5`, `--seq-1` … `--seq-7`, `--div-1` … `--div-7`, `--status-good` (marks) and `--status-good-text` (words), and the same for warning and critical.

## Charts in the browser

```html
<script type="module">
  import { series, sequential, plotlyLayout, onModeChange } from "./brand/js/palette.js";
  const colors = series("tps");            // slot 1 = this app's color, max 5
  // Plotly.js: Plotly.react(el, data, { ...plotlyLayout("tps"), ...yourLayout });
  // Chart.js / D3 / anything else: use the hex values from series() and sequential().
  onModeChange(redraw);                    // recolor when dark/light changes
</script>
```

## Charts and Excel in Python

`palette.py` has the same values (it's the source for everything else): `series(app, mode)`, `sequential(app, mode)`, `plotly_template(app, mode)` and `excel_hex()` for openpyxl. Once Shared Core exists, move `palette.py` there and keep this folder for the web assets.

## README banners and social previews

On Windows, run `powershell -ExecutionPolicy Bypass -File .\brand\render.ps1`. It sets up a private Python environment the first time, installs Playwright, rebuilds, runs the tests and renders. Elsewhere, run `python brand/render.py` (needs `pip install playwright` and `playwright install chromium`). Either way it needs internet. It writes:

- `banners/<app>-readme.png` (1280×320). Put it at the top of each README: `![Turn Pattern Sustainability](brand/banners/tps-readme.png)`
- `banners/<app>-social.png` (1280×640). Upload it in GitHub under **Settings → General → Social preview**.

## Changing colors

Edit `palette.py` only, then run `python brand/build.py` (rebuilds the CSS, JS, `tokens.json` and SVG icons) and `python brand/render.py` (rebuilds the PNGs). Run `pytest brand/` to confirm contrast and slot order still pass. The series orders were checked as a set for color-blind safety. If you change a chart color, re-run that check before shipping (the dataviz palette validator, against both surfaces).

## Rules

- Slot 1 is always the app's own color. Never reorder or cycle the slots.
- Use 5 series at most. Beyond that, fold the rest into "Other" or use small multiples.
- Chart marks use the series colors, never the brand fill.
- Text uses the ink colors, never series colors (links use `--accent`).
- Good and bad meanings get status colors with an icon and a label. Brand colors never carry that meaning.
- Keep the disclaimer footer on every page.
