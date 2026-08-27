"""Vendor-neutral STO scheduling research core.

Phase 1 provides a bounded Microsoft Project XML (MSPDI) importer and a
canonical, deterministic representation. It does not claim Microsoft Project
or Primavera P6 semantic compatibility.
"""

from .mspdi import MSPDI_NAMESPACE, MspdiImportError, import_mspdi, inventory_mspdi
from .provenance import canonical_json_bytes, canonical_sha256
from .validation import ValidationReport, validate_canonical_schedule

__all__ = [
    "MSPDI_NAMESPACE",
    "MspdiImportError",
    "ValidationReport",
    "canonical_json_bytes",
    "canonical_sha256",
    "import_mspdi",
    "inventory_mspdi",
    "validate_canonical_schedule",
]

__version__ = "0.1.1"
