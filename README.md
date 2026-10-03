# Turn Pattern Sustainability

**Can the fleet meet the flying schedule?** TPS plays a weekly flying schedule out thousands of times, with breaks, aborts, and fixes drawn from a unit's own rates, and reports how often the plan holds, where it breaks, why, and what would fix it. It runs entirely in the browser: no plan, history file, or result is sent to a server.

Personal project · public or synthetic data only · not endorsed by DoD or the U.S. Air Force.

## Repo layout

The folders follow the portfolio's app framework (`app_layer_frameworks.md`): each model layer has its own folder, with matching tests.

```
docs/                 MODEL_LOGIC.md (start here) and REFERENCES.md
model/tps_core/       the model, standard library only
  L0_inputs/          config schema, planning rules, deployed tempo
  L1_engine/          the simulation (readable reference + fast engine) and week replay
  L2_metrics/         judging each week and summarizing a run
  L3_levers/          fixes, turn-pattern search, break-even margins, sweeps
  L4_evidence/        run records and backtesting against past weeks
  web_api.py          the bridge the page calls (L5)
tests/                one folder per layer (L0_inputs/ ... L4_evidence/, app/), plus the docs sync test
app/web/              the page (L5): index.html, app.js, styles.css, worker.js
app/brand/            the Decision Models brand kit
examples/plans/       synthetic example plans
examples/history/     a template history file for backtesting
scripts/build_site.py builds site/ for GitHub Pages
.github/workflows/    tests, builds, and deploys on every push to main
```

| Where | What |
| --- | --- |
| `docs/MODEL_LOGIC.md` | **Start here.** Every rule the model applies, in the order a week unfolds: plain words, the math, where it comes from (DAFI 21-101, unit convention, or model choice), and the code and test behind it. A test keeps it in sync with the code. |
| `docs/REFERENCES.md` | Sources for Monte Carlo simulation, the analysis methods, verification and validation, and prior Air Force and commercial aviation simulation work. |
| `examples/` | Synthetic plans and a history template. **Never commit real unit data.** |

## Turn on GitHub Pages (once)

1. Push these files to `main`.
2. In the repo on GitHub: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. Watch **Actions**. When "Test and publish the proof of concept" finishes, the site link appears on the run and under Settings → Pages.

If any test fails, nothing publishes.

## Run it on your own machine

```bash
pytest                            # all tests (configured in pyproject.toml)
python scripts/build_site.py      # builds ./site
python -m http.server -d site 8000
```

Then open http://localhost:8000. It needs internet access the first time to download Pyodide.

## Describing your unit

Each config describes one unit's pattern. The three synthetic examples show a 2-go, 3-go, and 4-go unit.

| Config field | What it sets |
| --- | --- |
| `options.go_profile` | `goes_per_day` (1–4), `sortie_hours`, and `turn_hours`. Launch and landing times follow from these, with the first launch at hour 0. |
| `rates.fix_windows` | Cumulative fix rates as `[{"hours": 4, "rate": 0.45}, ...]`. Any hours, rising. Not fixed within the longest window means down for the week. The older `fix_8hr_rate`/`fix_12hr_rate`/`fix_24hr_rate` fields still work. |
| `rules.first_day_fix_hours` | On the first flying day, fixes longer than this wait for the next day (8 by default). |
| `rules.standard_patterns` | Optional MAJCOM standard turn patterns, like `[[8, 6, 4], [6, 4]]`. When set, plans are checked against them and the sustainable-plan search tries only these. |
| `sute` | Deployed tempo from any figures you have: `possessed_aircraft`, `om_days`, `sorties`, `possessed_aircraft_days`, `sorties_per_om_day`, `avg_sorties_per_aircraft` (or `monthly_sorties_per_aircraft`), or `sute` itself. Any set that pins down the SUTE works; three independent figures recover aircraft, days, and sorties too. `surge_ceiling` is optional. Leave out `required_sorties` to set the weekly requirement from the tempo; `requirement_basis` chooses matching SUTE (`"sute"`, the default) or sorties per aircraft (`"per_aircraft"`). Results show both side by side. |

Day-based patterns only for now: every sortie launches and lands at home the same day. Long sorties that cross midnight or leave the aircraft off-station (mobility, bomber) are a later phase.

## Branding

The page uses the Decision Models brand kit in `app/brand/` (TPS is app 01: teal, "Can the fleet meet the flying schedule?"). `<html data-app="tps">` picks the app; the build copies `app/brand/css`, `icons` and `js` into the site. Dark is the default and light follows the device, with the Auto/Light/Dark switch forcing either. Page colors are aliases for the brand tokens (`app/web/styles.css`, top). Chart marks use the series colors, good and bad meanings use the status colors with a label, and the disclaimer footer appears on every page and printout. To change colors, edit `app/brand/palette.py` and follow `app/brand/README.md`.

