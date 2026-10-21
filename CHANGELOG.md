# Changelog

All notable changes to Turn Pattern Sustainability. Versions follow semantic versioning; dates are when each version was built.

## [0.13.0] - 2026-10-21
- Private backtest: save your unit's history as `private/history.csv` and run `app/run_private.py`. It backtests every week on your own machine, prints the summary, saves the results week by week, and marks the backtest "Done locally" on the private Method page. Use `--times flown` to time weeks by when they actually flew.
- Synthetic history now works when only some days have fly windows set, and the backtest summary says "All 28 weeks were timed..." instead of "28 of 28 ...; the rest used...".

## [0.12.2] - 2026-10-21
- Fly-window boxes take a typed time or one picked from a list. A day left blank runs on the day before's window, shown in grey, so a plan with some days set always runs.
- Simulation results are unchanged.

## [0.12.1] - 2026-10-21
- Clock times use military time everywhere: fly windows are typed as 0700 and 2200, and warnings, the play-by-play, and history files show times the same way. Times with a colon, like 07:00, are still read.
- Simulation results are unchanged.

## [0.12.0] - 2026-10-21
- Fly windows: set each flying day's first launch and last land, for example 0700 to 2200, with a shorter Friday. A day that opens later gives overnight fixes more time before its first launch, and one that opens earlier gives them less.
- A go that lands after its day's window closes gets a warning. The plan still runs as entered.
- Windows can run past midnight, for example 1400 to 0200. Those sorties count to the day they launch on. Aircraft that land after midnight have less time for fixes before the next day's first launch, and an aircraft still flying can't make that launch.
- With fly windows set, the play-by-play shows clock times.
- Backtesting can time each past week by its own first launch and last land: history files take optional planned and flown time columns, and you choose which set to use. Planned times test the plan; flown times test the model. Files without them work as before.
- Plans without fly windows give the same results as before.

## [0.11.1] - 2026-10-16
- Clearer wording on every page and in the results summary: it now leads with how often the plan holds and why it fails.
- The pattern search labels its screening figures as estimates, so they aren't confused with the headline result.
- Simulation results are unchanged. The summary text is part of each run record, so records made with 0.11.0 re-verify as an earlier model version.

## [0.11.0] - 2026-10-04
- The public Results page now shows the same Leadership, Planner and Analyst views as the planner, for every synthetic unit and scenario.
- Seasonality: monthly rates, repair speed, holiday weeks and surges, shown as a month-by-month strip. Monthly rates can come from a history file in the planner.
- The availability chart shows median aircraft, the 10–90% range and a dashed requirement line.

## [0.10.0] - 2026-10-04
- New Overview, Results and Method pages, with the full planner behind Run ▸.
- Precomputed results for each synthetic unit (baseline, surge, short-staffed recovery) under scheduled spares and fleet flex.
- Code restructured with reference outputs captured first and checked on every deploy; simulation results unchanged.
- Saving runs in the browser is now opt-in, with one button to clear everything the site stores.
- Two guided tours: one walks through the results, the other edits and runs a plan using the engine's real numbers.

## [0.9.0] - 2026-10-03
- Backtesting: check the model's predictions against past weeks, in the browser.
- Decision Models brand applied; code reorganized into layers, from inputs to evidence.

## [0.8.0] - 2026-10-02
- Separate views for leadership, planners and analysts, plus how far each rate can slip before the plan fails.
- Efficient frontier of turn patterns, and checks that results are stable across run lengths and seeds.

## [0.7.0] - 2026-10-01
- Deployed tempo worked out from aircraft, O&M days and sorties; plan setup folds away after a run.

## [0.6.0] - 2026-10-01
- Deployed tempo from any combination of report figures; the home requirement can match SUTE or sorties per aircraft.

## [0.5.0] - 2026-09-30
- Replay any simulated week exactly: what each aircraft did, in order, and why the week failed.

## [0.4.0] - 2026-09-30
- Turn-pattern search across standard week shapes, checked against the weekly requirement.

## [0.3.0] - 2026-09-30
- Units flying 1 to 4 goes a day, configurable fix windows, SUTE, and results by go.

## [0.2.0] - 2026-09-30
- Causes of lost sorties, a fleet margin chart, fixes ranked by effect, and a leadership summary.

## [0.1.0] - 2026-09-30
- First release: the engine runs in the browser, and every run produces a record anyone can verify.
