"""Vendor-neutral STO scheduling research core.

The package provides a bounded Microsoft Project XML (MSPDI) importer, a
canonical representation, a fail-closed deterministic calculation experiment,
and a local Prototype 0 scenario workspace. It does not claim Microsoft Project
or Primavera P6 semantic compatibility.
"""

from .calculation_profile import (
    PROFILE_VERSION,
    CalculationProfileError,
    build_calculation_profile,
    build_engine_projection,
    calculate_forward_schedule,
    compare_source_coordinates,
    sanitized_profile_evidence,
)
from .mspdi import MSPDI_NAMESPACE, MspdiImportError, import_mspdi, inventory_mspdi
from .provenance import canonical_json_bytes, canonical_sha256
from .validation import ValidationReport, validate_canonical_schedule

__all__ = [
    "MSPDI_NAMESPACE",
    "PROFILE_VERSION",
    "CalculationProfileError",
    "MspdiImportError",
    "ValidationReport",
    "build_calculation_profile",
    "build_engine_projection",
    "calculate_forward_schedule",
    "canonical_json_bytes",
    "canonical_sha256",
    "compare_source_coordinates",
    "import_mspdi",
    "inventory_mspdi",
    "sanitized_profile_evidence",
    "validate_canonical_schedule",
]

__version__ = "0.1.1"