## Page layout

Setup sections (weekly plan, how your unit flies, deployed tempo, rates, rules, how the week plays out) are collapsible; each shows a one-line summary when closed, and the weekly plan starts open. After a run, the setup folds into a single line with an **Edit plan** button so the results use the full width.

Deployed tempo takes three inputs: deployed aircraft (PAA), O&M days, and sorties. SUTE, aircraft days, sorties per O&M day, and average sorties per aircraft are calculated and shown. Configs that recorded other figures still load; their worked-out aircraft, days, and sorties appear greyed in the inputs.

## Backtesting against past weeks

The **Check the model against past weeks** section loads a history file (one row per flying day; see `examples/history/history_template.csv` or use **Download the template**). Each week is predicted from its planned schedule and the rates of the weeks before it, then compared with what happened: calibration by prediction band, a Brier accuracy score against always guessing the overall rate, sorties coverage, and day-level agreement. **Try with synthetic history** shows the whole flow on 60 weeks the model generates itself. The file is read in the browser and never uploaded. Rules B-1 to B-4 in `docs/MODEL_LOGIC.md`.

## Three views of the same run

A toggle at the top of the results switches depth without changing the run:

| View | Shows |
| --- | --- |
| Leadership | A decision brief built around their questions: can we do it, what the plan costs (front line vs commit, spares scheduled and flown, 2407 adds, weekend repairs), decisions grouped into maintenance and scheduling levers, how much margin each rate has before the plan drops below the bar, and where to focus. Fixes and margins run automatically. |
| Planner (default) | The schedule shaded by risk (each go's chance of losing a sortie, spares scheduled and used by day), where the plan runs tight, why sorties are lost, watch a week, fixes including moving a sortie, and the turn-pattern search with its efficient frontier. |
| Analyst | Everything in the planner view, plus what moves the answer (break-even margins for each rate), whether the answer has settled (running estimate and a check against five other seeds), inputs and sources, and all the numbers. |

Anyone can switch views at any time, and every view shows the same seed and model version, so a recommendation can always be traced to its evidence. The choice is remembered in the browser.

## Reading the results

| Section | Answers |
| --- | --- |
| Summary (printable on one page) | Will the plan hold up? Weakest day, weekly requirement, next-Monday readiness, and the best fix and sustainable pattern once tested. |
| Where the plan runs tight | Aircraft ready at each day's first go (middle 80% of weeks) against aircraft needed, each day's chance of missing its plan, sorties flown by go with turn success and sortie generation effectiveness, and daily SUTE (planned and flown) against the deployed target and surge ceiling. |
| Why sorties are lost | Each lost sortie traced to one cause: ground aborts used up the spares, no aircraft back in time for a turn, or the day started short. |
| What would fix it | Changes a planner can make, ranked by effect, each with its trade-off. All use the same seed as the run shown, so differences come from the change. |
| Watch a week | Replays any simulated week exactly: a board of what every MC aircraft did all week (zoom to any day), the week step by step, and the chain of events behind a failure. Offers a typical week, a typical failure, the worst week, and a recovery-only failure, or any week number. |
| Test turn patterns | Permutes Monday–Friday weeks in recognizable families (Flat Turns, Waterfall, Step-Down, Front-Loaded Push, Balanced Push, Recovery Valley, Midweek Spike, Multi-Spike, Sawtooth, Step-Up; Reverse Waterfall, Back-Loaded Push, and Compressed Surge are tested but diagnostic only), at the requirement or a band of weekly targets, with go splits stepped down or even. Every week runs on the same seed and the leaders are re-run at full length. The requirement check names the best pattern for the requirement and where it fails, or says none reaches the bar and gives the most the fleet sustains. |

## How results stay trustworthy

- Every run record stores the full config, its fingerprint, the model version, the build commit, and the seed.
- **Verify a run record** re-runs it in the browser and confirms the results are identical, or explains what differs.
- Comparisons derive each variation's seed from one main seed, so the whole comparison re-runs identically.
- `tests/L1_engine/test_engine_equivalence.py` proves the fast engine matches the readable reference exactly.

## Data

The page never sends plans or results to a server; everything runs in the browser, and history is kept in that browser only. The site is public, so the repo holds synthetic examples only. Enter real unit data only where your unit's rules allow it.
