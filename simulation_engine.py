from __future__ import annotations

# Explicit Monte Carlo/simulation layer.
# The implementation remains in turn_pattern_modeler.py for backward compatibility.
from turn_pattern_modeler import (  # noqa: F401
    FLYING_DAYS,
    WEEKDAYS,
    AircraftInventory,
    DayResult,
    DaySchedule,
    EventDistribution,
    HomestationData,
    IterationResult,
    Scenario,
    SimulationSummary,
    compare_turn_patterns,
    run_iteration,
    simulate,
)
