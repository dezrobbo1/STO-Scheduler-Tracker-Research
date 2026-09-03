"""Public façade for the bounded Phase 1 calculation experiment."""

from .calculation_common import CalculationProfileError, PROFILE_VERSION
from .calculation_eligibility import build_calculation_profile
from .calculation_engine import (
    calculate_forward_schedule,
    compare_source_coordinates,
    validate_engine_projection,
)
from .calculation_projection import (
    build_engine_projection,
    sanitized_profile_evidence,
)

__all__ = [
    "PROFILE_VERSION",
    "CalculationProfileError",
    "build_calculation_profile",
    "build_engine_projection",
    "validate_engine_projection",
    "calculate_forward_schedule",
    "compare_source_coordinates",
    "sanitized_profile_evidence",
]
