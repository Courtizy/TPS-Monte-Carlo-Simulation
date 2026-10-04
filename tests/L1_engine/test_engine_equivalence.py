"""The fast engine must match the readable reference exactly for the same seed."""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helpers import example  # noqa: E402
from tps.L1_engine import engine  # noqa: E402
from tps.L1_engine import reference  # noqa: E402
from tps.L0_inputs.schemas import COVERAGE_OPTIONS, EVENT_MODES, FIX_MODES, load_scenario  # noqa: E402


def _random_config(r):
    fixes = sorted(r.random() for _ in range(3))
    if r.random() < 0.2:
        fixes = [r.choice([0.0, 1.0])] * 3
    rate = lambda: r.choice([0.0, 1.0, r.random(), r.random() * 0.4])  # noqa: E731
    goes = 4
    options_extra = {}
    if r.random() < 0.5:   # a go profile with 1-4 goes
        goes = r.randint(1, 4)
        sortie = r.choice([0.75, 1.5, 2.0, 3.0])
        turn = r.choice([1.0, 2.0, 3.0, 8.0])
        while goes * sortie + (goes - 1) * turn > 24:
            turn = max(0.5, turn / 2)
        options_extra["go_profile"] = {"goes_per_day": goes, "sortie_hours": sortie, "turn_hours": turn}
    schedule = {}
    for day in ("Mon", "Tue", "Wed", "Thu", "Fri"):
        counts = [r.randint(0, 9)]
        for g in range(1, 4):
            counts.append(r.randint(0, counts[-1]) if g < goes and r.random() < (0.9 if g == 1 else 0.3) else 0)
        schedule[day] = {"first_go": counts[0], "second_go": counts[1], "third_go": counts[2],
                         "fourth_go": counts[3], "spares": r.choice([None, None, 0, 1, 3])}
    rates = {"mc_rate": r.choice([1.0, r.uniform(0.4, 1.0)]), "break_rate": rate(), "ground_abort_rate": rate()}
    if r.random() < 0.5:
        rates.update(fix_8hr_rate=fixes[0], fix_12hr_rate=fixes[1], fix_24hr_rate=fixes[2])
    else:   # 1-5 fix windows at assorted hours
        hours = sorted(r.sample([1, 2, 3, 4, 6, 8, 12, 16, 24, 36], r.randint(1, 5)))
        shares = sorted(r.random() for _ in hours)
        rates["fix_windows"] = [{"hours": h, "rate": v} for h, v in zip(hours, shares)]
    repeat = r.choice([0.0, 0.1, 0.5, 1.0])
    config = example(
        inventory={"pai": r.randint(3, 30)},
        rules={"spare_rate": r.choice([0.0, 0.2, 0.34]), "long_fix_start_day": r.choice(["Mon", "Tue", "Wed", "Sat"]),
               "first_day_fix_hours": r.choice([4, 8, 12]),
               "max_daily_sorties": None, "max_second_go": None, "max_day_to_day_delta": None},
        schedule=schedule,
        required_sorties=r.randint(0, 60),
        success={"minimum_monday_aircraft": r.choice([None, 3]), "backlog_threshold": r.choice([None, 0, 2])},
        options={"event_mode": r.choice(EVENT_MODES), "fix_mode": r.choice(FIX_MODES),
                 "spares_cover_goes": r.choice([None, [1], [1, 2], [2]]), "allow_2407_adds": r.random() < 0.5,
                 "weekend_coverage_hours": {"Sat": r.choice(COVERAGE_OPTIONS), "Sun": r.choice(COVERAGE_OPTIONS)},
                 "repeat_rate": repeat, "recur_rate": r.choice([0.0, min(0.1, 1.0 - repeat), 1.0 - repeat]),
                 "repeat_window_hours": r.choice([24.0, 12.0, 48.0]), "recur_window_hours": r.choice([72.0, 36.0])},
    )
    config["rates"] = rates
    config["options"].pop("go_profile", None)
    config["options"].update(options_extra)
    if goes < 4 and "go_profile" not in options_extra:
        config["options"]["go_times"] = [[0, 2], [10, 12], [14, 16], [18, 20]][:goes]
    return config


# [A-3]
def test_fast_engine_matches_reference():
    cases = random.Random(2026)
    for case in range(250):
        scenario = load_scenario(_random_config(cases))
        seed = cases.randrange(10**9)
        ref_rng, fast_rng = random.Random(seed), random.Random(seed)
        plan = engine.compile_plan(scenario)
        for week in range(25):
            assert engine.run_compiled_week(plan, fast_rng) == reference.run_week(scenario, ref_rng), (case, week)
        assert ref_rng.random() == fast_rng.random(), f"case {case}: random streams diverged"
