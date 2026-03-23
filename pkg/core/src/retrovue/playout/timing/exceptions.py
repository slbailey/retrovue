"""Exceptions for playout timing subsystem."""


class CadenceVFRViolation(Exception):
    """Raised when CADENCE mode is forced on a VFR or INDETERMINATE input.

    INV-CADENCE-INPUT-VFR-FORBIDDEN-001: This is a hard rejection —
    not a warning, not a fallback. The system MUST refuse.
    """
