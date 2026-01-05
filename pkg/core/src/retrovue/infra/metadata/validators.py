from __future__ import annotations

from collections.abc import Iterable

import structlog

PROBE_ONLY_FIELDS: list[str] = [
    "runtime_seconds",
    "aspect_ratio",
    "resolution",
    "audio_channels",
    "audio_format",
    "container",
    "video_codec",
]


_log = structlog.get_logger(__name__)


def validate_authoritative_fields(sidecar: dict) -> None:
    """Validate that probe-only fields are not marked authoritative.

    Args:
        sidecar: Parsed sidecar payload (dict), using top-level keys and `_meta`.

    Raises:
        ValueError: if any probe-only field is listed as authoritative.
    """
    meta = sidecar.get("_meta") if isinstance(sidecar, dict) else None
    if not isinstance(meta, dict):
        _log.info("authoritative_fields_validation_skipped", reason="no_meta")
        return

    fields: Iterable[str] = meta.get("authoritative_fields") or []
    bad = sorted(set(name for name in fields if name in PROBE_ONLY_FIELDS))
    if bad:
        msg = (
            "Probe-only fields cannot be authoritative: "
            + ", ".join(bad)
        )
        _log.error("authoritative_fields_invalid", fields=bad)
        raise ValueError(msg)

    _log.info("authoritative_fields_ok")



