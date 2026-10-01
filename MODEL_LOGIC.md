# TPS Model Logic

**Turn Pattern Sustainability, model `tps_core` 0.7**

TPS answers one planning question: **can this unit fly this weekly schedule, week after week, without running out of aircraft?** It plays the week out thousands of times. Each time, breaks, aborts, and fixes land differently, and the model counts how often the plan holds up and why it fails when it doesn't.

This document walks through every rule the model applies, in the order a week unfolds.

## How to read this document

Each rule has an ID, like **F-3**. The same ID appears as a comment in the code (`[F-3]`) and in the test that proves the rule works. `tests_core/test_model_logic.py` fails if any rule here is missing from the code or the tests, so this document can't quietly drift out of date.

Every rule is tagged with where it comes from:

| Tag | Meaning |
| --- | --- |
| **DAFI 21-101** | Grounded in a paragraph of DAFI 21-101 (with Change 1), checked against the public text. |
| **Unit convention** | A planning practice confirmed by the model owner. Different units may set it differently, so it is an input wherever possible. |
| **Model choice** | A design decision needed to turn planning practice into a simulation. Explained so it can be challenged. |

Sources for the method itself (Monte Carlo simulation, the confidence interval, sensitivity analysis, verification and validation, and prior Air Force and aviation simulation work) are in `REFERENCES.md`. No rule comes from restricted publications. Planning values (rates, commit, spares) are inputs from each unit, never built into the code.

**Read the code in this order:** `rules.py` (planning arithmetic), `schemas.py` (inputs), `reference.py` (the simulation, written to be read line by line), `metrics.py` (judging a week), `patterns.py` and `levers.py` (search and fixes). `engine.py` is an optimized copy of `reference.py`; a test proves they give identical results, so you never need to read it to understand the model.

---

## The week at a glance

```
 Day:     Mon        Tue        Wed        Thu        Fri        Sat      Sun      Next Mon
         |-flying--|-flying--|-flying--|-flying--|-flying--|-repair-|-repair-|-check-|
 Hours:   0         24        48        72        96       120      144      168

 One flying day (2-go example: 2-hour sorties, 8-hour turn window):
   hour 0 ── Go 1 launch                           hour 10 ── Go 2 launch
   hour 2 ── Go 1 lands ── breaks start fix clock  hour 12 ── Go 2 lands
              └── an 8-hour fix finishes at hour 10: makes Go 2
              └── a 12-hour fix finishes at hour 14: misses Go 2, flies tomorrow
```

Hour 0 of every day is that day's first launch. Weekends only fix aircraft. "Next Mon" is the recovery check: are enough aircraft ready to start the next week?

---

## 1. Glossary

| Planner term | Meaning in the model | Name in code |
| --- | --- | --- |
| PAI | Aircraft assigned to the unit | `inventory.pai` |
| MC rate | Share of PAI mission capable at the start of the week | `rates.mc_rate` |
| Go | A launch wave; up to 4 per day | `first_go` … `fourth_go`, `go_profile` |
| Turn | Flying an aircraft again on a later go the same day | goes after the first |
| Code 3 / break | Aircraft lands needing a fix before it can fly | `code_3`, `break_rate` |
| Ground abort (GA) | Aircraft fails to launch | `ground_abort`, `ground_abort_rate` |
| Fix rate | Share of breaks and aborts fixed within a time window | `rates.fix_windows` |
| Commit | Most aircraft planned on the front line in a day | `commit_rate`, `commit_aircraft()` |
| Spare | Aircraft prepared to replace a primary that breaks or aborts | `spare_rate`, `spares` |
| Front line | First go plus spares | `aircraft_required` |
| 2407 add | Unplanned aircraft added to cover a loss | `allow_2407_adds`, `adds_2407` |
| Repeat / recur | A fixed aircraft breaks again for the same issue | `repeat_rate`, `recur_rate` |
| SUTE | Daily sortie utilization rate per PAI | `sute` block, `metrics.sute` |
| Recovery | Enough aircraft ready to start next week | `recovery_target` |

