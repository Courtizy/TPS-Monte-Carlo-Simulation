"""The play-by-play: recording, exact replay, chosen weeks, explanations, and clock times."""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import ROOT, example  # noqa: E402
from test_engine_equivalence import _random_config  # noqa: E402
from tps_core import engine, reference, web_api  # noqa: E402
from tps_core.metrics import score_week  # noqa: E402
from tps_core.replay import clock, pick_weeks, replay  # noqa: E402
from tps_core.runs import run_plan, simulate  # noqa: E402
from tps_core.schemas import load_scenario, validate_config  # noqa: E402

EXAMPLES = [json.loads((ROOT / "examples" / f).read_text())
            for f in ("synthetic_week.json", "synthetic_3go.json", "synthetic_4go.json")]


# [X-1]
def test_recording_changes_nothing_and_reproduces_counts():
    cases = random.Random(11)
    for _ in range(120):
        scenario = load_scenario(_random_config(cases))
        seed = cases.randrange(10**9)
        plain, logged = random.Random(seed), random.Random(seed)
        for _ in range(5):
            log = []
            expected = reference.run_week(scenario, plain)
            assert reference.run_week(scenario, logged, log) == expected
            days = expected[0]
            count = lambda kind: sum(e["kind"] == kind for e in log)  # noqa: E731
            assert count("launch") == sum(d["sorties_flown"] for d in days)
            assert count("lost") == sum(d["lost_sorties"] for d in days)
            assert count("abort") == sum(d["ground_abort"] for d in days)
            assert count("break") == sum(d["code_3"] for d in days)


# [X-2]
def test_replay_matches_the_original_run():
    for config in EXAMPLES:
        weeks, _ = simulate(config, 300, 21)
        for k in (0, 1, 137, 299):
            r = replay(config, 21, k)
            assert r["matches_run"] and r["week"] == k + 1
            assert r["day_rows"][0]["sorties_flown"] == weeks[k][0][0]["sorties_flown"]
            assert [d["lost_sorties"] for d in r["day_rows"]] == [d["lost_sorties"] for d in weeks[k][0]]
        assert replay(config, 21, 137)["story"] == replay(config, 21, 137)["story"]


# [X-3]
def test_offered_weeks_fit_their_descriptions():
    for config in EXAMPLES:
        weeks, scenario = simulate(config, 1500, 8)
        picks = pick_weeks(weeks, scenario.rules.flying_days)
        score = lambda i: score_week(*weeks[i], scenario.rules.flying_days)  # noqa: E731
        if picks["typical_failure"] is not None:
            assert not score(picks["typical_failure"])["succeeds"]
        if picks["recovery_only"] is not None:
            assert score(picks["recovery_only"])["failure_modes"] == ["Recovery"]
        worst = score(picks["worst"])["total_sorties"]
        assert all(score(i)["total_sorties"] >= worst for i in range(len(weeks)))
    record = run_plan(EXAMPLES[0], 500, 3)
    assert set(record["replay_weeks"]) == {"typical", "typical_failure", "worst", "recovery_only"}


# [X-4]
def test_failure_explanations_name_the_cause():
    for config in EXAMPLES:
        weeks, scenario = simulate(config, 1500, 8)
        picks = pick_weeks(weeks, scenario.rules.flying_days)
        for name in ("typical_failure", "recovery_only"):
            if picks[name] is None:
                continue
            r = replay(config, 8, picks[name])
            assert not r["succeeds"] and len(r["why"]) >= 2
            text = " ".join(r["why"])
            assert "Tail" in text or "aircraft" in text
            if r["first_failure_day"] in scenario.rules.flying_days:
                assert "missed its plan" in r["why"][0] or "started with" in r["why"][0]
        typical = replay(config, 8, picks["typical"])
        if typical["succeeds"]:
            assert typical["why"][0].startswith("This week succeeded")


# [X-5]
def test_clock_times():
    days = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Next Mon")
    assert clock(58, days, None) == "Wed +10:00"
    assert clock(58, days, "07:30") == "Wed 17:30"
    assert clock(68, days, "07:30") == "Thu 03:30"    # past midnight moves to the next day
    assert validate_config(example(options={"first_launch_time": "7:30"}))
    assert not validate_config(example(options={"first_launch_time": "07:30"}))


def test_tail_bars_are_well_formed_and_web_api_round_trip():
    r = json.loads(web_api.replay(json.dumps(EXAMPLES[1]), 4, 10))
    assert r["matches_run"] and len(r["tails"]) == r["start_mc"]   # every MC aircraft gets a row, idle or not
    for row in r["tails"]:
        for bar in row["bars"]:
            assert bar["kind"] in {"fly", "fix", "wait", "paused", "down"}
            assert 0 <= bar["start"] < bar["end"] <= r["week_hours"]
    assert json.loads(web_api.replay(json.dumps(EXAMPLES[0]), 4, -1))["errors"]
