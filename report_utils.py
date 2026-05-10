from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Iterable


OUTPUT_DIR = Path("analysis_output")


def write_report(path: Path, title: str, sections: Iterable[str]) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    path.write_text(_document(title, sections), encoding="utf-8")
    print(f"Wrote {path}")


def card(title: str, value: str, note: str = "") -> str:
    note_html = f"<p>{escape(note)}</p>" if note else ""
    return (
        '<div class="card">'
        f"<span>{escape(title)}</span>"
        f"<strong>{escape(value)}</strong>"
        f"{note_html}</div>"
    )


def cards(items: Iterable[tuple[str, str, str]]) -> str:
    return '<div class="cards">' + "".join(card(*item) for item in items) + "</div>"


def table(
    headers: list[str],
    rows: list[list[object]],
    classes: list[list[str]] | None = None,
    row_attrs: list[dict[str, object]] | None = None,
) -> str:
    head = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body = []
    for row_index, row in enumerate(rows):
        cells = []
        attrs = ""
        if row_attrs and row_index < len(row_attrs):
            attrs = "".join(
                f' data-{escape(str(key))}="{escape(str(value))}"'
                for key, value in row_attrs[row_index].items()
            )
        for col_index, value in enumerate(row):
            css = ""
            if classes and row_index < len(classes) and col_index < len(classes[row_index]):
                css = f' class="{classes[row_index][col_index]}"' if classes[row_index][col_index] else ""
            cells.append(f"<td{css}>{escape(str(value))}</td>")
        body.append(f"<tr{attrs}>" + "".join(cells) + "</tr>")
    return f"<table><tr>{head}</tr>{''.join(body)}</table>"


def probability_class(value: float, threshold: float = 0.90) -> str:
    if value >= threshold:
        return "green"
    if value >= 0.70:
        return "yellow"
    return "red"


def pct(value: float, decimals: int = 0) -> str:
    return f"{value:.{decimals}%}"


def bar_chart(labels: list[str], values: list[float], title: str, unit: str) -> str:
    width = 980
    height = 360
    margin_left = 56
    margin_bottom = 120
    margin_top = 42
    plot_width = width - margin_left - 24
    plot_height = height - margin_top - margin_bottom
    max_value = max(max(values), 1) if values else 1
    bar_gap = 8
    bar_width = max(12, (plot_width - bar_gap * (len(values) - 1)) / max(len(values), 1))
    bars = []
    for index, value in enumerate(values):
        x = margin_left + index * (bar_width + bar_gap)
        bar_height = (value / max_value) * plot_height if max_value else 0
        y = margin_top + plot_height - bar_height
        label = escape(labels[index])
        value_label = f"{value:.1f}" if isinstance(value, float) and value % 1 else f"{int(value)}"
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" '
            f'height="{bar_height:.1f}" fill="#4d6f91"></rect>'
            f'<text x="{x + bar_width / 2:.1f}" y="{y - 5:.1f}" '
            f'text-anchor="middle" font-size="11">{value_label}</text>'
            f'<text transform="translate({x + bar_width / 2:.1f},{height - margin_bottom + 18}) '
            f'rotate(55)" text-anchor="start" font-size="11">{label}</text>'
        )
    return (
        '<div class="chart">'
        f'<svg width="{width}" height="{height}" role="img" aria-label="{escape(title)}">'
        f'<text x="{width / 2:.1f}" y="22" text-anchor="middle" '
        f'font-size="16" font-weight="700">{escape(title)}</text>'
        f'<text x="8" y="{margin_top + plot_height / 2:.1f}" '
        f'transform="rotate(-90 8,{margin_top + plot_height / 2:.1f})" '
        f'text-anchor="middle" font-size="12">{escape(unit)}</text>'
        f'<line x1="{margin_left}" y1="{margin_top + plot_height}" '
        f'x2="{width - 16}" y2="{margin_top + plot_height}" stroke="#6f7a85"></line>'
        f'<line x1="{margin_left}" y1="{margin_top}" '
        f'x2="{margin_left}" y2="{margin_top + plot_height}" stroke="#6f7a85"></line>'
        + "".join(bars)
        + "</svg></div>"
    )


