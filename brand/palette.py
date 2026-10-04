"""Brand and chart colors for the Decision Models portfolio.

One source of truth for Turn Pattern Sustainability, Project ROI and the
Valuation Model. ``build.py`` turns this file into the web assets
(``css/brand.css``, ``js/palette.js``, ``tokens.json``, ``icons/*.svg``), so
GitHub Pages sites, Python charts and Excel exports all use the same values.
Edit colors HERE, then run ``python brand/build.py``.

Validated with the dataviz palette checks (OKLab ΔE ×100, Machado 2009 CVD
simulation) on 2026-10-03:

    App order                     Light (CVD / normal)   Dark (CVD / normal)
    TPS  -> ROI VAL PLUM SKY      13.4 / 23.6            12.0 / 17.1
    ROI  -> TPS VAL PLUM SKY      13.4 / 23.6            12.0 / 17.1
    VAL  -> TPS ROI SKY  PLUM     13.4 / 23.6            12.0 / 18.1

All series clear 3:1 against both chart surfaces in their mode. The first
three slots also pass the all-pairs check (scatter, small multiples).
Targets: CVD ΔE >= 8, normal-vision ΔE >= 15, marks >= 3:1.

Rules (see claude/portfolio_branding_decisions.md):
  * Slot 1 is always the app's own color. Never reorder or cycle slots.
  * Max 5 series per chart. More than that: fold into "Other" or facet.
  * Text uses INK colors, never series colors (links/accents excepted).
  * Status colors are reserved for good/warning/critical and always ship
    with an icon and a label. There is no "serious" level: it would sit too
    close to Project ROI orange.
"""

from __future__ import annotations

from typing import Literal

App = Literal["tps", "roi", "valuation"]
Mode = Literal["light", "dark"]

APPS: tuple[App, ...] = ("tps", "roi", "valuation")
MODES: tuple[Mode, ...] = ("light", "dark")

# ---------------------------------------------------------------------------
# Brand identity
# ---------------------------------------------------------------------------

APP_NAMES: dict[App, str] = {
    "tps": "Turn Pattern Sustainability",
    "roi": "Project ROI",
    "valuation": "Valuation Model",
}

APP_SHORT: dict[App, str] = {"tps": "TPS", "roi": "Project ROI", "valuation": "Valuation"}

APP_QUESTIONS: dict[App, str] = {
    "tps": "Can the fleet meet the flying schedule?",
    "roi": "Which projects earn funding under real limits?",
    "valuation": "What is the business worth, and how sure are we?",
}
#: Position in the operations -> capital -> deals sequence.
APP_STEP: dict[App, str] = {"tps": "01 · Operations", "roi": "02 · Capital", "valuation": "03 · Deals"}

CORE_NAME = "Shared Core"
CORE_QUESTION = "How likely is each outcome?"

ENDORSEMENT = "by Jason C. Courtoy"
DISCLAIMER = (
    "Personal project · public or synthetic data only · "
    "not endorsed by DoD or the U.S. Air Force"
)

FONTS = {
    "sans": "'Space Grotesk', system-ui, -apple-system, 'Segoe UI', sans-serif",
    "mono": "'JetBrains Mono', ui-monospace, 'SFMono-Regular', Menlo, monospace",
    "google_css": (
        "https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700"
        "&family=JetBrains+Mono:wght@400;600&display=swap"
    ),
}

#: Icon marks on a 64×64 grid, stroke-width 4, round caps. Drawn in white on
#: the brand fill, or in currentColor for the mark-only versions.
ICON_PATHS: dict[str, str] = {
    "tps": '<path d="M52 32a20 20 0 1 1-6-14.3"/><path d="M48 8v10H38"/>'
           '<circle cx="32" cy="32" r="4" fill="currentColor"/>',
    "roi": '<path d="M12 52V40"/><path d="M26 52V30"/><path d="M40 52V22"/>'
           '<path d="M10 26l14-10 10 6 18-12"/><path d="M44 10h8v8"/>',
    "valuation": '<path d="M14 16h26"/><path d="M22 28h30"/><path d="M10 40h28"/><path d="M24 52h22"/>',
    "core": '<path d="M32 6l22 13v26L32 58 10 45V19z"/><path d="M32 22l9 5v10l-9 5-9-5V27z"/>',
}

