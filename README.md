# Air Force Turn Pattern Sustainability Modeler

This is a first-pass Python version of the turn pattern sustainability model from the spreadsheet layout.

## Model Inputs

- `PAA` / `PAI`: possessed aircraft inputs. The current calculations use `PAI`.
- Historical MC rate: calculates starting `Total MC Aircraft`.
- Historical ground abort rate: calculates total weekly ground aborts from total weekly sorties.
- Historical break rate: calculates total weekly Code 3 events from total weekly sorties.
- Historical 8-hour, 12-hour, and 24-hour fix rates: determine whether each GA/Code 3 event is fixed.
- TTP commit rate: caps daily committed aircraft as a percentage of `PAI`.
- AFI spare rate: calculates spares from first-go aircraft unless a day explicitly provides spares.
- Strict/non-strict GA recovery: strict mode only allows scheduled spares to cover ground aborts. Non-strict mode also allows excess uncommitted MC aircraft to cover ground aborts.
- Daily first/second/third/fourth go schedule.
- Total required sorties. If planned sorties are higher than required sorties, the difference is treated as planned attrition.

## Current Flow

1. Total weekly sorties are calculated from Monday-Friday daily sorties.
2. Planned attrition is calculated as `planned weekly sorties - required weekly sorties`.
3. Total weekly Code 3 events are `round(weekly sorties * historical break rate)`.
4. Total weekly ground aborts are `round(weekly sorties * historical ground abort rate)`.
5. Code 3 and ground abort events are randomly distributed across Monday-Friday.
6. Daily event counts cannot exceed that day's first-go aircraft.
7. Starting MC aircraft are `round(PAI * historical MC rate)`.
8. Daily MC aircraft for flying are the prior day's `Available EOD`.
9. Each GA/Code 3 event gets an 8-hour fix chance.
10. 12-hour and 24-hour fixes do not start until Tuesday. Unfixed Monday events carry into Tuesday for those longer fix attempts.
11. Scheduled spares absorb ground aborts before planned sorties are counted as lost.
12. In strict mode, only scheduled spares cover ground aborts. In non-strict mode, uncommitted MC aircraft can also cover ground aborts. This lets you see both the sustainability view and the scheduling-context view.
13. `Available EOD = MC aircraft for flying - GA - Code 3 + fixed events`.
14. Saturday, Sunday, and next Monday continue the same carry-forward logic with no scheduled flying unless a schedule is provided.
15. A sortie requirement is met when actual attrition stays within planned attrition.

## Success Metrics

The simulator reports:

- Probability of overall success.
- Probability of meeting total required sorties.
- Probability actual attrition stays within planned attrition.
- Probability of having all required aircraft available each flying day.
- Probability of staying within the TTP commit rate.
- Average next-Monday available aircraft.
- Count of the first failure point by day.

Use `compare_turn_patterns()` to pass multiple named `Scenario` objects and receive one summary for each turn pattern.

## Run The Example

```bash
python3 example_run.py
```

The example now runs multiple named turn patterns in two models and prints:

- A strict comparison table where only scheduled spares cover ground aborts.
- A non-strict comparison table where uncommitted MC aircraft can also cover ground aborts.
- A detailed result section and sample Monte Carlo week for each pattern in each model.

Add or edit patterns in `example_run.py` inside the `turn_pattern_inputs` dictionary:

```python
"Pattern Name": {
    "schedule": {
        "Mon": DaySchedule(first_go=4, second_go=1),
        "Tue": DaySchedule(first_go=4, second_go=1),
        "Wed": DaySchedule(first_go=4, second_go=1),
        "Thu": DaySchedule(first_go=4, second_go=1),
        "Fri": DaySchedule(first_go=4, second_go=1),
    },
    "total_required_sorties": 25,
}
```

The example values are based on the visible spreadsheet structure and should be adjusted once the exact workbook formulas are confirmed.

## Generate Analysis Charts

```bash
python3 analysis_report.py
```

This creates `analysis_output/report.html` with:

- Strict vs non-strict success comparison.
- Summary tables for each model.
- Fleet UTE planning sweep from 1 to 15 PAI, showing 0.4 UTE patterns, 0.52 UTE band-ceiling patterns, and max-commit patterns.
- Leadership action summary showing the minimum PAI needed to meet the requirement under strict in-band, non-strict in-band, strict max-commit, and non-strict max-commit assumptions.
- Probability of success for the 0.4 UTE, 0.52 UTE, and max-commit patterns in the fleet sweep.
- Best sustainable strict and non-strict pattern between the 0.4 UTE point and max-commit point for each fleet size.
- UTE planning reference showing where 0.4 UTE lives, the required UTE, planned UTE, and the max-commit reference.
- First-failure-point charts.
- Failure-mode attribution charts for sortie shortfall, aircraft availability, TTP commit, and repair backlog.
- Weekly sorties-flown distributions.
- Next-Monday available-aircraft distributions.
- Average daily sortie-loss charts.
- Sensitivity analysis showing how much success probability changes when each major rate is moved up or down by 10%.

The report intentionally keeps generated pattern strings, first-failure-point charts, full summaries, and detailed distributions in a collapsible diagnostic section because they are usually less useful than the fleet UTE table, named-pattern comparison, failure modes, and sensitivity drivers.

UTE is calculated as `weekly sorties / (PAI * 5 flying days)`. The fleet sweep reports the 0.4 UTE planning point, the 0.52 acceptable UTE ceiling, and the max-commit reference pattern using the 55% commit rule.