def _document(title: str, sections: Iterable[str]) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape(title)}</title>
<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    margin: 32px;
    color: #172026;
    background: #f7f8fa;
}}
h1, h2, h3 {{ margin-bottom: 8px; }}
p {{ max-width: 1020px; line-height: 1.45; }}
.note, .recommendation, .methodology {{
    background: white;
    border-left: 5px solid #3a8f78;
    padding: 14px 18px;
    margin: 12px 0 24px;
    max-width: 1080px;
}}
.recommendation {{ border-left-color: #4d6f91; }}
.cards {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
    gap: 12px;
    max-width: 1180px;
    margin: 12px 0 26px;
}}
.card {{
    background: white;
    border: 1px solid #d8dde3;
    padding: 12px;
}}
.card strong {{
    display: block;
    font-size: 22px;
    margin-top: 4px;
}}
table {{
    border-collapse: collapse;
    background: white;
    margin: 12px 0 24px;
    min-width: 900px;
}}
th, td {{
    border: 1px solid #d8dde3;
    padding: 8px 10px;
    text-align: right;
    vertical-align: top;
}}
th:first-child, td:first-child {{ text-align: left; }}
th {{ background: #e8edf3; }}
.green {{ background: #e1f2e8; }}
.yellow {{ background: #fff2cc; }}
.red {{ background: #f8d9d9; }}
.caption {{ color: #52606d; font-size: 14px; }}
.filter-panel {{
    background: white;
    border: 1px solid #d8dde3;
    padding: 12px 16px;
    margin: 12px 0 24px;
    max-width: 540px;
}}
.filter-panel label {{
    display: block;
    font-weight: 700;
    margin-bottom: 6px;
}}
.filter-panel select {{
    font-size: 16px;
    padding: 6px 8px;
    width: 100%;
    max-width: 320px;
}}
.filter-panel input {{
    font-size: 16px;
    padding: 6px 8px;
    width: 100%;
    max-width: 300px;
    box-sizing: border-box;
}}
.best-fit-callout {{
    background: white;
    border-left: 5px solid #2f6f9f;
    padding: 14px 18px;
    margin: 12px 0 24px;
    max-width: 1180px;
}}
.callout-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 10px;
    margin-top: 10px;
}}
.callout-grid div {{
    border-top: 1px solid #edf0f2;
    padding-top: 8px;
}}
.callout-grid span {{
    display: block;
    color: #52606d;
    font-size: 12px;
}}
.callout-grid strong {{
    display: block;
    margin-top: 3px;
}}
.chart {{
    background: white;
    border: 1px solid #d8dde3;
    margin: 12px 0 28px;
    padding: 12px;
    width: fit-content;
}}
details {{
    background: white;
    border: 1px solid #d8dde3;
    padding: 12px 16px;
    margin: 18px 0 28px;
    max-width: 1220px;
}}
summary {{ cursor: pointer; font-weight: 700; }}
</style>
</head>
<body>
{''.join(sections)}
<script>
const paiFilter = document.getElementById("pai-filter");
const attritionFilter = document.getElementById("attrition-filter");
const requiredSortiesFilter = document.getElementById("required-sorties-filter");
const eventCountFilter = document.getElementById("event-count-filter");
const fixCountFilter = document.getElementById("fix-count-filter");
const modelFilter = document.getElementById("model-filter");
const uteFilter = document.getElementById("ute-filter");
const riskFilter = document.getElementById("risk-filter");
const familyFilter = document.getElementById("family-filter");
function applyFilters() {{
    const selectedPai = paiFilter ? paiFilter.value : "all";
    const selectedAttrition = attritionFilter ? attritionFilter.value : "all";
    const minimumRequiredSorties = requiredSortiesFilter && requiredSortiesFilter.value !== "" ? parseInt(requiredSortiesFilter.value, 10) : null;
    const selectedEventCount = eventCountFilter ? eventCountFilter.value : "all";
    const selectedFixCount = fixCountFilter ? fixCountFilter.value : "all";
    const selectedModel = modelFilter ? modelFilter.value : "all";
    const selectedUte = uteFilter ? uteFilter.value : "all";
    const selectedRisk = riskFilter ? riskFilter.value : "all";
    const selectedFamily = familyFilter ? familyFilter.value : "all";
    document.querySelectorAll("tr[data-pai], tr[data-attrition], tr[data-planned], tr[data-event-count], tr[data-fix-count], tr[data-model], tr[data-ute], tr[data-risk], tr[data-family], tr[data-backend]").forEach((row) => {{
        const paiMatch = selectedPai === "all" || row.dataset.pai === selectedPai || !row.dataset.pai;
        const attritionMatch = selectedAttrition === "all" || row.dataset.attrition === selectedAttrition || !row.dataset.attrition;
        const plannedSorties = row.dataset.planned ? parseInt(row.dataset.planned, 10) : null;
        const requiredSortiesMatch = minimumRequiredSorties === null || plannedSorties === null || plannedSorties >= minimumRequiredSorties;
        const eventCountMatch = selectedEventCount === "all" || row.dataset.eventCount === selectedEventCount || !row.dataset.eventCount;
        const fixCountMatch = selectedFixCount === "all" || row.dataset.fixCount === selectedFixCount || !row.dataset.fixCount;
        const modelMatch = selectedModel === "all" || row.dataset.model === selectedModel || !row.dataset.model;
        const uteMatch = selectedUte === "all" || row.dataset.ute === selectedUte || !row.dataset.ute;
        const riskMatch = selectedRisk === "all" || row.dataset.risk === selectedRisk || !row.dataset.risk;
        const familyMatch = selectedFamily === "all" || row.dataset.family === selectedFamily || !row.dataset.family;
        row.style.display = paiMatch && attritionMatch && requiredSortiesMatch && eventCountMatch && fixCountMatch && modelMatch && uteMatch && riskMatch && familyMatch ? "" : "none";
    }});
    updateBestFitCallout();
}}
[paiFilter, attritionFilter, eventCountFilter, fixCountFilter, modelFilter, uteFilter, riskFilter, familyFilter].forEach((filter) => {{
    if (filter) {{
        filter.addEventListener("change", applyFilters);
    }}
}});
if (requiredSortiesFilter) {{
    requiredSortiesFilter.addEventListener("input", applyFilters);
}}
function setText(id, value) {{
    const element = document.getElementById(id);
    if (element) element.textContent = value || "None";
}}
function updateBestFitCallout() {{
    const selectedModel = modelFilter ? modelFilter.value : "all";
    const candidates = Array.from(document.querySelectorAll('tr[data-role="best-fit"]'))
        .filter((row) => row.style.display !== "none")
        .filter((row) => selectedModel === "all" || row.dataset.model === selectedModel)
        .filter((row) => row.dataset.risk === "Green" || row.dataset.risk === "Yellow");
    candidates.sort((a, b) => {{
        if (selectedModel === "all" && a.dataset.model !== b.dataset.model) {{
            if (a.dataset.model === "Fleet-Flex Recovery") return -1;
            if (b.dataset.model === "Fleet-Flex Recovery") return 1;
        }}
        const successDelta = parseFloat(b.dataset.success || "0") - parseFloat(a.dataset.success || "0");
        if (successDelta) return successDelta;
        const scoreDelta = parseFloat(b.dataset.score || "0") - parseFloat(a.dataset.score || "0");
        if (scoreDelta) return scoreDelta;
        return parseInt(a.dataset.friday || "999", 10) - parseInt(b.dataset.friday || "999", 10);
    }});
    const best = candidates[0];
    const empty = document.getElementById("best-fit-empty");
    const detail = document.getElementById("best-fit-detail");
    if (!best) {{
        if (empty) empty.style.display = "";
        if (detail) detail.style.display = "none";
        return;
    }}
    if (empty) empty.style.display = "none";
    if (detail) detail.style.display = "";
    setText("callout-pattern", best.dataset.patternDisplay);
    setText("callout-name", best.dataset.name);
    setText("callout-pai", best.dataset.pai);
    setText("callout-attrition", best.dataset.attrition);
    setText("callout-event-count", best.dataset.eventCount);
    setText("callout-fix-count", best.dataset.fixCount);
    setText("callout-ute", best.dataset.ute);
    setText("callout-planned", best.dataset.planned);
    setText("callout-required", best.dataset.required);
    setText("callout-frontlines", best.dataset.frontlines);
    setText("callout-backend-frontlines", best.dataset.backendFrontlines);
    setText("callout-commit", best.dataset.commit);
    setText("callout-turns", best.dataset.turns);
    setText("callout-backend", best.dataset.backend);
    setText("callout-friday", best.dataset.friday);
    setText("callout-success", best.dataset.successText);
    setText("callout-nextmon", best.dataset.nextmon);
    setText("callout-debt", best.dataset.debt);
}}
updateBestFitCallout();
</script>
</body>
</html>
"""
