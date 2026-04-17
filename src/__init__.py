"""
__init__.py — Public API for DAHS_2 src package
"""

from src.simulator import (
    WarehouseSimulator,
    SimulationMetrics,
    Job,
    Operation,
    StationState,
    ZoneConfig,
    JobType,
)
from src.features import (
    FeatureExtractor,
    SCENARIO_FEATURE_NAMES,
    JOB_FEATURE_NAMES,
    FEATURE_DESCRIPTIONS,
)
from src.heuristics import (
    fifo_dispatch,
    priority_edd_dispatch,
    critical_ratio_dispatch,
    atc_dispatch,
    wspt_dispatch,
    slack_dispatch,
    DISPATCH_MAP,
    ALL_HEURISTICS,
    HEURISTIC_LABELS,
)
from src.hybrid_scheduler import (
    BatchwiseSelector,
    HybridPriority,
    SwitchingLog,
    load_batchwise_selector,
    load_hybrid_priority,
)
from src.presets import (
    PresetScenario,
    PRESETS,
    get_preset,
    get_all_presets,
    run_preset_demo,
    run_all_preset_demos,
)

__all__ = [
    # Simulator
    "WarehouseSimulator",
    "SimulationMetrics",
    "Job",
    "Operation",
    "StationState",
    "ZoneConfig",
    "JobType",
    # Features
    "FeatureExtractor",
    "SCENARIO_FEATURE_NAMES",
    "JOB_FEATURE_NAMES",
    "FEATURE_DESCRIPTIONS",
    # Heuristics
    "fifo_dispatch",
    "priority_edd_dispatch",
    "critical_ratio_dispatch",
    "atc_dispatch",
    "wspt_dispatch",
    "slack_dispatch",
    "DISPATCH_MAP",
    "ALL_HEURISTICS",
    "HEURISTIC_LABELS",
    # Hybrid scheduler
    "BatchwiseSelector",
    "HybridPriority",
    "SwitchingLog",
    "load_batchwise_selector",
    "load_hybrid_priority",
    # Presets
    "PresetScenario",
    "PRESETS",
    "get_preset",
    "get_all_presets",
    "run_preset_demo",
    "run_all_preset_demos",
]