#: Solid brand fills: icon tiles, header bars, primary buttons, sliders.
#: White text on each clears WCAG AA (5.47 / 5.67 / 6.29 : 1).
BRAND_FILL: dict[App, str] = {
    "tps": "#0F766E",
    "roi": "#B4410C",
    "valuation": "#4F46E5",
}
ON_BRAND_FILL = "#FFFFFF"

#: Shared Core has no fill; it is drawn as an outline.
CORE_OUTLINE = "#4A5866"

# ---------------------------------------------------------------------------
# Surfaces and ink
# ---------------------------------------------------------------------------

SURFACE: dict[Mode, dict[str, str]] = {
    "dark": {
        "page": "#111A24",       # app background / chart surface
        "panel": "#1A2430",      # cards, sidebar, secondary background
        "line": "#2E3B48",       # borders, gridlines
        "ink": "#EEF1F4",        # primary text (15.5:1)
        "ink_secondary": "#B6C0CA",  # 9.5:1
        "ink_muted": "#8592A0",  # axis labels (5.5:1)
    },
    "light": {
        "page": "#F7F8FA",
        "panel": "#FFFFFF",
        "line": "#D5DAE0",
        "ink": "#111A24",        # 16.5:1
        "ink_secondary": "#4A5866",  # 6.9:1
        "ink_muted": "#6B7785",  # 4.3:1, large text and axis labels only
    },
}

# ---------------------------------------------------------------------------
# Chart series (categorical)
# ---------------------------------------------------------------------------

#: Chart-mark steps of each hue, tuned per mode. The brand fills are not
#: used as chart marks: teal #0F766E reads gray at chart size and all three
#: fills fall below 3:1 on the dark surface.
SERIES: dict[Mode, dict[str, str]] = {
    "light": {
        "tps": "#0A8D83",
        "roi": "#B4410C",
        "valuation": "#4F46E5",
        "plum": "#944561",
        "sky": "#1F93B8",
    },
    "dark": {
        "tps": "#1EA89D",
        "roi": "#D26B45",
        "valuation": "#7882E0",
        "plum": "#A4587D",
        "sky": "#1997CF",
    },
}

#: Fixed slot order per app. Validated as a set; do not edit one entry alone.
SERIES_ORDER: dict[App, tuple[str, ...]] = {
    "tps": ("tps", "roi", "valuation", "plum", "sky"),
    "roi": ("roi", "tps", "valuation", "plum", "sky"),
    "valuation": ("valuation", "tps", "roi", "sky", "plum"),
}

MAX_SERIES = 5

#: Accent text and links. Light uses the brand fill; dark uses the chart step.
ACCENT_TEXT: dict[Mode, dict[App, str]] = {
    "light": dict(BRAND_FILL),
    "dark": {app: SERIES["dark"][app] for app in APPS},
}

# ---------------------------------------------------------------------------
# Sequential, diverging, status
# ---------------------------------------------------------------------------

#: Seven steps, light -> dark, in each app's own hue (OKLCH L 0.94 -> 0.41).
SEQUENTIAL: dict[App, tuple[str, ...]] = {
    "tps": ("#D2F3EF", "#A4DED7", "#70C6BD", "#3EACA2", "#089087", "#00736B", "#005750"),
    "roi": ("#FEE5DD", "#FFC0AB", "#F39A7B", "#DD7955", "#C15B35", "#A0421D", "#7E2C08"),
    "valuation": ("#E6EAFD", "#C5CEFF", "#A1ADFF", "#818CF9", "#676EDF", "#4F54BC", "#3A3C96"),
}

#: Polarity (above/below a baseline that is not good/bad). Indigo <-> orange.
DIVERGING: dict[Mode, tuple[str, ...]] = {
    "light": ("#4F54BC", "#818CF9", "#C5CEFF", "#E4E7EB", "#FFC0AB", "#DD7955", "#A0421D"),
    "dark": ("#4F54BC", "#818CF9", "#C5CEFF", "#3A4552", "#FFC0AB", "#DD7955", "#A0421D"),
}

