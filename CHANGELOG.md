# Changelog

All notable changes to Turn Pattern Sustainability. Versions follow semantic versioning; dates are when each version was built.

## [0.10.0] - 2026-10-04
- Aligned with the Decision Models kit: `src/tps/` package, root `brand/`, public and private front doors, Overview · Results · Method pages with the full planner behind Run ▸.
- Results page shows precomputed presets for each synthetic unit (baseline, surge, short-staffed recovery) under scheduled spares and fleet flex.
- Golden outputs captured before the move and checked on every deploy; simulation results unchanged.
- Saving runs in the browser is now opt-in, with one button to clear everything the site stores.
- Two guided tours from the "Take the tour" strip: the results tour switches presets and the planner tour edits and runs the plan, each showing what changes what with the engine's real numbers.

## [0.9.0] - 2026-10-03
- Backtesting against past weeks in the browser: calibration by band, Brier skill, sorties coverage, day-level agreement.
- Decision Models brand kit applied; repo reorganized into layers L0 to L4.

## [0.8.0] - 2026-10-02
- Role views built around each audience's questions; break-even margins; efficient frontier; convergence and replication checks.

## [0.7.0] - 2026-10-01
- Deployed tempo from aircraft, O&M days and sorties; collapsible setup that folds away after a run.

## [0.6.0] - 2026-10-01
- Deployed tempo from any combination of report figures; home requirement matched by SUTE or by sorties per aircraft.

## [0.5.0] - 2026-09-30
- Watch a week: exact replay of any simulated week, with a tail board, the story, and why it failed.

## [0.4.0] - 2026-09-30
- Turn-pattern search across recognizable families, with a requirement check.

## [0.3.0] - 2026-09-30
- Multi-go units (1 to 4 goes), configurable fix windows, SUTE, results by go.

## [0.2.0] - 2026-09-30
- Root causes of lost sorties, fleet margin chart, fixes ranked by impact, leadership summary.

## [0.1.0] - 2026-09-30
- Go-level engine run in the browser with Pyodide; run records anyone can verify.
