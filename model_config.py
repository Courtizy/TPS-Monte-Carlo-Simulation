from __future__ import annotations

from simulation_engine import AircraftInventory, DaySchedule, HomestationData, Scenario
from ttp_rules import DEFAULT_TTP_POLICY, TtpPolicy


DEFAULT_PAA = 11
DEFAULT_PAI = 11
DEFAULT_MC_RATE = 0.735
DEFAULT_GROUND_ABORT_RATE = 0.064
DEFAULT_BREAK_RATE = 0.265
DEFAULT_FIX_8HR_RATE = 0.496
DEFAULT_FIX_12HR_RATE = 0.607
DEFAULT_FIX_24HR_RATE = 0.803
DEFAULT_TTP_COMMIT_RATE = DEFAULT_TTP_POLICY.commit_rate
DEFAULT_AFI_SPARE_RATE = DEFAULT_TTP_POLICY.spare_rate


def default_homestation(
    *,
    use_uncommitted_aircraft_for_ga_recovery: bool = False,
    event_count_model: str = "Normal TTP",
    fix_count_model: str = "Probabilistic Monte Carlo",
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
    mc_rate: float = DEFAULT_MC_RATE,
    ground_abort_rate: float = DEFAULT_GROUND_ABORT_RATE,
    break_rate: float = DEFAULT_BREAK_RATE,
    fix_8hr_rate: float = DEFAULT_FIX_8HR_RATE,
    fix_12hr_rate: float = DEFAULT_FIX_12HR_RATE,
    fix_24hr_rate: float = DEFAULT_FIX_24HR_RATE,
) -> HomestationData:
    return HomestationData(
        mc_rate=mc_rate,
        ground_abort_rate=ground_abort_rate,
        break_rate=break_rate,
        fix_8hr_rate=fix_8hr_rate,
        fix_12hr_rate=fix_12hr_rate,
        fix_24hr_rate=fix_24hr_rate,
        ttp_commit_rate=policy.commit_rate,
        afi_spare_rate=policy.spare_rate,
        use_uncommitted_aircraft_for_ga_recovery=use_uncommitted_aircraft_for_ga_recovery,
        event_count_model=event_count_model,
        fix_count_model=fix_count_model,
    )


def build_scenario(
    schedule: dict[str, DaySchedule],
    total_required_sorties: int,
    use_uncommitted_aircraft_for_ga_recovery: bool,
    *,
    pai: int = DEFAULT_PAI,
    paa: int | None = None,
    event_count_model: str = "Normal TTP",
    fix_count_model: str = "Probabilistic Monte Carlo",
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
    mc_rate: float = DEFAULT_MC_RATE,
    ground_abort_rate: float = DEFAULT_GROUND_ABORT_RATE,
    break_rate: float = DEFAULT_BREAK_RATE,
    fix_8hr_rate: float = DEFAULT_FIX_8HR_RATE,
    fix_12hr_rate: float = DEFAULT_FIX_12HR_RATE,
    fix_24hr_rate: float = DEFAULT_FIX_24HR_RATE,
) -> Scenario:
    return Scenario(
        inventory=AircraftInventory(paa=pai if paa is None else paa, pai=pai),
        homestation=default_homestation(
            use_uncommitted_aircraft_for_ga_recovery=use_uncommitted_aircraft_for_ga_recovery,
            event_count_model=event_count_model,
            fix_count_model=fix_count_model,
            policy=policy,
            mc_rate=mc_rate,
            ground_abort_rate=ground_abort_rate,
            break_rate=break_rate,
            fix_8hr_rate=fix_8hr_rate,
            fix_12hr_rate=fix_12hr_rate,
            fix_24hr_rate=fix_24hr_rate,
        ),
        schedule=schedule,
        total_required_sorties=total_required_sorties,
        policy=policy,
    )


def empty_week_schedule(policy: TtpPolicy = DEFAULT_TTP_POLICY) -> dict[str, DaySchedule]:
    return {day: DaySchedule() for day in policy.flying_days}
