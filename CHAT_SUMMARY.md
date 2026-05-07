# Turn Pattern Sustainability Modeler Context

## Project Goal

Build a Python-based Air Force turn-pattern sustainability modeler that can compare multiple weekly turn patterns and help determine whether each pattern is sustainable under maintenance, attrition, commit-rate, and UTE constraints.

The tool is intended to support leadership-ready decisions: which patterns work, why others fail, how much sortie production is realistic for a given fleet size, and where risk comes from.

## Core Model Inputs

- PAA / PAI: possessed/primary assigned aircraft available to the unit.
- Historical MC rate: used to estimate total mission-capable aircraft.
- Historical ground abort rate: used to estimate weekly ground aborts from planned sorties.
- Historical break rate: used to estimate weekly Code 3 breaks from planned sorties.
- Historical 8-hour, 12-hour, and 24-hour fix rates: used to determine repair recovery timing.
- TTP commit rate: default 55%, limiting how much of the fleet should be committed to the schedule.
- AFI spare percentage: optional spares applied to the schedule when desired.
- Weekly turn pattern: daily go counts, spares, and resulting sortie production.
- Weekly required sorties: may be lower than planned sorties to account for planned attrition.
- UTE constraints: target UTE around 0.40, acceptable planning band up to 0.52, and max UTE at the 55% commit limit.

## Model Behavior

- The first go plus spares determines aircraft committed to the daily schedule.
- Daily sorties are calculated from all scheduled gos.
- Weekly Code 3s and ground aborts are estimated from total weekly sorties, then randomly distributed across the flying week in Monte Carlo iterations.
- Ground aborts and breaks cannot exceed realistic daily exposure from scheduled frontline aircraft.
- Fixes are applied sequentially using 8-hour, 12-hour, and 24-hour fix probabilities.
- 12-hour and 24-hour fixes only begin on Tuesday. Monday events that are not fixed in 8 hours carry into Tuesday repair logic.
- End-of-day available aircraft becomes the next day’s starting MC aircraft.
- Saturday and Sunday are used for continued repair/recovery, not normal weekday sortie generation.
- The following Monday reflects the remaining aircraft available after weekend recovery.

## Strict And Non-Strict Models

The model reports two interpretations:

- Strict: only scheduled spares can cover ground aborts or aircraft losses during execution. This shows whether the published schedule is sustainable without pulling additional aircraft into the line.
- Non-strict: available uncommitted MC aircraft can fill gaps if enough aircraft exist. This provides operational nuance, but needing this repeatedly may indicate the pattern is not truly sustainable as scheduled.

## Success Logic

The model accounts for planned attrition:

- Planned attrition = planned weekly sorties - required weekly sorties.
- A pattern can still succeed if actual lost sorties remain within the planned attrition allowance.
- Success probability is estimated over many Monte Carlo iterations.

The report also tracks likely failure drivers:

- Sortie shortfall.
- Aircraft availability shortfall.
- TTP commit-rate exceedance.
- Repair backlog.

## Reporting Goals

The report should be readable for leadership and planners:

- Start with an executive recommendation.
- Show UTE planning reference points.
- Provide a fleet sweep from 1 to 15 aircraft.
- Identify best feasible sortie production and turn patterns within the 0.40 to 0.52 UTE band and up to the 55% commit cap.
- Compare named turn patterns.
- Explain why patterns fail.
- Include sensitivity analysis so users understand which assumptions drive outcomes.
- Keep detailed generated patterns in diagnostics rather than making them the main story.

## Current Files

- `turn_pattern_modeler.py`: core simulation model and supporting analysis logic.
- `example_run.py`: example run comparing named turn patterns.
- `analysis_report.py`: generates a leadership-style HTML report.
- `README.md`: project usage notes.
- `analysis_output/report.html`: generated sample report.

## Suggested Next Enhancements

- Add a simple input file format for user-defined fleets and patterns.
- Add export to Excel or PDF for easier briefing.
- Add confidence intervals around success probabilities.
- Add scenario comparison presets for optimistic, expected, and conservative maintenance assumptions.
- Add clearer leadership language around strict vs non-strict results.
