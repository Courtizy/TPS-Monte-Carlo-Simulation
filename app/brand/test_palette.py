"""Guards the palette's validated properties. Run with ``pytest``.

The full CVD / OKLab checks were run with the dataviz validator when the
palette was set; these tests catch accidental edits to contrast and structure.
"""

import pytest

import palette as p


@pytest.mark.parametrize("app", p.APPS)
def test_white_text_on_brand_fill(app):
    assert p.contrast(p.ON_BRAND_FILL, p.BRAND_FILL[app]) >= 4.5


@pytest.mark.parametrize("mode", p.MODES)
@pytest.mark.parametrize("app", p.APPS)
def test_series_contrast_on_both_surfaces(app, mode):
    for color in p.series(app, mode):
        for surface in ("page", "panel"):
            assert p.contrast(color, p.SURFACE[mode][surface]) >= 3.0, (color, surface)


@pytest.mark.parametrize("mode", p.MODES)
@pytest.mark.parametrize("app", p.APPS)
def test_accent_text_is_readable(app, mode):
    assert p.contrast(p.ACCENT_TEXT[mode][app], p.SURFACE[mode]["page"]) >= 4.5


@pytest.mark.parametrize("mode", p.MODES)
def test_ink_contrast(mode):
    s = p.SURFACE[mode]
    assert p.contrast(s["ink"], s["page"]) >= 7
    assert p.contrast(s["ink_secondary"], s["page"]) >= 4.5


@pytest.mark.parametrize("app", p.APPS)
def test_slot_one_is_own_color(app):
    assert p.SERIES_ORDER[app][0] == app
    assert len(set(p.SERIES_ORDER[app])) == p.MAX_SERIES


def test_too_many_series_raises():
    with pytest.raises(ValueError):
        p.series("tps", "dark", p.MAX_SERIES + 1)


def test_status_never_reuses_series_colors():
    for mode in p.MODES:
        assert not set(p.STATUS[mode].values()) & set(p.SERIES[mode].values())


@pytest.mark.parametrize("mode", p.MODES)
def test_status_text_is_readable(mode):
    for color in p.STATUS_TEXT[mode].values():
        for surface in ("page", "panel"):
            assert p.contrast(color, p.SURFACE[mode][surface]) >= 4.5, (color, surface)


def test_tokens_cover_every_app():
    t = p.all_tokens()
    assert set(t["apps"]) == set(p.APPS)
    assert t["endorsement"] == "by Jason C. Courtoy"
