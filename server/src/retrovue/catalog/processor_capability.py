"""
Processor capability registry: declare what each processor produces and its execution order.

Phase 2: job queue and runtime use this to resolve target_type and validate results.
Contract: docs/contracts/core/ProcessorCapabilityContract_v0.1.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..adapters.registry import ENRICHERS

__all__ = ["ProcessorCapability", "get_capability", "get_processors_for_target", "CAPABILITY_REGISTRY"]


@dataclass(frozen=True)
class ProcessorCapability:
    """Per-processor capability: target_type, order, produced/required metadata."""

    processor_id: str
    target_type: str  # "MEDIA" or "ASSET"
    execution_order: int
    produced_metadata: tuple[str, ...]
    required_metadata: tuple[str, ...]


# Registry keyed by processor_id (same keys as ENRICHERS).
CAPABILITY_REGISTRY: dict[str, ProcessorCapability] = {
    "ffprobe": ProcessorCapability(
        processor_id="ffprobe",
        target_type="MEDIA",
        execution_order=10,
        produced_metadata=(
            "duration_ms",
            "video_codec",
            "audio_codec",
            "container",
            "bitrate",
            "resolution",
        ),
        required_metadata=("path_uri",),
    ),
    "loudness": ProcessorCapability(
        processor_id="loudness",
        target_type="MEDIA",
        execution_order=20,
        produced_metadata=("loudness_lufs", "gain_db", "loudness_range_lu"),
        required_metadata=("path_uri",),
    ),
    "interstitial-type": ProcessorCapability(
        processor_id="interstitial-type",
        target_type="ASSET",
        execution_order=5,
        produced_metadata=("interstitial_type",),
        required_metadata=(),
    ),
}


def get_capability(processor_id: str) -> ProcessorCapability | None:
    """Return capability for a processor, or None if unknown."""
    return CAPABILITY_REGISTRY.get(processor_id)


def get_processors_for_target(target_type: str) -> list[str]:
    """Return processor_ids for the given target_type, in execution_order ascending."""
    candidates = [
        (cap.processor_id, cap.execution_order)
        for cap in CAPABILITY_REGISTRY.values()
        if cap.target_type == target_type
    ]
    candidates.sort(key=lambda x: x[1])
    return [pid for pid, _ in candidates]
