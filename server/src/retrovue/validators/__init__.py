"""
Validator framework for asset ingest pipeline.

Domain package for asset validation logic. Validators run post-discovery
to verify asset technical properties before the asset can proceed through
the ingest lifecycle.

All validators produce structured results per INV-VALIDATOR-OUTPUT-SHAPE-001.
"""

from .result import ValidationResult, ValidatorEntry, ValidatorError, ValidatorWarning
from .base import BaseValidator
from .pipeline import ValidationPipeline

__all__ = [
    "ValidationResult",
    "ValidatorEntry",
    "ValidatorError",
    "ValidatorWarning",
    "BaseValidator",
    "ValidationPipeline",
]
