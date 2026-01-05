"""
Custom exceptions for RetroVue operations.

This module provides custom exception classes for different types of errors
that can occur during RetroVue operations.
"""


class RetroVueError(Exception):
    """Base exception for all RetroVue errors."""

    pass


class ValidationError(RetroVueError):
    """Raised when validation fails."""

    pass


class ConstraintError(RetroVueError):
    """Raised when database constraint violation occurs."""

    pass


class BusinessRuleError(RetroVueError):
    """Raised when business rule violation occurs."""

    pass


class ResourceError(RetroVueError):
    """Raised when resource is not available."""

    pass


class OperationError(RetroVueError):
    """Raised when operation fails."""

    pass


class IngestError(OperationError):
    """Raised when ingest operation fails."""

    pass


class WipeError(OperationError):
    """Raised when wipe operation fails."""

    pass


class AssetProcessingError(OperationError):
    """Raised when asset processing fails."""

    pass
