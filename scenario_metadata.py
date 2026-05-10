from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256

from simulation_engine import Scenario


MODEL_VERSION = "0.4.0"


@dataclass(frozen=True)
class ScenarioRunMetadata:
    scenario_name: str
    timestamp_utc: str
    model_version: str
    policy_name: str
    policy_version: str
    random_seed: int | None
    iterations: int
    recovery_model: str
    event_count_model: str
    fix_count_model: str
    input_fingerprint: str


def build_run_metadata(
    scenario: Scenario,
    *,
    scenario_name: str,
    iterations: int,
    random_seed: int | None,
    recovery_model: str,
) -> ScenarioRunMetadata:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return ScenarioRunMetadata(
        scenario_name=scenario_name,
        timestamp_utc=timestamp,
        model_version=MODEL_VERSION,
        policy_name=scenario.policy.policy_name,
        policy_version=scenario.policy.policy_version,
        random_seed=random_seed,
        iterations=iterations,
        recovery_model=recovery_model,
        event_count_model=scenario.homestation.event_count_model,
        fix_count_model=scenario.homestation.fix_count_model,
        input_fingerprint=_fingerprint_scenario(scenario),
    )


def _fingerprint_scenario(scenario: Scenario) -> str:
    schedule_text = "|".join(
        f"{day}:{schedule.first_go},{schedule.second_go},{schedule.third_go},{schedule.fourth_go},{schedule.spares}"
        for day, schedule in sorted(scenario.schedule.items())
    )
    raw = "|".join(
        [
            str(scenario.inventory),
            str(scenario.homestation),
            schedule_text,
            str(scenario.total_required_sorties),
            scenario.policy.policy_name,
            scenario.policy.policy_version,
        ]
    )
    return sha256(raw.encode("utf-8")).hexdigest()[:16]
