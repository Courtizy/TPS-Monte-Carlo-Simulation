"""Config schema for tps (schema "tps-core/1").

A config is plain JSON holding everything a run needs. load_scenario() turns it
into a Scenario or raises ConfigError listing every problem at once. Unknown
keys are errors, so a typo can never fall back to a default silently.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field, fields
from typing import Any

from tps.L0_inputs.rules import (
    DEFAULT_FLYING_DAYS,
    DEFAULT_RECOVERY_DAYS,
    RuleSet,
    aircraft_required,
    commit_aircraft,
)

SCHEMA = "tps-core/1"
EVENT_MODES = ("Spreadsheet", "Fixed Count Random Placement", "Fully Random")
FIX_MODES = ("Expected", "Random")
COVERAGE_OPTIONS = (0, 8, 12, 16, 24)
DEFAULT_GO_TIMES = ((0.0, 2.0), (10.0, 12.0), (14.0, 16.0), (18.0, 20.0))
RATE_KEYS = ("mc_rate", "break_rate", "ground_abort_rate")
LEGACY_FIX_KEYS = (("fix_8hr_rate", 8.0), ("fix_12hr_rate", 12.0), ("fix_24hr_rate", 24.0))
MAX_GOES = 4
TOP_KEYS = (
    "schema", "name", "notes", "inventory", "rates", "rules", "schedule",
    "required_sorties", "success", "options", "sources", "sute", "seasonality",
)


class ConfigError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("Invalid config:\n  " + "\n  ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class Inventory:
    pai: int


@dataclass(frozen=True)
class Rates:
    mc_rate: float
    break_rate: float
    ground_abort_rate: float
    # Cumulative fix rates: ((hours, share fixed within those hours), ...), hours rising.
    fix_windows: tuple[tuple[float, float], ...]


def window_key(hours: float) -> str:
    """Row field name for fixes finishing in a window, e.g. fixed_8hr or fixed_1.5hr."""
    return f"fixed_{int(hours) if float(hours).is_integer() else hours}hr"


@dataclass(frozen=True)
class DayPlan:
    first_go: int = 0
    second_go: int = 0
    third_go: int = 0
    fourth_go: int = 0
    spares: int | None = None  # None = first go x spare rate, rounded up

    @property
    def daily_sorties(self) -> int:
        return self.first_go + self.second_go + self.third_go + self.fourth_go

    @property
    def goes(self) -> tuple[int, int, int, int]:
        return (self.first_go, self.second_go, self.third_go, self.fourth_go)


@dataclass(frozen=True)
class Options:
    event_mode: str = "Fixed Count Random Placement"
    fix_mode: str = "Random"
    go_times: tuple[tuple[float, float], ...] = DEFAULT_GO_TIMES
    spares_cover_goes: tuple[int, ...] | None = None  # 1-based go numbers; None = all
    allow_2407_adds: bool = False
    weekend_coverage_hours: tuple[tuple[str, int], ...] = (("Sat", 24), ("Sun", 24))
    go_profile: tuple[int, float, float] | None = None  # (goes per day, sortie hours, turn window hours)
    first_launch_time: str | None = None   # "07:30": shows real clock times in the play-by-play [X-5]
    repeat_rate: float = 0.0
    recur_rate: float = 0.0
    repeat_window_hours: float = 24.0
    recur_window_hours: float = 72.0


@dataclass(frozen=True)
class Scenario:
    name: str
    inventory: Inventory
    rates: Rates
    rules: RuleSet
    schedule: dict[str, DayPlan]
    required_sorties: int
    options: Options = field(default_factory=Options)
    minimum_monday_aircraft: int | None = None
    backlog_threshold: int | None = None  # None = backlog reported, not pass/fail
    sute_target: float | None = None      # deployed daily SUTE, from whatever figures were given [M-9]
    sute_basis: str = "sute"              # what the home requirement matches: "sute" or "per_aircraft"
    sute_ceiling: float | None = None     # surge capacity, if the unit sets one
    required_from_sute: bool = False

    @property
    def goes_per_day(self) -> int:
        """Goes the unit flies: from the go profile or explicit go times, else the most the schedule uses."""
        if self.options.go_profile is not None or self.options.go_times != DEFAULT_GO_TIMES:
            return len(self.options.go_times)
        used = [sum(1 for g in plan.goes if g) for plan in self.schedule.values()]
        return max(used + [1])


# ---------------------------------------------------------------- helpers
def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _share(value: Any) -> bool:
    return _num(value) and 0 <= value <= 1


def fingerprint(obj: Any) -> str:
    """SHA-256 of canonical JSON (key order and spacing ignored)."""
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- validation
def validate_config(config: Any) -> list[str]:
    """Every structural problem in a config; empty means it loads."""
    if not isinstance(config, dict):
        return ["The config must be a JSON object."]
    errors: list[str] = []
    for key in config:
        if key not in TOP_KEYS:
            errors.append(f"Unknown key: {key}")
    if config.get("schema") != SCHEMA:
        errors.append(f'schema must be "{SCHEMA}"')
    for key in ("inventory", "rates", "rules", "schedule"):
        if key not in config:
            errors.append(f"Missing: {key}")
    if "required_sorties" not in config and "sute" not in config:
        errors.append("Missing: required_sorties (or a sute block to work it out from)")
    errors += _validate_sute(config.get("sute"))
    from tps.L0_inputs.seasonality import validate_seasonality
    errors += validate_seasonality(config.get("seasonality"))

    inventory = config.get("inventory", {})
    if not isinstance(inventory, dict) or set(inventory) - {"pai"}:
        errors.append('inventory must be {"pai": whole number}')
    elif not _count(inventory.get("pai")) or inventory.get("pai") == 0:
        errors.append("inventory.pai must be a whole number above 0")

    rates = config.get("rates", {})
    if not isinstance(rates, dict):
        errors.append("rates must be an object")
    else:
        for key in RATE_KEYS:
            if key not in rates:
                errors.append(f"rates.{key} is missing")
            elif not _share(rates[key]):
                errors.append(f"rates.{key} must be between 0 and 1")
        legacy = [k for k, _ in LEGACY_FIX_KEYS]
        allowed = set(RATE_KEYS) | set(legacy) | {"fix_windows"}
        errors += [f"Unknown rate: rates.{key}" for key in rates if key not in allowed]
        has_legacy = any(k in rates for k in legacy)
        if "fix_windows" in rates and has_legacy:
            errors.append("Use rates.fix_windows or the three fix_8hr/12hr/24hr rates, not both")
        elif "fix_windows" in rates:
            errors += _validate_windows(rates["fix_windows"])
        else:
            for key in legacy:
                if key not in rates:
                    errors.append(f"rates.{key} is missing (or give rates.fix_windows)")
                elif not _share(rates[key]):
                    errors.append(f"rates.{key} must be between 0 and 1")
            fixes = [rates.get(k) for k in legacy]
            if all(_share(v) for v in fixes) and not fixes[0] <= fixes[1] <= fixes[2]:
                errors.append("Fix rates are cumulative: fixed within 8 hours can't be above fixed within 12 hours, and 12 hours can't be above 24 hours")

    rules = config.get("rules", {})
    rule_keys = {f.name for f in fields(RuleSet)}
    flying = DEFAULT_FLYING_DAYS
    if not isinstance(rules, dict):
        errors.append("rules must be an object")
    else:
        errors += [f"Unknown rule: rules.{key}" for key in rules if key not in rule_keys]
        for key in ("commit_rate", "spare_rate"):
            if key not in rules:
                errors.append(f"rules.{key} is missing")
            elif not _share(rules[key]):
                errors.append(f"rules.{key} must be between 0 and 1")
        for key in ("flying_days", "recovery_days"):
            days = rules.get(key)
            if days is not None and (not isinstance(days, list) or not days
                                     or not all(isinstance(d, str) for d in days)):
                errors.append(f"rules.{key} must be a list of day names")
        if isinstance(rules.get("flying_days"), list):
            flying = tuple(rules["flying_days"])
        for key in ("max_daily_sorties", "max_second_go", "max_third_go", "max_fourth_go", "max_day_to_day_delta"):
            if rules.get(key) is not None and not _count(rules[key]):
                errors.append(f"rules.{key} must be a whole number or null")
        if "first_day_fix_hours" in rules and not (_num(rules["first_day_fix_hours"]) and rules["first_day_fix_hours"] >= 0):
            errors.append("rules.first_day_fix_hours must be a number of hours, 0 or more")
        patterns = rules.get("standard_patterns")
        if patterns is not None and not (
            isinstance(patterns, list) and patterns and all(
                isinstance(p, list) and 1 <= len(p) <= MAX_GOES and all(_count(g) for g in p)
                and all(p[i + 1] <= p[i] for i in range(len(p) - 1)) and p[0] > 0 for p in patterns)):
            errors.append("rules.standard_patterns must be a list of patterns like [8, 6, 4], each go no larger than the one before")

    schedule = config.get("schedule", {})
    plan_keys = {f.name for f in fields(DayPlan)}
    if not isinstance(schedule, dict):
        errors.append("schedule must be an object keyed by flying day")
    else:
        for day, plan in schedule.items():
            if day not in flying:
                errors.append(f"schedule.{day} is not a flying day")
            if not isinstance(plan, dict):
                errors.append(f"schedule.{day} must be an object")
                continue
            for key, value in plan.items():
                if key not in plan_keys:
                    errors.append(f"Unknown field: schedule.{day}.{key}")
                elif not (value is None and key == "spares") and not _count(value):
                    errors.append(f"schedule.{day}.{key} must be a whole number")
            goes = [plan.get(k, 0) for k in ("first_go", "second_go", "third_go", "fourth_go")]
            if all(_count(g) for g in goes) and any(goes[i + 1] > goes[i] for i in range(3)):
                # [R-5]
                errors.append(f"schedule.{day}: each go must be no larger than the one before")

    if "required_sorties" in config and not _count(config["required_sorties"]):
        errors.append("required_sorties must be a whole number")

    success = config.get("success", {})
    if not isinstance(success, dict) or set(success) - {"minimum_monday_aircraft", "backlog_threshold"}:
        errors.append("success may hold only minimum_monday_aircraft and backlog_threshold")
    else:
        for key, value in success.items():
            if value is not None and not _count(value):
                errors.append(f"success.{key} must be a whole number or null")

    errors += _validate_options(config.get("options", {}))
    options = config.get("options", {}) if isinstance(config.get("options"), dict) else {}
    profile = options.get("go_profile") if isinstance(options.get("go_profile"), dict) else None
    goes_allowed = (profile.get("goes_per_day") if profile else
                    len(options["go_times"]) if isinstance(options.get("go_times"), list) else MAX_GOES)
    if isinstance(schedule, dict) and _count(goes_allowed):
        names = ("first_go", "second_go", "third_go", "fourth_go")
        for day, plan in schedule.items():
            if isinstance(plan, dict) and any(_count(plan.get(n, 0)) and plan.get(n, 0) > 0
                                              for n in names[goes_allowed:]):
                errors.append(f"schedule.{day} plans more goes than the {goes_allowed} per day the go profile allows")

    sources = config.get("sources", {})
    if not isinstance(sources, dict) or not all(isinstance(v, str) for v in sources.values()):
        errors.append("sources must map names to text")
    return errors


def _validate_options(options: Any) -> list[str]:
    if not isinstance(options, dict):
        return ["options must be an object"]
    errors = [f"Unknown option: options.{k}" for k in options if k not in {f.name for f in fields(Options)}]
    if options.get("event_mode", EVENT_MODES[1]) not in EVENT_MODES:
        errors.append(f"options.event_mode must be one of: {', '.join(EVENT_MODES)}")
    if options.get("fix_mode", "Random") not in FIX_MODES:
        errors.append(f"options.fix_mode must be one of: {', '.join(FIX_MODES)}")
    first = options.get("first_launch_time")
    if first is not None and not (isinstance(first, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", first)):
        errors.append('options.first_launch_time must be a 24-hour time like "07:30"')
    profile = options.get("go_profile")
    if profile is not None:
        if "go_times" in options:
            errors.append("Use options.go_profile or options.go_times, not both")
        errors += _validate_profile(profile)
    go_times = options.get("go_times")
    if go_times is not None:
        ok = isinstance(go_times, list) and 1 <= len(go_times) <= 4 and all(
            isinstance(p, list) and len(p) == 2 and _num(p[0]) and _num(p[1]) and p[0] < p[1] <= 24
            for p in go_times
        )
        if not ok or any(go_times[i + 1][0] <= go_times[i][0] for i in range(len(go_times) - 1)):
            errors.append("options.go_times must be up to 4 [launch, land] pairs with rising launch hours, landing by 24")
    covered = options.get("spares_cover_goes")
    if covered is not None and (not isinstance(covered, list) or not all(_count(g) and 1 <= g <= 4 for g in covered)):
        errors.append("options.spares_cover_goes must be null or a list of go numbers 1-4")
    if "allow_2407_adds" in options and not isinstance(options["allow_2407_adds"], bool):
        errors.append("options.allow_2407_adds must be true or false")
    weekend = options.get("weekend_coverage_hours", {})
    if not isinstance(weekend, dict) or not all(v in COVERAGE_OPTIONS for v in weekend.values()):
        errors.append("options.weekend_coverage_hours values must be 0, 8, 12, 16, or 24")
    for key in ("repeat_rate", "recur_rate"):
        if key in options and not _share(options[key]):
            errors.append(f"options.{key} must be between 0 and 1")
    if _share(options.get("repeat_rate", 0)) and _share(options.get("recur_rate", 0)) and \
            options.get("repeat_rate", 0) + options.get("recur_rate", 0) > 1:
        errors.append("options.repeat_rate + recur_rate must not exceed 1")
    for key in ("repeat_window_hours", "recur_window_hours"):
        if key in options and not (_num(options[key]) and options[key] > 0):
            errors.append(f"options.{key} must be a positive number")
    return errors


def _validate_windows(windows: Any) -> list[str]:
    if not isinstance(windows, list) or not windows:
        return ["rates.fix_windows must be a list like [{\"hours\": 8, \"rate\": 0.45}, ...]"]
    errors = []
    previous_hours, previous_rate = 0.0, 0.0
    for i, window in enumerate(windows):
        if not isinstance(window, dict) or set(window) != {"hours", "rate"}:
            errors.append(f"rates.fix_windows[{i}] must have exactly hours and rate")
            continue
        hours, rate = window["hours"], window["rate"]
        if not (_num(hours) and hours > previous_hours):
            errors.append(f"rates.fix_windows[{i}].hours must be above the window before it")
        if not _share(rate):
            errors.append(f"rates.fix_windows[{i}].rate must be between 0 and 1")
        elif rate < previous_rate:
            errors.append(f"Fix rates are cumulative: the {hours}-hour rate can't be below the one before it")
        if _num(hours):
            previous_hours = hours
        if _share(rate):
            previous_rate = rate
    return errors


def _validate_profile(profile: Any) -> list[str]:
    if not isinstance(profile, dict) or set(profile) - {"goes_per_day", "sortie_hours", "turn_hours"}:
        return ["options.go_profile must hold goes_per_day, sortie_hours, and turn_hours"]
    errors = []
    goes = profile.get("goes_per_day")
    if not (_count(goes) and 1 <= goes <= MAX_GOES):
        errors.append(f"options.go_profile.goes_per_day must be 1 to {MAX_GOES}")
    for key in ("sortie_hours", "turn_hours"):
        if not (_num(profile.get(key)) and profile[key] > 0):
            errors.append(f"options.go_profile.{key} must be a positive number of hours")
    if not errors:
        day_length = goes * profile["sortie_hours"] + (goes - 1) * profile["turn_hours"]
        if day_length > 24:
            errors.append(f"The go profile needs {day_length:g} hours, more than one day")
    return errors


def _validate_sute(sute: Any) -> list[str]:
    """Deployed tempo may be given by any figures that pin down a SUTE [M-9]."""
    from tps.L0_inputs.tempo import ALIASES, FIGURES, solve_tempo
    if sute is None:
        return []
    allowed = set(FIGURES) | set(ALIASES) | {"surge_ceiling", "requirement_basis"}
    if not isinstance(sute, dict) or set(sute) - allowed:
        return ["sute may hold possessed_aircraft, om_days, sorties, possessed_aircraft_days, sorties_per_om_day, "
                "avg_sorties_per_aircraft (or monthly_sorties_per_aircraft), sute, surge_ceiling, and requirement_basis"]
    errors = []
    for key, value in sute.items():
        if key in ("surge_ceiling", "requirement_basis"):
            continue
        if value is not None and not (_num(value) and value > 0):
            errors.append(f"sute.{key} must be a positive number")
    if sute.get("surge_ceiling") is not None and not (_num(sute["surge_ceiling"]) and sute["surge_ceiling"] > 0):
        errors.append("sute.surge_ceiling must be a positive number or null")
    if sute.get("requirement_basis", "sute") not in ("sute", "per_aircraft"):
        errors.append('sute.requirement_basis must be "sute" or "per_aircraft"')
    if not errors and solve_tempo(sute)["sute"] is None:
        errors.append("These deployed figures don't pin down a SUTE. Add one more, such as O&M days or possessed aircraft.")
    return errors


# [T-2]
def profile_go_times(goes: int, sortie_hours: float, turn_hours: float) -> tuple[tuple[float, float], ...]:
    """Launch and landing hours for each go: first launch at hour 0, then land, turn, launch."""
    times, launch = [], 0.0
    for _ in range(goes):
        land = launch + sortie_hours
        times.append((launch, land))
        launch = land + turn_hours
    return tuple(times)


# [M-7]
def deployed_sute(config: dict[str, Any]) -> float | None:
    from tps.L0_inputs.tempo import solve_tempo
    sute = config.get("sute")
    return None if not sute else solve_tempo(sute)["sute"]


def required_from_sute(config: dict[str, Any]) -> int:
    """Weekly required sorties at the deployed tempo, matched by SUTE (default) or by sorties per aircraft [M-7]."""
    from tps.L0_inputs.tempo import home_requirements
    days = len(config.get("rules", {}).get("flying_days", DEFAULT_FLYING_DAYS))
    both = home_requirements(deployed_sute(config), config["inventory"]["pai"], days)
    basis = (config.get("sute") or {}).get("requirement_basis", "sute")
    return both["match_per_aircraft" if basis == "per_aircraft" else "match_sute"]


# ---------------------------------------------------------------- loading
def load_scenario(config: dict[str, Any]) -> Scenario:
    errors = validate_config(config)
    if errors:
        raise ConfigError(errors)
    raw_rules = dict(config["rules"])
    for key in ("flying_days", "recovery_days"):
        if key in raw_rules:
            raw_rules[key] = tuple(raw_rules[key])
    if raw_rules.get("standard_patterns") is not None:
        raw_rules["standard_patterns"] = tuple(tuple(p) for p in raw_rules["standard_patterns"])
    rules = RuleSet(**raw_rules)
    raw_options = dict(config.get("options", {}))
    if "go_profile" in raw_options:
        profile = raw_options.pop("go_profile")
        raw_options["go_profile"] = (profile["goes_per_day"], float(profile["sortie_hours"]), float(profile["turn_hours"]))
        raw_options["go_times"] = profile_go_times(*raw_options["go_profile"])
    elif "go_times" in raw_options:
        raw_options["go_times"] = tuple((float(a), float(b)) for a, b in raw_options["go_times"])
    if raw_options.get("spares_cover_goes") is not None:
        raw_options["spares_cover_goes"] = tuple(raw_options["spares_cover_goes"])
    weekend = dict(Options().weekend_coverage_hours)
    weekend.update(raw_options.get("weekend_coverage_hours", {}))
    raw_options["weekend_coverage_hours"] = tuple(weekend.items())
    success = config.get("success", {})
    return Scenario(
        name=config.get("name", ""),
        inventory=Inventory(pai=config["inventory"]["pai"]),
        rates=Rates(**{key: float(config["rates"][key]) for key in RATE_KEYS}, fix_windows=_windows(config["rates"])),
        rules=rules,
        schedule={day: DayPlan(**config["schedule"].get(day, {})) for day in rules.flying_days},
        required_sorties=config["required_sorties"] if "required_sorties" in config else required_from_sute(config),
        options=Options(**raw_options),
        minimum_monday_aircraft=success.get("minimum_monday_aircraft"),
        backlog_threshold=success.get("backlog_threshold"),
        sute_target=deployed_sute(config),
        sute_ceiling=(config.get("sute") or {}).get("surge_ceiling"),
        sute_basis=(config.get("sute") or {}).get("requirement_basis", "sute"),
        required_from_sute="required_sorties" not in config,
    )


# [F-1]
def _windows(rates: dict[str, Any]) -> tuple[tuple[float, float], ...]:
    if "fix_windows" in rates:
        return tuple((float(w["hours"]), float(w["rate"])) for w in rates["fix_windows"])
    return tuple((hours, float(rates[key])) for key, hours in LEGACY_FIX_KEYS)


# [R-4] [M-7]
def plan_warnings(scenario: Scenario) -> list[str]:
    """Plan-versus-rules checks. Warnings, not errors: the plan still runs."""
    rules = scenario.rules
    warnings = []
    commit = commit_aircraft(scenario.inventory.pai, rules)
    previous = None
    for day in rules.flying_days:
        plan = scenario.schedule[day]
        if aircraft_required(plan, rules) > commit:
            warnings.append(f"{day}: first go + spares ({aircraft_required(plan, rules)}) is above commit ({commit}).")
        limits = (
            ("max_daily_sorties", plan.daily_sorties, "sorties"),
            ("max_second_go", plan.second_go, "second-go sorties"),
            ("max_third_go", plan.third_go, "third-go sorties"),
            ("max_fourth_go", plan.fourth_go, "fourth-go sorties"),
        )
        for key, value, words in limits:
            limit = getattr(rules, key)
            if limit is not None and value > limit:
                warnings.append(f"{day}: {value} {words} is above the limit of {limit}.")
        if previous is not None and rules.max_day_to_day_delta is not None:
            change = abs(plan.daily_sorties - previous)
            if change > rules.max_day_to_day_delta:
                warnings.append(f"{day}: sorties change by {change} from the day before (limit {rules.max_day_to_day_delta}).")
        previous = plan.daily_sorties
        if plan.daily_sorties and len([g for g in plan.goes if g]) > len(scenario.options.go_times):
            warnings.append(f"{day}: more goes planned than the {len(scenario.options.go_times)} the go profile allows.")
        if rules.standard_patterns and plan.daily_sorties:
            flown = tuple(g for g in plan.goes if g)
            if flown not in rules.standard_patterns:
                warnings.append(f"{day}: {'-'.join(map(str, flown))} is not one of the standard turn patterns.")
    planned = sum(scenario.schedule[d].daily_sorties for d in rules.flying_days)
    if scenario.sute_ceiling:
        planned_sute = planned / (scenario.inventory.pai * len(rules.flying_days))
        if planned_sute > scenario.sute_ceiling:
            warnings.append(f"Planned SUTE ({planned_sute:.2f}) is above the surge ceiling ({scenario.sute_ceiling:.2f}).")
    if scenario.required_sorties > planned:
        warnings.append(f"Required sorties ({scenario.required_sorties}) exceed planned sorties ({planned}).")
    return warnings