#: Reserved meaning. Always pair with an icon and a label.
STATUS: dict[Mode, dict[str, str]] = {
    "dark": {"good": "#0CA30C", "warning": "#FAB219", "critical": "#D03B3B"},
    "light": {"good": "#1E8A1E", "warning": "#9A6A00", "critical": "#C02F2F"},
}
#: Status as TEXT (labels, chips): darker/lighter steps so words clear 4.5:1
#: on both page and panel. Use STATUS for marks, STATUS_TEXT for words.
STATUS_TEXT: dict[Mode, dict[str, str]] = {
    "dark": {"good": "#0CA30C", "warning": "#FAB219", "critical": "#EF6A6A"},
    "light": {"good": "#1A7A1A", "warning": "#875D00", "critical": "#B42A2A"},
}
STATUS_ICON = {"good": "✓", "warning": "!", "critical": "✕"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def series(app: App, mode: Mode = "dark", n: int = MAX_SERIES) -> list[str]:
    """Hex colors for ``n`` chart series in ``app``, slot 1 = the app's color."""
    if not 1 <= n <= MAX_SERIES:
        raise ValueError(
            f"{n} series requested; max is {MAX_SERIES}. Fold the rest into 'Other' or facet."
        )
    return [SERIES[mode][key] for key in SERIES_ORDER[app][:n]]


def sequential(app: App, mode: Mode = "dark") -> list[str]:
    """Low -> high magnitude ramp. In dark mode low values sit near the surface."""
    ramp = list(SEQUENTIAL[app])
    return ramp[::-1] if mode == "dark" else ramp


def tokens(app: App, mode: Mode = "dark") -> dict[str, str]:
    """Flat token set for one app in one mode (for templates and CSS)."""
    return {
        **SURFACE[mode],
        "brand": BRAND_FILL[app],
        "on_brand": ON_BRAND_FILL,
        "accent_text": ACCENT_TEXT[mode][app],
        **{f"series_{i + 1}": c for i, c in enumerate(series(app, mode))},
        **{f"status_{k}": v for k, v in STATUS[mode].items()},
    }


def all_tokens() -> dict:
    """Everything, as plain JSON-ready data (written to ``tokens.json``)."""
    return {
        "apps": {
            app: {
                "name": APP_NAMES[app],
                "short": APP_SHORT[app],
                "question": APP_QUESTIONS[app],
                "step": APP_STEP[app],
                "brandFill": BRAND_FILL[app],
                "seriesOrder": list(SERIES_ORDER[app]),
                "sequential": list(SEQUENTIAL[app]),
            }
            for app in APPS
        },
        "core": {"name": CORE_NAME, "question": CORE_QUESTION, "outline": CORE_OUTLINE},
        "onBrandFill": ON_BRAND_FILL,
        "surface": SURFACE,
        "series": SERIES,
        "accentText": ACCENT_TEXT,
        "diverging": {m: list(v) for m, v in DIVERGING.items()},
        "status": STATUS,
        "statusText": STATUS_TEXT,
        "maxSeries": MAX_SERIES,
        "endorsement": ENDORSEMENT,
        "disclaimer": DISCLAIMER,
        "fonts": FONTS,
    }


def plotly_template(app: App, mode: Mode = "dark"):
    """A Plotly template using this app's colors. Requires ``plotly``."""
    import plotly.graph_objects as go

    s = SURFACE[mode]
    axis = dict(gridcolor=s["line"], linecolor=s["line"], zerolinecolor=s["line"],
                tickfont=dict(color=s["ink_muted"]), title_font=dict(color=s["ink_secondary"]))
    return go.layout.Template(
        layout=dict(
            colorway=series(app, mode),
            paper_bgcolor=s["page"],
            plot_bgcolor=s["page"],
            font=dict(family="Space Grotesk, system-ui, sans-serif", color=s["ink"]),
            colorscale=dict(sequential=sequential(app, mode), diverging=list(DIVERGING[mode])),
            xaxis=axis,
            yaxis=axis,
            legend=dict(font=dict(color=s["ink_secondary"])),
            hoverlabel=dict(bgcolor=s["panel"], bordercolor=s["line"], font_color=s["ink"]),
        )
    )


def excel_hex(color: str) -> str:
    """'#0F766E' -> '0F766E' for openpyxl fills and fonts."""
    return color.lstrip("#").upper()


def contrast(a: str, b: str) -> float:
    """WCAG 2.x contrast ratio between two hex colors."""

    def lum(h: str) -> float:
        rgb = [int(h.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)