---

## 2. Fleet and front line

### R-1: Aircraft available at the start of the week
**Source:** Unit convention.
**Rule:** The week starts with the mission-capable share of PAI, rounded down. Aircraft not MC at the start stay down all week.

$$MC_0 = \lfloor PAI \times MC \rfloor$$

**Code:** `reference.py` → `run_week` (`start_mc`).
**Test:** `test_short_fleet_is_blamed_on_the_first_go`.

### R-2: Committed aircraft
**Source:** Unit convention (commit rate is unit-set; around 55% at the owner's unit). DAFI 21-101 ¶1.3.3 directs MAJCOMs to set utilization standards for combat-coded fighters by MDS and PAA.
**Rule:** Commit is rounded down, because a partial aircraft can't be scheduled.

$$C = \lfloor PAI \times commit\_rate \rfloor$$

**Code:** `rules.py` → `commit_aircraft`.
**Test:** `test_commit_spares_and_front_line_math`.

### R-3: Scheduled spares
**Source:** Unit convention (often 20% of the first go).
**Rule:** Spares are rounded up, because a partial spare still needs a whole aircraft. A planner can override the number on any day.

$$spares_d = \lceil first\_go_d \times spare\_rate \rceil \quad \text{(unless overridden)}$$

**Code:** `rules.py` → `calculated_spares`, `day_spares`.
**Test:** `test_commit_spares_and_front_line_math`.

### R-4: Front line and commit
**Source:** Unit convention: commit is a planning target that should not be ignored; spares count against it because they take maintenance prep.
**Rule:** Each day's front line is first go plus spares. A day planned above commit runs, but fails the week's "plan within commit" check (M-1) and shows a warning.

$$need_d = first\_go_d + spares_d, \qquad \text{within commit if } need_d \le C$$

**Code:** `rules.py` → `aircraft_required`; `schemas.py` → `plan_warnings`.
**Test:** `test_plan_warnings_flag_rule_breaks`.

### R-5: Goes and turns
**Source:** Unit convention.
**Rule:** Later goes fly aircraft from earlier goes that day, so no go can be larger than the one before it, and a day can't plan more goes than the unit flies.

$$go_{k+1} \le go_k, \qquad \text{goes used} \le \text{goes per day}$$

**Code:** `schemas.py` → `validate_config`.
**Test:** `test_validation_catches_problems`.

---

## 3. Timeline

### T-1: Model hours
**Source:** Model choice.
**Rule:** Day *i* of the week spans hours `24i` to `24i + 24`. Hour 0 of each day is its first launch.
**Code:** `reference.py` → `run_week`.
**Test:** `test_return_timing_table`.

### T-2: Go profile
**Source:** Unit convention; DAFI 21-101 ¶1.3.3 directs MAJCOM standards to account for standard turn patterns, turn-time inspections, and average sortie duration.
**Rule:** Each unit sets goes per day, sortie length, and turn window. Launch and landing times follow, and the last go must land within the day.

$$launch_1 = 0,\quad land_k = launch_k + sortie,\quad launch_{k+1} = land_k + turn$$

**Code:** `schemas.py` → `profile_go_times`.
**Test:** `test_profile_go_times`.

### T-3: Ready to fly
**Source:** Model choice.
**Rule:** An aircraft can fly a go if its fix (if any) finishes at or before that go's launch.

$$\text{flies go } k \iff ready \le launch_k$$

**Code:** `reference.py` → `run_week` (`ready`).
**Test:** `test_a_4_hour_fix_misses_a_3_hour_turn_but_makes_the_third_go`.

---

## 4. Breaks and aborts

### E-1: Rates apply to the week's sorties
**Source:** Unit convention.
**Rule:** Break and abort rates are monthly averages applied to all the week's planned sorties, turns included. A 25% break rate on 26 sorties plans for 7 breaks that week.
**Code:** `reference.py` → `run_week` (`slots`).
**Test:** `test_fixed_count_places_exact_breaks`.

### E-2: Where breaks land
**Source:** Unit convention (the owner wanted all three to compare hand-placed and random approaches).
**Rule:** There are three modes. With *S* planned sorties and rate *r*:
- **Spreadsheet:** exactly $N = \lceil S r \rceil$ events, spaced evenly through the week: sortie $\lfloor (j + o) S / N \rfloor$ for $j = 0 \dots N-1$, with $o = 0.5$ for breaks and $0.75$ for aborts.
- **Set count, random sorties:** exactly *N* events, on sorties chosen at random.
- **Fully random:** each sortie has chance *r*, so some weeks see more and some fewer.

**Code:** `reference.py` → `_place_events`.
**Test:** `test_fixed_count_places_exact_breaks`, `test_fully_random_breaks_match_the_rate`.

### E-3: Ground abort
**Source:** Unit convention.
**Rule:** The aborting aircraft goes to fix, with its clock starting at launch. The next aircraft in the fill order (S-1) launches in its place; if there is none, the sortie is lost.
**Code:** `reference.py` → `run_week` (`abort_slots`).
**Test:** `test_a_spare_replaces_an_abort`.

### E-4: Break (Code 3)
**Source:** Unit convention.
**Rule:** The sortie counts as flown. The aircraft goes to fix, with its clock starting at landing.
**Code:** `reference.py` → `run_week` (`break_slots`).
**Test:** `test_break_costs_the_turn_and_8hr_fix_saves_it`.

### E-5: No aircraft, no event
**Source:** Model choice.
**Rule:** A break or abort planned for a sortie that is lost (no aircraft to fly it) does not happen.
**Code:** `reference.py` → `run_week`.
**Test:** `test_events_on_lost_sorties_do_not_happen`.

---

## 5. Filling each sortie

### S-1: Fill order
**Source:** Unit convention; the order is a model choice.
**Rule:** Each sortie takes the first ready aircraft from:
1. aircraft planned for this go (first go: the day's lineup; later goes: aircraft that already flew today);
2. other front-line aircraft (unused lineup aircraft, then spares);
3. 2407 adds, if allowed (S-3).

**Code:** `reference.py` → `run_week` (`queue`, `take`).
**Test:** `test_a_spare_replaces_an_abort`.

### S-2: Which goes spares can cover
**Source:** Unit convention.
**Rule:** Spares cover any go by default. A unit can limit them to certain goes, for example the first go only.
**Code:** `reference.py` → `run_week` (`spare_ok`).
**Test:** `test_spares_limited_to_the_first_go`.

### S-3: 2407 adds
**Source:** Unit convention: adds are done the day of, counted against commit afterward, with no fixed cap.
**Rule:** When allowed, any ready MC aircraft not on the front line can cover a loss. It then flies like any other aircraft, can break, and drains the pool for later days. Adds don't fail the plan's commit check (R-4). Days when actual front-line use exceeded commit are reported separately.
**Code:** `reference.py` → `run_week` (`added`).
**Test:** `test_2407_adds_cover_losses_and_count_against_commit`.

---

## 6. Fixes

### F-1: Fix windows
**Source:** Unit convention: cumulative fix rates from monthly averages, any windows the unit tracks (for example 8/12/24 hours, or 2/4/8/12/24).
**Rule:** Each break or abort draws a number *u* between 0 and 1 and is fixed within the first window whose cumulative rate exceeds it. Anything past the longest window stays down for the rest of the week. Rates are treated as never falling from one window to the next.

$$\text{fixed within } h_i, \quad i = \min\{\, i : u < F_i \,\}; \qquad u \ge F_{last} \Rightarrow \text{down for the week}$$

**Code:** `reference.py` → `send_to_fix`; `schemas.py` → `_windows`.
**Test:** `test_a_2_hour_fix_makes_a_3_hour_turn`.

### F-2: When the fix clock starts
**Source:** Unit convention.
**Rule:** For a break, the clock starts at landing. For an abort, it starts at launch.
**Code:** `reference.py` → `send_to_fix` (`event_time`).
**Test:** `test_return_timing_table`.

### F-3: First flying day rule
**Source:** Unit convention: the first flying day runs into the afternoon, leaving only the overnight window, so longer fixes wait. DAFI 21-101 Table 1.2 gives primary mission aircraft repair priority for the first 8 work hours after landing.
**Rule:** On days before `long_fix_start_day` (Tuesday by default), fixes longer than `first_day_fix_hours` (8 by default) start their clock at the next allowed day's first launch. A Monday break needing 12 hours is ready Wednesday morning.
**Code:** `rules.py` → `can_use_long_fix`; `reference.py` → `send_to_fix`.
**Test:** `test_first_day_long_fix_ready_wednesday`, `test_first_day_threshold_is_configurable`.

### F-4: Weekday and weekend fix clocks
**Source:** Unit convention: weekend duty is a yes/no decision, and fix rates continue when it's worked. DAFI 21-101 ¶1.14 limits continuous duty to 12 hours (extendable to 16 with squadron commander approval) and requires 8 hours of rest, which is why weekend options are framed as shifts.
**Rule:** On weekdays the clock runs all 24 hours, because the fix rates already reflect normal weekday manning. On Saturday and Sunday it runs only during the covered hours (0, 8, 12, 16, or 24), starting at the day's hour 0, and pauses otherwise. "Around the clock" implies more than one crew.
**Code:** `reference.py` → `coverage_by_day`, `ready_time`.
**Test:** `test_weekend_clock`.

### F-5: Expected fix outcomes
**Source:** Model choice.
**Rule:** "Match the rates exactly" mode replaces random draws with an evenly spread fixed sequence, so the week's mix of fix times matches the rates without luck.

$$u_k = (o + k\varphi) \bmod 1, \qquad \varphi = 0.618\ldots,\quad o = 0 \text{ (fixes)},\; 0.5 \text{ (repeat/recur)}$$

**Code:** `reference.py` → `_Draws`.
**Test:** `test_expected_draws_match_the_rates`.

### F-6: Repeat and recur
**Source:** Unit convention: repeat and recur are monthly average rates, separate from the break rate. DAFI 21-101 ¶2.4.3.15 requires procedures to review repeat, recur, and cannot-duplicate discrepancies.
**Rule:** When a fix finishes, the aircraft has a `repeat_rate` chance of breaking again on its first sortie within 24 hours, or a `recur_rate` chance within 72 hours. These breaks come on top of the break rate.
**Code:** `reference.py` → `send_to_fix` (`latent_start`).
**Test:** `test_repeat_rebreaks_a_fixed_aircraft`.

---

## 7. Judging a week

### M-1: What counts as success
**Source:** Unit convention.
**Rule:** A simulated week succeeds only if **all** of these hold:
1. sorties flown meet the weekly requirement;
2. every flying day flies all its planned sorties;
3. every flying day starts with enough ready aircraft for its front line;
4. every day's plan is within commit (R-4);
5. recovery passes (M-2);
6. backlog is within its limit, if a limit is set (M-3).

**Code:** `metrics.py` → `score_week`.
**Test:** `test_backlog_is_reported_not_pass_fail_by_default`.

### M-2: Recovery
**Source:** Unit convention: the target is all of Monday's flyers, meaning the most committable aircraft (first go plus spares) any day needs.
**Rule:** Recovery passes if aircraft ready at next Monday's first launch meet the target. A unit can set a fixed minimum instead.

$$T = \max_d \, need_d, \qquad \text{recovered if } ready_{\text{Next Mon, hour } 0} \ge T$$

**Code:** `metrics.py` → `score_week`.
**Test:** `test_margin_fields_are_ordered_and_sensible`.

### M-3: Repair backlog
**Source:** Unit convention (reported, not pass/fail, unless the unit sets a limit).
**Rule:** Backlog is the aircraft still down at next Monday: $MC_0 - ready_{\text{Next Mon}}$.
**Code:** `reference.py` → `run_week` (`repair_backlog`); `metrics.py` → `score_week`.
**Test:** `test_backlog_is_reported_not_pass_fail_by_default`.

### M-4: How sure the answer is
**Source:** Model choice.
**Rule:** The success rate carries a 95% Wilson interval, which stays sensible near 0% and 100%. With *w* successes in *n* weeks, $\hat p = w/n$ and $z = 1.96$:

$$\frac{\hat p + \frac{z^2}{2n} \pm z\sqrt{\frac{\hat p(1-\hat p)}{n} + \frac{z^2}{4n^2}}}{1 + \frac{z^2}{n}}$$

**Code:** `metrics.py` → `wilson_interval`.
**Test:** `test_wilson_interval`.

### M-5: Why sorties are lost
**Source:** Model choice.
**Rule:** Every lost sortie is blamed on exactly one cause:
- **Day started short:** a first-go sortie with no aircraft, on a day that began with fewer ready aircraft than the first go.
- **Aborts used up the spares:** an abort with no replacement, or a first-go sortie lost after earlier aborts took the spares.
- **No aircraft back for a turn:** a later-go sortie with no aircraft back in time.

**Code:** `reference.py` → `run_week` (`lost_first_go_short`, `lost_abort_uncovered`, `lost_turn_short`); `metrics.py` → `_causes`.
**Test:** `test_causes_always_add_up_to_lost_sorties`.

### M-6: Results by go
**Source:** Model choice, using standard measures.
**Rule:**

$$SGE = \frac{\text{sorties flown}}{\text{sorties scheduled}}, \qquad TSR = \frac{\text{flown on goes } 2\text{–}4}{\text{scheduled on goes } 2\text{–}4}$$

The go with the lowest share flown is reported as the weakest go.
**Code:** `metrics.py` → `_by_go`.
**Test:** `test_per_go_counts_and_turn_success`.

### M-7: Training tempo (SUTE)
**Source:** Unit convention: train like you fight, flying at or slightly above the deployed tempo at home, measured per PAI; show the match by SUTE and by sorties per aircraft side by side. Command supplements define UTE as average sorties per PAI.
**Rule:** The deployed SUTE comes from whatever figures are given (M-9). At home:

$$SUTE_{home} = \frac{\text{weekly sorties}}{PAI \times \text{flying days}}, \qquad \text{per aircraft}_{home} = \frac{\text{weekly sorties}}{PAI}$$

Deployed operations run every O&M day, so deployed sorties per aircraft per week is $SUTE_{deployed} \times 7$. Two weekly requirements follow:

$$\text{match SUTE} = \lceil SUTE_{deployed} \times PAI \times \text{flying days} \rceil, \qquad \text{match per aircraft} = \lceil SUTE_{deployed} \times 7 \times PAI \rceil$$

If the requirement isn't entered, the chosen basis (SUTE by default) sets it. Results show deployed, planned, and flown values side by side for both measures, and how often each is met. A surge ceiling is an optional input; plans above it get a warning.
**Code:** `schemas.py` → `deployed_sute`, `required_from_sute`; `tempo.py` → `home_requirements`; `metrics.py` → `_sute`.
**Test:** `test_sute_math_and_derived_requirement`, `test_both_home_requirements`.

### M-8: Risk labels
**Source:** Unit convention (risk bands carried over from the original TPS) and model choice (day-risk shading).
**Rule:** Overall success is labeled Green (85% or more), Yellow (70% or more), Orange (55% or more), or Red. The day-risk strip shades each day by its chance of missing its plan: under 2% low, 2–10% watch, 10% or more high. The weakest day is the flying day most likely to miss its plan.
**Code:** `rules.py` → `risk_band`; `metrics.py` → `_weakest_day`.
**Test:** `test_risk_bands`.

### M-9: Deployed tempo from aircraft, O&M days, and sorties
**Source:** Unit convention: deployed aircraft (PAA), O&M days, and sorties are the easiest figures to gather; the rest are calculated from them.
**Rule:** The form asks for deployed aircraft *A* (the PAA that deployed), O&M days *D*, and sorties *S*, and shows the calculated figures: SUTE $= S / (A \times D)$, aircraft days $= A \times D$, sorties per O&M day $= S / D$, and avg sorties per aircraft $= S / A$. For example, 11 aircraft, 7 days, and 31 sorties give 77 aircraft days, 4.4 sorties per day, 2.8 per aircraft, and SUTE 0.40.

Configs that recorded other figures still work. Each figure ties together *A*, *D*, and *S*, and in logs each becomes a straight line:

| Figure | Means | In logs |
| --- | --- | --- |
| Possessed aircraft | *A* | *a* |
| O&M days | *D* | *d* |
| Sorties | *S* | *s* |
| Possessed aircraft days | *A × D* | *a + d* |
| Sorties per O&M day | *S / D* | *s − d* |
| Avg sorties per aircraft | *S / A* | *s − a* |
| SUTE | *S / (A × D)* | *s − a − d* |

Any figures whose lines combine to *s − a − d* give the SUTE; three independent figures also recover *A*, *D*, and *S*. Rounded report figures that disagree are fit by least squares and the largest disagreement is shown. Figures that can't pin down a SUTE are rejected with a note saying what to add. The older "sorties per aircraft per month" input is the same as avg sorties per aircraft.
**Code:** `tempo.py` → `solve_tempo`; `schemas.py` → `_validate_sute`.
**Test:** `test_tempo_from_any_figures`.

---

## 8. Fixes and the pattern search

### L-1: Testing fixes
**Source:** Model choice. DAFI 21-101 ¶1.3.3 calls for helping units assess shortfalls and build action plans.
**Rule:** From a finished run, the model builds changes a planner could make: one more spare on the weakest day, one fewer sortie on its last go, one more spare every day, allowing 2407 adds, and more weekend repair hours. Each change runs on **the same seed** as the original, so differences come from the change, not luck. Each lists its trade-off, including when a change raises next Monday's recovery target.
**Code:** `levers.py` → `build_levers`.
**Test:** `test_levers_are_valid_configs_with_costs`.

### P-1: Weekly targets to test
**Source:** Unit convention: focus permutations on the tempos that matter.
**Rule:** Test the requirement alone, a band of about five targets from 75% of the requirement up to the surge ceiling (or 1.5× the larger of the requirement and the current plan), or the planner's own list.
**Code:** `patterns.py` → `week_targets`.
**Test:** `test_targets_band_includes_requirement_and_stays_sane`.

### P-2: Week permutations
**Source:** Unit convention (from the original TPS generator).
**Rule:** For each target, list every Monday–Friday split of the weekly total with at least 1 sortie a day, no day above the daily cap (the most a day can hold under commit, spares, and per-go limits), and no day-to-day change above the limit. When there are more than 20,000 weeks, draw a sample of 4,000 evenly instead.
**Code:** `patterns.py` → `daily_compositions`, `daily_cap`.
**Test:** `test_compositions_respect_total_cap_and_day_to_day_limit`.

### P-3: Pattern families
**Source:** Unit convention (families from the original TPS, in its order of checks).
**Rule:** Each week's daily totals are named by the first rule that fits:

| Family | Rule | Recommended? |
| --- | --- | --- |
| Flat Turns | Every day the same | Yes |
| Compressed Surge | The 3 busiest days hold 75% or more of the week | Diagnostic only |
| Step-Down | Never rises, holds a level, at least 3 levels | Yes |
| Waterfall | Never rises | Yes |
| Step-Up | Never falls, holds a level, at least 3 levels | Yes |
| Reverse Waterfall | Never falls | Diagnostic only |
| Sawtooth | Alternates up and down at least 3 times | Yes |
| Recovery Valley | A mid-week day at least 2 below both neighbors | Yes |
| Midweek Spike | Peak on Wednesday or Thursday | Yes |
| Multi-Spike | Two or more days at least 1 above average | Yes |
| Front-Loaded Push | Mon + Tue more than 2 above Thu + Fri | Yes |
| Back-Loaded Push | Thu + Fri more than 2 above Mon + Tue | Diagnostic only |
| Balanced Push | Anything else | Yes |

Diagnostic-only families are simulated and shown, but never recommended.
**Code:** `patterns.py` → `classify`.
**Test:** `test_classify`.

### P-4: Splitting a day into goes
**Source:** Model choice.
**Rule:** A day's total is split into goes either **evenly** (12 over 3 goes is 4x4x4) or **stepped down** (weights 2:1, 3:2:1, or 4:3:2:1, so 12 over 3 goes is 6x4x2). A split must fit commit with spares and any per-go limits; if one style doesn't fit, the other is tried.
**Code:** `patterns.py` → `split_day`, `_day_fits`.
**Test:** `test_split_day`.

### P-5: Judging each tested week
**Source:** Model choice.
**Rule:** Each tested week is judged on flying **its own** weekly total, so the search can find the most the fleet sustains even below the requirement. The verdict then compares that against the real requirement.
**Code:** `patterns.py` → `_candidate`.
**Test:** `test_generated_weeks_fit_the_rules_and_cover_families`.

### P-6: Screen, confirm, and verdict
**Source:** Model choice.
**Rule:** Every candidate is screened at 1,000 weeks on the same seed. The leaders are re-run at full length and marked confirmed. The verdict states:
- the best pattern for the requirement and where it fails, or that none reaches the success bar;
- how many families reach the bar;
- the most sorties the fleet sustains at that bar, and how far that is from the requirement;
- how the current plan compares.

**Code:** `patterns.py` → `generate`, `analyze`, `_verdict`.
**Test:** `test_analysis_never_recommends_diagnostic_families`, `test_verdict_reports_the_shortfall_when_the_requirement_is_out_of_reach`.

---

## 9. Trust and reproducibility

### A-1: Run records
**Source:** Model choice.
**Rule:** Every run saves the full config, a fingerprint of it, the model version, the build commit, the seed, and a fingerprint of the results. Verifying a record re-runs it and confirms the results match exactly, or explains what changed.
**Code:** `runs.py` → `run_plan`, `verify_record`.
**Test:** `test_tampering_is_detected`.

### A-2: Seeds for sweeps
**Source:** Model choice.
**Rule:** In a sweep, each variant's seed comes from the main seed and the variant's position, so the whole sweep re-runs identically however it is split across workers. Fixes and pattern searches instead reuse the seed of the run shown, so comparisons are like-for-like.

$$seed_i = \mathrm{SHA256}(\text{"tps-sweep:"} \,\|\, seed \,\|\, \text{":"} \,\|\, i)_{\text{first 4 bytes}} \wedge \texttt{0x7FFFFFFF}$$

**Code:** `sweep.py` → `derive_seed`.
**Test:** `test_derived_seeds_are_stable_and_distinct`.

### A-3: The fast engine matches the reference
**Source:** Model choice.
**Rule:** `engine.py` must give identical results to `reference.py` for the same seed, across randomized scenarios covering every mode and option.
**Code:** `engine.py` → `run_compiled_week`.
**Test:** `test_fast_engine_matches_reference`.

### A-4: Runs anywhere
**Source:** Model choice.
**Rule:** The model uses only Python's standard library, so it runs unchanged in the browser (Pyodide) and on a server.
**Code:** `tps_core/__init__.py`.
**Test:** `test_only_standard_library_imports`.

---

## 10. Watching a week (play-by-play)

### X-1: Recording a week
**Source:** Model choice.
**Rule:** The readable engine can record every event of a week in order: each day's starting aircraft and front line, each go's launch, launches and who flew them (planned, lineup, spare, or 2407), aborts, landings with Code 3, every fix (window, when its clock started, when the aircraft is ready, or down for the week), and lost sorties with their cause. Recording happens after the random draws it describes, so it never changes results. From the log the model builds a bar for everything each aircraft did (flying, waiting for the long-fix day, in fix, paused for the weekend, down for the week) and the week's story in time order.
**Code:** `reference.py` → `run_week` (`record`); `replay.py` → `_tail_bars`, `_story`.
**Test:** `test_recording_changes_nothing_and_reproduces_counts`.

### X-2: Replaying any week exactly
**Source:** Model choice.
**Rule:** To replay week *k* of a run, the fast engine runs the first *k* − 1 weeks from the run's seed, which leaves the random draws exactly where the original run had them, then the readable engine plays week *k* with the recorder on. The replay is checked against the fast engine's result for the same week. No results change, so every existing run record can be replayed.
**Code:** `replay.py` → `replay`.
**Test:** `test_replay_matches_the_original_run`.

### X-3: Which weeks to offer
**Source:** Model choice.
**Rule:** Each run record lists weeks worth watching:
- **Typical:** sorties flown closest to the middle of all weeks.
- **Typical failure:** the first failed week on the most common failing flying day (or recovery, if no flying day fails).
- **Worst:** the fewest sorties flown, then the fewest aircraft ready next Monday.
- **Recovery only:** the first week that flew every sortie but failed the next-Monday check.

Any week number can also be replayed.
**Code:** `replay.py` → `pick_weeks`; `runs.py` → `run_plan` (`replay_weeks`).
**Test:** `test_offered_weeks_fit_their_descriptions`.

### X-4: Why the week failed
**Source:** Model choice.
**Rule:** For a failed week, the model starts at the first failure and explains it from the log only. For each lost sortie's cause: which aborts used up how many spares; which aircraft broke or aborted earlier that day and when their fixes finished, compared with the go's launch; or which aircraft were down at the start of the day and why. For a recovery failure, it lists the aircraft still down and why, plus the weekend repair hours. It closes by noting whether 2407 adds were available.
**Code:** `replay.py` → `_why`.
**Test:** `test_failure_explanations_name_the_cause`.

### X-5: Real clock times
**Source:** Unit convention.
**Rule:** Times read as hours after the day's first launch (+10:00). With an optional first launch time, such as 07:30, they read as real times, moving to the next day after midnight.
**Code:** `replay.py` → `clock`; `schemas.py` → `_validate_options` (`first_launch_time`).
**Test:** `test_clock_times`.

---

## 11. Not modeled yet

- **Multi-week tempo:** each run is one week starting fresh. Fatigue, phase clocks, and hangar queens need multi-week mode.
- **Long or off-station sorties:** sorties that cross midnight or leave the aircraft away (mobility, bomber).
- **Crew, equipment, and fuel queues:** contention is assumed to be inside the unit's fix rates.
- **Scheduled maintenance by day:** phase and inspection pulls are folded into the starting MC rate.
- **Supply and cannibalization:** assumed to be inside the fix rates.

## 12. DAFI 21-101 paragraphs referenced

Only paragraphs checked against the public text of DAFI 21-101 (with Change 1) are cited:

| Paragraph | What it says, in short | Where it shows up |
| --- | --- | --- |
| 1.3.3 | MAJCOMs set utilization standards for combat-coded fighters, including standard turn patterns, turn-time inspections, and average sortie duration, and help units assess shortfalls | R-2, T-2, L-1, standard patterns input |
| 1.14 | 12-hour continuous duty limit, extendable to 16 with squadron commander approval; 8 hours of rest | F-4 weekend shift options |
| Table 1.2 | Primary mission aircraft get priority for the first 8 work hours after landing | F-3 context |
| 2.4.3.15 | Procedures to review repeat, recur, and cannot-duplicate discrepancies | F-6 |
| 2.9.9.2 | Use a sortie production model for the MDS where one exists | Purpose of TPS |
| 2.2.4 | Joint annual maintenance and flying hour plan balancing sorties with maintenance capability | Purpose of TPS |
