import unittest
from dataclasses import replace

from gui_controller import build_gui_config, display_rows, run_gui_model
from input_validation import validate_scenario
from optimizer import planned_attrition_allowance
from pattern_generator import capacity_points, generate_turn_pattern_permutations, PatternConstraints
from recommendation_engine import compare_baseline_candidate, recommendation_fields
from scenario_metadata import build_run_metadata
from simulation_engine import (
    AircraftInventory,
    DaySchedule,
    HomestationData,
    Scenario,
    simulate,
)
from ttp_rules import DEFAULT_TTP_POLICY, TtpPolicy


def scenario(
    schedule,
    required,
    *,
    pai=5,
    mc_rate=1.0,
    ga_rate=0.0,
    break_rate=0.0,
    fix_8=0.0,
    fix_12=0.0,
    fix_24=0.0,
    use_uncommitted=False,
    event_model="Normal TTP",
    fix_model="Normal TTP",
    backlog_threshold=0,
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
):
    return Scenario(
        inventory=AircraftInventory(paa=pai, pai=pai),
        homestation=HomestationData(
            mc_rate=mc_rate,
            ground_abort_rate=ga_rate,
            break_rate=break_rate,
            fix_8hr_rate=fix_8,
            fix_12hr_rate=fix_12,
            fix_24hr_rate=fix_24,
            ttp_commit_rate=policy.commit_rate,
            afi_spare_rate=policy.spare_rate,
            use_uncommitted_aircraft_for_ga_recovery=use_uncommitted,
            event_count_model=event_model,
            fix_count_model=fix_model,
            backlog_threshold=backlog_threshold,
        ),
        schedule=schedule,
        total_required_sorties=required,
        policy=policy,
    )


