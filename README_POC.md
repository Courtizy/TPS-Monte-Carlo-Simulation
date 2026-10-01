# TPS proof of concept

The Turn Pattern Sustainability model running entirely in the browser, published with GitHub Pages.
The `tps_core` package here is the same model the hosted team app will run later.

## What's in it

| Path | What it is |
| --- | --- |
| `MODEL_LOGIC.md` | **Start here.** Every rule the model applies, in the order a week unfolds: plain words, the math, where it comes from (DAFI 21-101, unit convention, or model choice), and the code and test behind it. |
| `tps_core/` | The model package: schemas, rules, go-level engine (fast + readable reference), metrics, run records, sweeps. Standard library only. |
| `tests_core/` | Tests that must pass before the site publishes. |
| `web/` | The page: plan form, results, week board, variation comparison, run history. |
| `examples/` | Synthetic example configs. **Never commit real unit data.** |
| `scripts/build_site.py` | Builds `site/`: zips the model with the version and commit stamped in. |
| `.github/workflows/pages.yml` | Tests, builds, and publishes to GitHub Pages on every push to `main`. |

## Turn on GitHub Pages (once)

1. Push these files to `main`.
2. In the repo on GitHub: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. Watch **Actions**. When "Test and publish the proof of concept" finishes, the site link appears on the run and under Settings → Pages.

If any test fails, nothing publishes.

## Run it on your own machine

```bash
pytest tests_core                 # model tests
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
| `sute` | `monthly_sorties_per_aircraft` and `om_days` set the deployed daily SUTE; `surge_ceiling` is optional. Leave out `required_sorties` to work the weekly requirement out as SUTE × PAI × flying days. |

Day-based patterns only for now: every sortie launches and lands at home the same day. Long sorties that cross midnight or leave the aircraft off-station (mobility, bomber) are a later phase.

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
- `tests_core/test_engine_equivalence.py` proves the fast engine matches the readable reference exactly.

## Data

The page never sends plans or results to a server; everything runs in the browser, and history is kept in that browser only. The site is public, so the repo holds synthetic examples only. Enter real unit data only where your unit's rules allow it.
