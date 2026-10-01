"""Deployed tempo: work out SUTE and sorties per aircraft from whatever figures you have.

Units report deployed tempo in different ways. Each figure is one relationship
between three quantities: possessed aircraft (A), O&M days (D), and sorties (S).
Taking logs turns each into a straight line [M-9]:

    possessed aircraft            A          a
    O&M days                      D          d
    sorties                       S          s
    possessed aircraft days       A x D      a + d
    sorties per O&M day           S / D      s - d
    avg sorties per aircraft      S / A      s - a
    SUTE                          S / (A x D) s - a - d

Any figures that pin down s - a - d give the SUTE. Three independent figures
recover A, D, and S too. Rounded report figures that disagree slightly are fit
by least squares, and the largest disagreement is reported.
"""
from __future__ import annotations

import math
from typing import Any

FIGURES = {
    # name: (coefficients on (a, d, s), label)
    "possessed_aircraft": ((1, 0, 0), "Possessed aircraft"),
    "om_days": ((0, 1, 0), "O&M days"),
    "sorties": ((0, 0, 1), "Sorties"),
    "possessed_aircraft_days": ((1, 1, 0), "Possessed aircraft days"),
    "sorties_per_om_day": ((0, -1, 1), "Sorties per O&M day"),
    "avg_sorties_per_aircraft": ((-1, 0, 1), "Avg sorties per aircraft"),
    "sute": ((-1, -1, 1), "SUTE"),
}
ALIASES = {"monthly_sorties_per_aircraft": "avg_sorties_per_aircraft",   # older configs
           "paa": "possessed_aircraft", "deployed_aircraft": "possessed_aircraft"}
INPUTS = ("possessed_aircraft", "om_days", "sorties")   # what the form asks for; the rest are calculated
TARGET = (-1, -1, 1)
DAYS_PER_WEEK = 7   # deployed operations run every O&M day


def known_figures(block: dict[str, Any]) -> dict[str, float]:
    figures = {}
    for key, value in block.items():
        name = ALIASES.get(key, key)
        if name in FIGURES and value is not None:
            figures[name] = float(value)
    return figures


def _solve(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    """Gauss-Jordan for a small square system; None if singular."""
    n = len(matrix)
    m = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            return None
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                m[r] = [x - f * y for x, y in zip(m[r], m[col])]
    return [m[i][n] / m[i][i] for i in range(n)]


def solve_tempo(block: dict[str, Any] | None) -> dict[str, Any]:
    """Everything the figures determine. 'sute' is None if they can't pin it down. [M-9]"""
    figures = known_figures(block or {})
    out: dict[str, Any] = {"given": dict(figures), "sute": None, "possessed_aircraft": None, "om_days": None,
                           "sorties": None, "possessed_aircraft_days": None, "sorties_per_om_day": None,
                           "avg_sorties_per_aircraft": None, "per_aircraft_week": None, "mismatch": 0.0}
    if any(v <= 0 for v in figures.values()):
        return out
    rows = [FIGURES[n][0] for n in figures]
    logs = [math.log(v) for v in figures.values()]

    # Full solve when the figures pin down all three quantities.
    normal = [[sum(r[i] * r[j] for r in rows) for j in range(3)] for i in range(3)]
    x = _solve(normal, [sum(r[i] * b for r, b in zip(rows, logs)) for i in range(3)]) if rows else None
    if x is not None:
        a, d, s = x
        out.update(possessed_aircraft=math.exp(a), om_days=math.exp(d), sorties=math.exp(s),
                   possessed_aircraft_days=math.exp(a + d), sorties_per_om_day=math.exp(s - d),
                   avg_sorties_per_aircraft=math.exp(s - a), sute=math.exp(s - a - d))
        fitted = [sum(c * v for c, v in zip(r, x)) for r in rows]
        out["mismatch"] = max(abs(math.exp(f - b) - 1) for f, b in zip(fitted, logs))
    else:
        # Partial: find figures whose combination gives s - a - d exactly.
        k = len(rows)
        gram = [[sum(rows[i][c] * rows[j][c] for c in range(3)) for j in range(k)] for i in range(k)]
        rhs = [sum(rows[i][c] * TARGET[c] for c in range(3)) for i in range(k)]
        coeffs = _min_norm(gram, rhs)
        if coeffs is not None:
            combined = [sum(coeffs[i] * rows[i][c] for i in range(k)) for c in range(3)]
            if max(abs(u - v) for u, v in zip(combined, TARGET)) < 1e-9:
                out["sute"] = math.exp(sum(c * b for c, b in zip(coeffs, logs)))
        for name in ("possessed_aircraft", "om_days", "sorties", "possessed_aircraft_days",
                     "sorties_per_om_day", "avg_sorties_per_aircraft"):
            if name in figures:
                out[name] = figures[name]
        if out["avg_sorties_per_aircraft"] is None and out["sute"] and out["om_days"]:
            out["avg_sorties_per_aircraft"] = out["sute"] * out["om_days"]
    if "sute" in figures:
        out["sute"] = figures["sute"]
    if out["sute"]:
        out["per_aircraft_week"] = out["sute"] * DAYS_PER_WEEK
    return out


def _min_norm(gram: list[list[float]], rhs: list[float]) -> list[float] | None:
    """Solve gram c = rhs, dropping dependent rows (sets their weight to 0)."""
    k = len(gram)
    keep = []
    for i in range(k):
        trial = keep + [i]
        sub = [[gram[r][c] for c in trial] for r in trial]
        if _solve(sub, [0.0] * len(trial)) is not None:
            keep = trial
    if not keep:
        return None
    sub = [[gram[r][c] for c in keep] for r in keep]
    sol = _solve(sub, [rhs[r] for r in keep])
    if sol is None:
        return None
    coeffs = [0.0] * k
    for idx, value in zip(keep, sol):
        coeffs[idx] = value
    return coeffs


def home_requirements(sute: float, pai: int, flying_days: int) -> dict[str, int]:
    """Weekly sorties at home to match the deployed tempo, two ways [M-7].

    Matching SUTE flies the deployed rate per aircraft per day on each flying day.
    Matching sorties per aircraft gives each aircraft the deployed week's sorties
    in the home week's fewer flying days.
    """
    return {
        "match_sute": math.ceil(round(sute * pai * flying_days, 9)),
        "match_per_aircraft": math.ceil(round(sute * DAYS_PER_WEEK * pai, 9)),
    }