class ModelValidationTests(unittest.TestCase):
    def test_ute_and_commit_rounding(self):
        point = {item["label"]: item for item in capacity_points(11)}
        self.assertEqual(point["UTE 0.40"]["weekly_sorties"], 22)
        self.assertEqual(point["UTE 0.45"]["weekly_sorties"], 24)
        self.assertEqual(point["55% Commit Surge"]["commit_aircraft"], 6)
        self.assertEqual(point["55% Commit Surge"]["weekly_sorties"], 30)
        nine_pai = {item["label"]: item for item in capacity_points(9)}
        self.assertEqual(nine_pai["55% Commit Surge"]["commit_aircraft"], 4)
        self.assertEqual(nine_pai["55% Commit Surge"]["weekly_sorties"], 20)

    def test_policy_commit_rate_changes_simulation_commit_behavior(self):
        default_scn = scenario(
            {"Mon": DaySchedule(first_go=5)},
            required=5,
            pai=10,
        )
        default_summary = simulate(default_scn, iterations=1, seed=31)
        self.assertEqual(default_summary.sample_iteration.days[0].commit_limit, 5)
        self.assertEqual(default_summary.probability_within_ttp_commit, 1.0)

        tighter_policy = replace(DEFAULT_TTP_POLICY, commit_rate=0.40)
        tighter_scn = scenario(
            {"Mon": DaySchedule(first_go=5)},
            required=5,
            pai=10,
            policy=tighter_policy,
        )
        tighter_summary = simulate(tighter_scn, iterations=1, seed=31)
        self.assertEqual(tighter_summary.sample_iteration.days[0].commit_limit, 4)
        self.assertEqual(tighter_summary.probability_within_ttp_commit, 0.0)
        self.assertEqual(tighter_summary.probability_success, 0.0)

    def test_policy_spare_rate_changes_aircraft_required_without_engine_edits(self):
        spare_policy = replace(DEFAULT_TTP_POLICY, spare_rate=0.25)
        scn = scenario(
            {"Mon": DaySchedule(first_go=4)},
            required=4,
            pai=10,
            policy=spare_policy,
        )
        summary = simulate(scn, iterations=1, seed=32)
        monday = summary.sample_iteration.days[0]
        self.assertEqual(monday.spares, 1)
        self.assertEqual(monday.aircraft_required, 5)

    def test_policy_long_fix_start_day_changes_monday_repair_behavior(self):
        monday_fix_policy = replace(DEFAULT_TTP_POLICY, long_fix_start_day="Mon")
        scn = scenario(
            {"Mon": DaySchedule(first_go=1)},
            required=1,
            pai=2,
            break_rate=1.0,
            fix_8=0.0,
            fix_12=1.0,
            fix_24=1.0,
            policy=monday_fix_policy,
        )
        summary = simulate(scn, iterations=1, seed=33)
        monday = summary.sample_iteration.days[0]
        self.assertEqual(monday.fixed_12hr, 1)
        self.assertEqual(monday.fixed_24hr, 0)

    def test_policy_capacity_points_change_ute_and_commit_outputs(self):
        policy = replace(DEFAULT_TTP_POLICY, ute_levels=(0.50,), commit_rate=0.40)
        point = {item["label"]: item for item in capacity_points(10, policy=policy)}
        self.assertEqual(point["UTE 0.50"]["weekly_sorties"], 25)
        self.assertEqual(point[policy.surge_label]["commit_aircraft"], 4)
        self.assertEqual(point[policy.surge_label]["weekly_sorties"], 20)

    def test_policy_go_structure_limits_generated_patterns(self):
        policy = replace(DEFAULT_TTP_POLICY, max_second_go=1)
        scn = scenario({}, required=1, pai=10, policy=policy)
        patterns = generate_turn_pattern_permutations(15, 10, scn, constraints=None, max_results=40)
        self.assertTrue(patterns)
        for pattern in patterns:
            for day in pattern["schedule"].values():
                self.assertLessEqual(day.second_go, 1)

    def test_input_validation_flags_invalid_rates_and_assumption_warnings(self):
        scn = scenario(
            {"Mon": DaySchedule(first_go=6)},
            required=7,
            pai=10,
            mc_rate=1.2,
        )
        result = validate_scenario(scn)
        self.assertFalse(result.is_valid)
        self.assertTrue(any("MC rate" in error for error in result.errors))
        self.assertTrue(any("Required sorties exceed planned sorties" in warning for warning in result.warnings))

    def test_recommendation_engine_labels_sustainability_and_limiter(self):
        row = {
            "commit_success": 1.0,
            "peak_frontlines": 5,
            "commit_aircraft": 6,
            "weekly_sorties": 26,
            "required_sorties": 24,
            "suppressed_events_count": 0,
            "sortie_success": 0.95,
            "aircraft_success": 0.96,
            "daily_schedule_success": 0.95,
            "recovery_success": 0.60,
            "backlog_success": 0.90,
            "recovery_debt": 2.0,
            "success_ci95_high": 0.96,
            "success_ci95_low": 0.92,
            "low_confidence": False,
            "confidence_warnings": "None",
            "validation_warnings": "None",
            "no_suppressed_events_success": 1.0,
            "planned_attrition_success": 0.95,
            "failure_mode": "Recovery",
            "pattern_with_frontlines": "7(5)-6(4)-6(4)-5(3)-2(2)",
            "success": 0.93,
            "avg_next_monday": 8.4,
        }
        fields = recommendation_fields(row)
        self.assertEqual(fields["operational_assessment"], "Executable / Not Sustainable")
        self.assertEqual(fields["limiting_factor"], "Recovery-Time Limited")

    def test_baseline_candidate_comparison_returns_decision_deltas(self):
        baseline = {
            "pattern_with_frontlines": "5(4)-5(4)-5(4)-5(4)-5(4)",
            "success": 0.80,
            "weekly_sorties": 25,
            "avg_next_monday": 8.0,
            "avg_repair_backlog": 1.5,
            "recovery_debt": 1.0,
            "failure_mode": "Aircraft Availability",
        }
        candidate = {
            "pattern_with_frontlines": "7(5)-6(4)-6(4)-5(3)-2(2)",
            "success": 0.92,
            "weekly_sorties": 26,
            "avg_next_monday": 9.1,
            "avg_repair_backlog": 0.6,
            "recovery_debt": 0.2,
            "failure_mode": "None",
        }
        comparison = compare_baseline_candidate(baseline, candidate)
        self.assertAlmostEqual(comparison["success_delta"], 0.12)
        self.assertEqual(comparison["planned_sorties_delta"], 1)

    def test_run_metadata_tracks_reproducible_inputs(self):
        scn = scenario({"Mon": DaySchedule(first_go=1)}, required=1, pai=2)
        metadata = build_run_metadata(
            scn,
            scenario_name="Unit Test Scenario",
            iterations=100,
            random_seed=42,
            recovery_model="Fleet-Flex Recovery",
        )
        self.assertEqual(metadata.policy_version, DEFAULT_TTP_POLICY.policy_version)
        self.assertEqual(metadata.random_seed, 42)
        self.assertEqual(len(metadata.input_fingerprint), 16)

    def test_gui_controller_runs_thin_dashboard_flow(self):
        config = build_gui_config(
            pai_min=11,
            pai_max=11,
            required_weekly_sorties=24,
            iterations=2,
            random_seed=42,
            mc_rate=0.735,
            ground_abort_rate=0.064,
            break_rate=0.265,
            fix_8hr_rate=0.496,
            fix_12hr_rate=0.607,
            fix_24hr_rate=0.803,
            event_count_model="Normal TTP",
            fix_count_model="Normal TTP",
            max_patterns=2,
            max_daily_sorties=8,
            max_second_go=3,
            max_day_to_day_delta=2,
            ute_levels=(0.40,),
            attrition_scenarios=(("Requirement Based", 0.0),),
        )
        result = run_gui_model(config, include_surge=True)
        self.assertTrue(result.best_rows)
        self.assertIsNotNone(result.recommendation)
        self.assertTrue(display_rows(result.best_rows))
        self.assertIsNotNone(result.surge)

    def test_optimizer_config_rates_feed_model_template(self):
        config = build_gui_config(
            pai_min=11,
            pai_max=11,
            required_weekly_sorties=24,
            iterations=1,
            random_seed=7,
            mc_rate=0.50,
            ground_abort_rate=0.0,
            break_rate=0.0,
            fix_8hr_rate=0.0,
            fix_12hr_rate=0.0,
            fix_24hr_rate=0.0,
            event_count_model="Normal TTP",
            fix_count_model="Normal TTP",
            max_patterns=1,
            max_daily_sorties=5,
            max_second_go=1,
            max_day_to_day_delta=2,
            ute_levels=(0.40,),
            attrition_scenarios=(("Requirement Based", 0.0),),
        )
        result = run_gui_model(config, include_surge=False)
        self.assertTrue(result.rows)
        self.assertLessEqual(max(row["avg_next_monday"] for row in result.rows), 5)

    def test_fractional_aircraft_counts_round_down(self):
        scn = scenario(
            {"Mon": DaySchedule(first_go=8)},
            required=8,
            pai=12,
            mc_rate=0.735,
        )
        summary = simulate(scn, iterations=1, seed=6)
        monday = summary.sample_iteration.days[0]
        self.assertEqual(monday.total_mc_aircraft, 8)
        self.assertEqual(monday.commit_limit, 6)
        self.assertEqual(monday.spares, 0)

    def test_normal_ttp_events_round_up_and_fixes_use_expected_value_rounding(self):
        scn = scenario(
            {"Mon": DaySchedule(first_go=10)},
            required=10,
            pai=20,
            break_rate=0.11,
            fix_8=0.50,
        )
        summary = simulate(scn, iterations=1, seed=7)
        total_code_3 = sum(day.code_3 for day in summary.sample_iteration.days)
        total_8hr_fixes = sum(day.fixed_8hr for day in summary.sample_iteration.days)
        self.assertEqual(total_code_3, 2)
        self.assertEqual(total_8hr_fixes, 1)

    def test_generated_patterns_respect_commit_cap(self):
        scn = scenario({}, required=1, pai=11)
        patterns = generate_turn_pattern_permutations(
            29,
            11,
            scn,
            PatternConstraints(max_daily_sorties=8, max_day_to_day_delta=2, max_second_go=3),
            max_results=40,
        )
        self.assertTrue(patterns)
        for pattern in patterns:
            for day in pattern["schedule"].values():
                self.assertLessEqual(day.aircraft_required(0), 6)

    def test_required_sorties_do_not_equal_full_schedule_success(self):
        scn = scenario(
            {"Mon": DaySchedule(first_go=1, second_go=1)},
            required=1,
            pai=2,
            ga_rate=0.5,
            use_uncommitted=False,
        )
        summary = simulate(scn, iterations=1, seed=1)
        self.assertEqual(summary.probability_meet_sorties, 1.0)
        self.assertEqual(summary.probability_full_schedule, 0.0)
        self.assertEqual(summary.probability_success, 0.0)

    def test_required_sortie_success_is_not_attrition_buffer_success(self):
        scn = scenario(
            {"Mon": DaySchedule(first_go=3, second_go=1)},
            required=3,
            pai=5,
            ga_rate=0.25,
            use_uncommitted=False,
        )
        summary = simulate(scn, iterations=1, seed=34)
        self.assertEqual(summary.sample_iteration.total_sorties, 3)
        self.assertEqual(summary.probability_meet_sorties, 1.0)
        self.assertEqual(summary.probability_full_schedule, 0.0)

    def test_planned_attrition_allowance_uses_floor_for_weekly_planning(self):
        self.assertEqual(planned_attrition_allowance(26, attrition_rate=0.10), 2)
        self.assertEqual(planned_attrition_allowance(26, attrition_rate=0.15), 3)
        self.assertEqual(planned_attrition_allowance(26, attrition_count=4), 4)
        self.assertEqual(planned_attrition_allowance(26), 0)

    def test_monday_excludes_12_and_24_hour_fixes(self):
        scn = scenario(
            {"Mon": DaySchedule(first_go=1)},
            required=1,
            pai=2,
            break_rate=1.0,
            fix_8=0.0,
            fix_12=1.0,
            fix_24=1.0,
        )
        summary = simulate(scn, iterations=1, seed=2)
        monday = summary.sample_iteration.days[0]
        self.assertEqual(monday.fixed_12hr, 0)
        self.assertEqual(monday.fixed_24hr, 0)
        self.assertGreaterEqual(summary.average_repair_backlog, 0)

    def test_event_suppression_is_flagged_not_hidden(self):
        scn = scenario(
            {
                "Mon": DaySchedule(first_go=1, second_go=1),
                "Tue": DaySchedule(first_go=1, second_go=1),
                "Wed": DaySchedule(first_go=1, second_go=1),
                "Thu": DaySchedule(first_go=1, second_go=1),
                "Fri": DaySchedule(first_go=1, second_go=1),
            },
            required=1,
            pai=5,
            break_rate=1.0,
        )
        summary = simulate(scn, iterations=1, seed=3)
        self.assertGreater(summary.suppressed_events_count, 0)
        self.assertEqual(summary.probability_no_suppressed_events, 0.0)
        self.assertEqual(summary.probability_success, 0.0)

    def test_eod_bounds_are_clamped_to_inventory(self):
        scn = scenario(
            {"Mon": DaySchedule(first_go=1)},
            required=1,
            pai=1,
            mc_rate=1.0,
            break_rate=1.0,
            fix_8=1.0,
            fix_12=1.0,
            fix_24=1.0,
        )
        summary = simulate(scn, iterations=1, seed=4)
        for day in summary.sample_iteration.days:
            self.assertGreaterEqual(day.available_eod, 0)
            self.assertLessEqual(day.available_eod, 1)

    def test_backlog_carry_forward_blocks_clean_success(self):
        scn = scenario(
            {"Mon": DaySchedule(first_go=1)},
            required=1,
            pai=2,
            break_rate=1.0,
            fix_8=0.0,
            fix_12=0.0,
            fix_24=0.0,
            backlog_threshold=0,
        )
        summary = simulate(scn, iterations=1, seed=5)
        self.assertGreater(summary.average_repair_backlog, 0)
        self.assertEqual(summary.probability_backlog, 0.0)
        self.assertEqual(summary.probability_success, 0.0)

    def test_known_good_26_sortie_patterns_validate_in_fleet_flex_mode(self):
        patterns = [
            {
                "Mon": DaySchedule(first_go=5, second_go=2),
                "Tue": DaySchedule(first_go=4, second_go=2),
                "Wed": DaySchedule(first_go=4, second_go=2),
                "Thu": DaySchedule(first_go=3, second_go=2),
                "Fri": DaySchedule(first_go=2, second_go=0),
            },
            {
                "Mon": DaySchedule(first_go=5, second_go=2),
                "Tue": DaySchedule(first_go=3, second_go=2),
                "Wed": DaySchedule(first_go=4, second_go=2),
                "Thu": DaySchedule(first_go=3, second_go=2),
                "Fri": DaySchedule(first_go=3, second_go=0),
            },
        ]
        for pai in (11, 12, 13):
            for schedule in patterns:
                scn = scenario(
                    schedule,
                    required=26,
                    pai=pai,
                    mc_rate=0.735,
                    ga_rate=0.064,
                    break_rate=0.265,
                    fix_8=0.496,
                    fix_12=0.607,
                    fix_24=0.803,
                    use_uncommitted=True,
                    event_model="Normal TTP",
                    fix_model="Normal TTP",
                )
                summary = simulate(scn, iterations=300, seed=42)
                self.assertGreaterEqual(summary.probability_success, 0.99)
                self.assertGreaterEqual(summary.probability_full_schedule, 0.99)
                self.assertEqual(summary.probability_within_ttp_commit, 1.0)

    def test_known_good_patterns_fail_strict_mode_without_spares(self):
        scn = scenario(
            {
                "Mon": DaySchedule(first_go=5, second_go=2),
                "Tue": DaySchedule(first_go=4, second_go=2),
                "Wed": DaySchedule(first_go=4, second_go=2),
                "Thu": DaySchedule(first_go=3, second_go=2),
                "Fri": DaySchedule(first_go=2, second_go=0),
            },
            required=26,
            pai=11,
            mc_rate=0.735,
            ga_rate=0.064,
            break_rate=0.265,
            fix_8=0.496,
            fix_12=0.607,
            fix_24=0.803,
            use_uncommitted=False,
            event_model="Normal TTP",
            fix_model="Normal TTP",
        )
        summary = simulate(scn, iterations=100, seed=42)
        self.assertEqual(summary.probability_success, 0.0)
        self.assertEqual(summary.probability_full_schedule, 0.0)
        self.assertEqual(summary.probability_meet_aircraft_required, 1.0)


if __name__ == "__main__":
    unittest.main()
