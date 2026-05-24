# Model Logic Reference

This file explains how the Turn Pattern Sustainability Monte Carlo Model works from input
to recommendation. The short version is:

```text
Policy rules -> Capacity sweep -> Pattern generation -> Monte Carlo simulation -> Recommendation screen -> Reports
```

The model is not only asking whether a sortie count is possible. It asks whether
the pattern can make the required sorties, stay inside commit rules, absorb
ground aborts and Code 3s, recover aircraft by next Monday, and avoid creating
unacceptable repair backlog.

## 1. Policy Layer

The policy layer is the rulebook. It lives in `ttp_rules.py`.

It owns:

- commit rate
- UTE planning range
- flying days and recovery days
- spare calculation rule
- allowed GO structure
- max second-go, third-go, and fourth-go limits
- long-fix start day
- recovery model names
- max-commit surge posture
- risk-band thresholds
- human-factor scoring weights

It does not generate events or simulate repairs. It only defines the boundaries
that the generator and simulation engine must respect.

Key examples:

```text
Commit aircraft = floor(PAI x commit rate)
Scheduled spares = ceil(first-go aircraft x spare rate)
```

Commit aircraft and capacity are rounded down because partial aircraft cannot be scheduled. Scheduled spares are rounded up because a partial spare requirement still requires a whole aircraft.

## 2. Capacity Sweep

The capacity sweep answers:

```text
Given this PAI and UTE, how many weekly sorties should be tested?
```

Normal UTE capacity:

```text
weekly_sorties = floor(PAI x flying_days x UTE)
```

Max-commit surge capacity:

```text
commit_aircraft = floor(PAI x commit_rate)
max_commit_weekly_sorties = commit_aircraft x flying_days
max_commit_ute = max_commit_weekly_sorties / (PAI x flying_days)
```

Capacity sweep is math only. It does not prove the pattern is sustainable.

## 3. Pattern Generator

The pattern generator builds Monday-Friday turn patterns that equal the weekly
sortie target.

It now preserves operational families intentionally instead of letting one broad
permutation search dominate the results.

Normal recommendation families:

- Flat Turns
- Waterfall
- Step-Down
- Front-Loaded Push
- Balanced Push
- Recovery Valley
- Midweek Spike
- Multi-Spike
- Sawtooth
- Step-Up

Diagnostic-only families:

- Reverse Waterfall
- Back-Loaded Push
- Compressed Surge

Diagnostic-only families are still simulated, but they are blocked from normal
recommendations. They help explain what the model tested and why certain shapes
may be mathematically possible but operationally undesirable.

Flat turns are strict:

```text
4x2-4x2-4x2-4x2-4x2 = Flat Turns
4x2-3x2-3x2-3x2-3x2 = Waterfall
```

## 4. GO Split Logic

Each daily sortie total is split into allowed GO lines.

Example:

```text
6 daily sorties may be split as:
4x2
5x1
6x0
```

Rules:

- later GOs cannot exceed first-go aircraft
- third go cannot exist without second go
- fourth go cannot exist without third go
- each GO must stay within the sidebar max-go limits
- daily aircraft required must stay within commit cap
- daily sorties must stay within max daily sortie cap

If the sidebar allows only 1st and 2nd go, the generator will not use 3rd or 4th
go patterns.

## 5. Spares

The sidebar controls scheduled spares.

When disabled:

```text
spares = 0
```

When enabled:

```text
spares = ceil(first_go_aircraft x 0.20)
```

Spares count toward aircraft required. They can cover ground aborts before
fleet-flex recovery is used.

Example:

```text
5 first-go aircraft x 20% = 1 spare
4 first-go aircraft x 20% = 1 spare
```

## 6. Monte Carlo Simulation

The simulation engine lives in `simulation.py`.

Each iteration runs a full week:

```text
Mon -> Tue -> Wed -> Thu -> Fri -> Sat -> Sun -> Next Mon
```

Each iteration:

1. Starts with mission-capable aircraft:

   ```text
   starting_MC = floor(PAI x MC_rate)
   ```

2. Generates Code 3 / break events.
3. Generates ground abort events.
4. Distributes events across flying days.
5. Applies scheduled-spare or fleet-flex GA recovery.
6. Calculates sorties flown.
7. Applies 8-hour fixes.
8. Applies 12-hour and 24-hour fixes after the long-fix start day.
9. Carries end-of-day aircraft into the next day.
10. Continues recovery through Saturday, Sunday, and next Monday.
11. Scores the iteration across all success dimensions.

## 7. Event And Fix Modes

Event count model:

- Normal TTP: calculates expected weekly event counts from rates.
- Probabilistic Monte Carlo: rolls event chances across the week.

Fix count model:

- Normal TTP: applies expected repair counts from fix rates.
- Probabilistic Monte Carlo: rolls each repair chance.

Normal TTP is closer to the traditional planning spreadsheet. Probabilistic
Monte Carlo is better for uncertainty and stress testing.

