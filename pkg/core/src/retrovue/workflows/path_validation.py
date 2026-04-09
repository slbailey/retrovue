"""
Path validation at container import time per INV-PATH-VALIDATION-ON-IMPORT-001.

Path mappings are stored but NOT validated at source registration time.
At container import, sampled asset paths are checked against effective
mappings to catch misconfiguration early.

This module MUST NOT read from stdin or write to stdout.
"""

from __future__ import annotations

import structlog
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

logger = structlog.get_logger(__name__)


@dataclass
class PathValidationResult:
    """Result of path validation at import time."""

    status: str  # "passed" or "failed"
    diagnostic: str | None = None
    warnings: list[str] = field(default_factory=list)
    resolved_count: int = 0
    failed_count: int = 0


def _apply_mappings(path: str, mappings: list[tuple[str, str]]) -> str | None:
    """Apply path mappings (longest-prefix match) to resolve a source path."""
    normalised = path.replace("\\", "/")
    best: tuple[int, str] | None = None

    for source_prefix, retrovue_prefix in mappings:
        src_norm = source_prefix.replace("\\", "/").rstrip("/")
        if normalised.startswith(src_norm + "/") or normalised == src_norm:
            remainder = normalised[len(src_norm):]
            resolved = str(Path(retrovue_prefix) / remainder.lstrip("/"))
            prefix_len = len(src_norm)
            if best is None or prefix_len > best[0]:
                best = (prefix_len, resolved)

    return best[1] if best else None


def validate_paths_at_import(
    *,
    effective_mappings: list[tuple[str, str]],
    sample_paths: list[str],
    path_exists_fn: Callable[[str], bool] | None = None,
) -> PathValidationResult:
    """Validate that sampled asset paths resolve using effective mappings.

    Args:
        effective_mappings: List of (source_path, retrovue_path) tuples.
        sample_paths: Sample asset paths to validate.
        path_exists_fn: Callable that checks if a resolved path exists.
            Defaults to os.path.exists-style check.

    Returns:
        PathValidationResult indicating pass/fail with diagnostics.
    """
    if path_exists_fn is None:
        path_exists_fn = lambda p: Path(p).exists()

    if not sample_paths:
        return PathValidationResult(status="passed", resolved_count=0, failed_count=0)

    resolved_count = 0
    failed_count = 0
    failed_paths: list[str] = []

    for sample in sample_paths:
        mapped = _apply_mappings(sample, effective_mappings)
        if mapped and path_exists_fn(mapped):
            resolved_count += 1
        else:
            failed_count += 1
            failed_paths.append(sample)

    total = resolved_count + failed_count

    # All failed → hard failure
    if resolved_count == 0:
        # Determine unresolvable prefix for diagnostic
        if not effective_mappings:
            diagnostic = (
                "INV-PATH-VALIDATION-ON-IMPORT-001: no path mappings configured for source. "
                f"Sample paths could not be resolved: {failed_paths[:3]}. "
                "Use 'retrovue source path-map add' to configure mappings."
            )
        else:
            configured_prefixes = [m[0] for m in effective_mappings]
            diagnostic = (
                f"INV-PATH-VALIDATION-ON-IMPORT-001: path mappings do not cover sample paths. "
                f"Configured prefixes: {configured_prefixes}. "
                f"Unresolvable samples: {failed_paths[:3]}. "
                "Use 'retrovue source path-map add' to add the correct mapping."
            )

        logger.warning(
            "path_validation_failed",
            resolved=resolved_count,
            failed=failed_count,
            sample_failures=failed_paths[:3],
        )

        return PathValidationResult(
            status="failed",
            diagnostic=diagnostic,
            resolved_count=resolved_count,
            failed_count=failed_count,
        )

    # Partial failure → warning, proceed
    warnings: list[str] = []
    if failed_count > 0:
        for fp in failed_paths:
            warnings.append(f"Sample path not resolvable: {fp}")
        logger.info(
            "path_validation_partial",
            resolved=resolved_count,
            failed=failed_count,
            sample_failures=failed_paths[:5],
        )

    return PathValidationResult(
        status="passed",
        resolved_count=resolved_count,
        failed_count=failed_count,
        warnings=warnings,
    )
