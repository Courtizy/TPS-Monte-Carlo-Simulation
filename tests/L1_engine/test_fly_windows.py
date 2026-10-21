"""Fly windows: each day's first launch to last land, set per day [T-4], past midnight if needed [T-5]."""
import sys
from pathlib import Path
from random import Random

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helpers import example  # noqa: E402
from tps.L1_engine import engine, reference  # noqa: E402
from tps.L1_engine.replay import replay  # noqa: E402
from tps.L0_inputs.schemas import day_starts, launch_clock, load_scenario, plan_warnings, validate_config  # noqa: E402

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")


def _windows(**days):
    """Every flying day 0700-2200 unless given."""
    return {d: days.get(d, ["0700", "2200"]) for d in DAYS}


def _one_jet(fly_windows=None, days=("Mon", "Tue"), break_rate=1.0, fix_hours=24):
    """One aircraft flying one 2-hour sortie on each of days; each break needs a fix_hours fix."""
    config = example(
        inventory={"pai": 1},
        rates={"mc_rate": 1.0, "break_rate": break_rate, "ground_abort_rate": 0.0,
               "fix_windows": [{"hours": fix_hours, "rate": 1.0}]},
        rules={"spare_rate": 0.0, "first_day_fix_hours": 24, "max_daily_sorties": None, "max_day_to_day_delta": None},
        schedule={d: {"first_go": 1 if d in days else 0, "second_go": 0} for d in DAYS},
        required_sorties=0,
        options={"event_mode": "Spreadsheet", "fix_mode": "Expected", "repeat_rate": 0.0, "recur_rate": 0.0,
                 "go_profile": {"goes_per_day": 1, "sortie_hours": 2, "turn_hours": 1}},
    )
    if fly_windows:
        config["options"]["fly_windows"] = fly_windows
    scenario = load_scenario(config)
    rows, _ = engine.run_week(scenario, Random(0))
    assert (rows, _) == reference.run_week(scenario, Random(0))
    return scenario, rows


# [T-4]
def test_fly_windows_move_each_days_first_launch():
    scenario, _ = _one_jet(_windows(Tue=["1000", "2200"], Wed=["0600", "2000"]))
    starts = day_starts(scenario)
    assert starts[:3] == [0.0, 27.0, 47.0]     # hour 0 is Monday 0700
    assert starts[5:] == [120.0, 144.0, 168.0]  # weekend and next Monday keep Monday's clock
    assert launch_clock(scenario.options) == "0700"
    no_windows, _ = _one_jet()
    assert day_starts(no_windows) == [24.0 * i for i in range(8)]


def test_a_later_window_gives_an_overnight_fix_time_to_finish():
    # Monday's sortie lands at 0900 and its 24-hour fix is ready Tuesday 0900.
    _, same = _one_jet(_windows())
    _, later = _one_jet(_windows(Tue=["1000", "2200"]))
    assert same[0]["code_3"] == 1 and later[0]["code_3"] == 1
    assert same[1]["mc_aircraft_for_flying"] == 0 and same[1]["lost_sorties"] == 1    # Tuesday 0700: not ready
    assert later[1]["mc_aircraft_for_flying"] == 1 and later[1]["lost_sorties"] == 0  # Tuesday 1000: ready


def test_fly_window_checks():
    good = example(options={"fly_windows": _windows(Fri=["0700", "2400"], Thu=["07:00", "22:00"])})
    assert not validate_config(good)                  # military time; a colon is read too
    partial = example(options={"fly_windows": {"Tue": ["0800", "2200"], "Thu": ["1000", "0100"]}})
    assert not validate_config(partial)                 # blank days take the day before's window
    filled = dict((d, (a, b)) for d, a, b in load_scenario(partial).options.fly_windows)
    assert filled["Mon"] == filled["Tue"] == filled["Wed"] == (8.0, 22.0)   # Monday takes the first one given
    assert filled["Thu"] == filled["Fri"] == (10.0, 25.0)
    same = example(options={"fly_windows": _windows(Tue=["0700", "0700"])})
    assert any("fly_windows.Tue: the first launch and last land can't be the same time" in e for e in validate_config(same))
    bad_time = example(options={"fly_windows": _windows(Wed=["7:00", "2200"])})
    assert any("fly_windows.Wed must be two military times" in e for e in validate_config(bad_time))
    both = example(options={"fly_windows": _windows(), "first_launch_time": "0700"})
    assert any("not both" in e for e in validate_config(both))
    weekend = example(options={"fly_windows": {**_windows(), "Sat": ["0800", "1200"]}})
    assert any("fly_windows.Sat is not a flying day" in e for e in validate_config(weekend))


def test_a_go_landing_after_the_window_closes_is_a_warning():
    # Two goes: land at 2 and 12 hours after first launch, so 0900 and 1900 from a 0700 start.
    config = example(options={"fly_windows": _windows(Fri=["0700", "1600"])})
    warnings = plan_warnings(load_scenario(config))
    assert "Fri: go 2 lands at 1900, after the fly window closes at 1600." in warnings
    assert not any(w.startswith(("Mon:", "Tue:")) and "fly window" in w for w in warnings)


def test_replay_reads_fly_windows_as_clock_times():
    config = example(options={"fly_windows": _windows(Tue=["0930", "2200"])})
    r = replay(config, 5, 3)
    assert r["matches_run"] and r["first_launch_time"] == "0700"
    assert r["day_starts"][1] == 26.5
    tuesday = next(e for e in r["events"] if e["kind"] == "go" and e["day"] == "Tue")
    assert tuesday["t"] == 26.5


# [T-5]
def test_a_window_can_close_after_midnight():
    scenario, _ = _one_jet(_windows(Thu=["1400", "0200"]))
    assert ("Thu", 14.0, 26.0) in scenario.options.fly_windows
    assert day_starts(scenario)[3] == 72 + 7          # Thursday's launches still count to Thursday
    assert not validate_config(example(options={"fly_windows": _windows(Thu=["0000", "2400"])}))


def test_landing_past_midnight_cuts_the_next_days_fix_time():
    # Thursday's sortie lands at 2300 or 0100 and needs a 4-hour fix; Friday opens at 0430.
    _, early = _one_jet(_windows(Thu=["2100", "2300"], Fri=["0430", "2200"]), days=("Thu", "Fri"), fix_hours=4)
    _, late = _one_jet(_windows(Thu=["2300", "0100"], Fri=["0430", "2200"]), days=("Thu", "Fri"), fix_hours=4)
    assert early[4]["mc_aircraft_for_flying"] == 1     # ready at 0300
    assert late[4]["mc_aircraft_for_flying"] == 0      # ready at 0500, after Friday's first launch
    assert late[4]["lost_first_go_short"] == 1


def test_an_aircraft_still_flying_misses_the_next_days_first_launch():
    config_windows = _windows(Thu=["2300", "0100"], Fri=["0030", "2200"])
    scenario, rows = _one_jet(config_windows, days=("Thu", "Fri"), break_rate=0.0)
    assert rows[3]["sorties_flown"] == 1
    assert rows[4]["mc_aircraft_for_flying"] == 0 and rows[4]["lost_sorties"] == 1   # lands Friday 0100
    assert ("Fri: first launch at 0030 comes before the day before's last go lands (0100). "
            "Aircraft still flying can't make it.") in plan_warnings(scenario)