Fix order is sequential:

```text
8-hour fix -> 12-hour fix -> 24-hour fix
```

An event can only be fixed once.

## 8. Recovery Models

The model runs two recovery assumptions:

```text
Scheduled-Spares Only
Fleet-Flex Recovery
```

Scheduled-Spares Only:

- ground aborts can only be covered by scheduled spares
- more conservative

Fleet-Flex Recovery:

- uncommitted MC aircraft can cover a ground abort if available
- shows practical schedule flexibility

## 9. Success Logic

Overall success is stricter than sortie success.

A successful iteration must pass:

- required sortie success
- daily schedule success
- aircraft availability success
- commit compliance
- next-Monday recovery
- backlog success
- event integrity checks
- recommendation shape screen

This means:

```text
Sortie Target Met can be high while Overall Success is lower.
```

That usually means the model can make the sortie number but fails another
operational dimension such as recovery, aircraft availability, or backlog.

## 10. Recommendation Screen

After simulation, the app decides whether a candidate is recommendable.

A recommendable pattern must:

- plan at least the required weekly sorties
- meet the success threshold
- meet the recovery threshold
- meet the backlog threshold
- avoid diagnostic-only family status
- pass operational-shape screening

Non-recommended patterns remain visible in diagnostics so the user can understand
what almost worked and why it was screened out.

## 11. Risk Bands

Risk is based on overall success probability:

```text
Green  = >= 85%
Yellow = 70% to 84.9%
Orange = 55% to 69.9%
Red    = < 55%
```

Green and Yellow are the normal planning range. Orange and Red are warning
states.

## 12. Tabs And Outputs

### Summary

Shows the decision brief by PAI.

Use it to answer:

```text
At this PAI, what pattern should I consider?
```

If no pattern passes, it shows the closest non-recommended pattern. That is not
a recommendation; it is a near-miss for troubleshooting.

### Capacity Sweep

Shows the raw sortie math by PAI and UTE.

Use it to answer:

```text
What weekly sortie range exists inside the selected UTE band?
```

It does not prove sustainability.

### Best Patterns

Shows only recommendable candidates.

Use it to answer:

```text
Which patterns passed the recommendation screen?
```

### Max Surge Weeks

Tests max-commit stress across multiple weeks.

Use it to answer:

```text
How long can max commit remain usable before recovery or backlog breaks down?
```

This is not normal weekly planning.

### Diagnostics

Shows all family-level candidates, including non-recommended patterns.

Use it to answer:

```text
Why did the model reject certain patterns?
```

### Pattern Detail

Shows one selected pattern in more detail.

Use it to inspect:

- component probabilities
- daily sortie pressure
- selected pattern metrics
- recovery-model comparison

### Manual Turn Pattern

Tests a specific user-entered pattern.

Use it to validate known real-world schedules such as:

```text
5x2-4x2-4x2-3x2-2x0
```

### DSUTE Calculator

Calculates sortie-side UTE:

```text
DSUTE = sorties / (possessed_aircraft x O&M_days)
```

It helps translate a known operating tempo into a model UTE range.

## 13. Feature Impact Guide

| Feature | What It Changes | Output Impact |
|---|---|---|
| PAI | Aircraft available to the model | Changes capacity, commit aircraft, MC aircraft, and recovery margin |
| UTE range | Weekly sortie targets tested | Changes which sortie counts and patterns are generated |
| Required sorties | Minimum sortie success threshold | Changes sortie success and overall success |
| Iterations | Number of simulated weeks | Changes confidence/stability, not model assumptions |
| MC rate | Starting MC aircraft | Changes aircraft availability and recovery margin |
| Ground abort rate | GA event count | Changes sortie loss risk and spare/fleet-flex value |
| Break rate | Code 3 event count | Changes backlog, recovery, and next-Monday MC |
| Fix rates | Repair return probability/count | Changes recovery and backlog success |
| Event model | How events are generated | Normal TTP is steadier; probabilistic adds variance |
| Fix model | How repairs are generated | Normal TTP is steadier; probabilistic adds variance |
| Use scheduled spares | Adds 20% first-go spares | Improves GA coverage but increases aircraft required |
| Max daily sorties | Daily pressure cap | Removes unrealistic high-output days |
| # of GOs | Allowed turn depth | Changes possible daily splits |
| Max day-to-day delta | Smoothness constraint | Removes sharp schedule jumps |
| Include max surge | Adds stress case | Useful for surge analysis, not routine planning |

## 14. Important Interpretation Rules

- Capacity does not equal sustainability.
- Meeting required sorties does not equal overall success.
- A closest non-recommended pattern is not a recommendation.
- Diagnostic-only families are useful context, not routine planning outputs.
- Max surge is a stress test, not a normal weekly posture.
- Flat turns require the exact same GO split every flying day.
- Waterfalls can have small step-downs and still be waterfalls.
- Recovery debt is currently an MC recovery gap, not a complete maintenance debt
  measure.
