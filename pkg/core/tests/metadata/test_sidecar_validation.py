from __future__ import annotations

import pytest

# Ensure jsonschema is installed; skip tests otherwise
pytest.importorskip("jsonschema")

from retrovue.infra.metadata.schema_loader import validate_sidecar_json
from retrovue.infra.metadata.validators import validate_authoritative_fields


def base_meta(**overrides):
    meta = {
        "schema": "retrovue.sidecar",
        "version": "0.1.0",
        "scope": "file",
    }
    meta.update(overrides)
    return meta


def test_valid_episode_sidecar_passes():
    payload = {
        "asset_type": "episode",
        "title": "Pilot (Part 2)",
        "season_number": 1,
        "episode_number": 2,
        "_meta": base_meta(),
    }

    # Schema validation
    validate_sidecar_json(payload)
    # Probe-only authoritative validator should also pass (no authoritative fields)
    validate_authoritative_fields(payload)


def test_promo_missing_promoted_asset_id_fails_schema():
    payload = {
        "asset_type": "promo",
        "title": "Season Launch",
        "_meta": base_meta(),
        "relationships": {},
    }

    with pytest.raises(ValueError):
        validate_sidecar_json(payload)


def test_unknown_key_fails_schema():
    payload = {
        "asset_type": "episode",
        "title": "Pilot (Part 2)",
        "season_number": 1,
        "episode_number": 2,
        "_meta": base_meta(),
        "unexpected": "nope",
    }

    with pytest.raises(ValueError):
        validate_sidecar_json(payload)


def test_probe_only_field_marked_authoritative_fails_validator():
    payload = {
        "asset_type": "episode",
        "title": "Pilot",
        "season_number": 1,
        "episode_number": 1,
        "_meta": base_meta(authoritative_fields=["runtime_seconds"]),
    }

    # Schema allows it; enforcement is separate
    validate_sidecar_json(payload)
    with pytest.raises(ValueError):
        validate_authoritative_fields(payload)


def test_valid_station_ops_passes():
    payload = {
        "asset_type": "episode",
        "title": "Pilot",
        "season_number": 1,
        "episode_number": 1,
        "station_ops": {
            "content_class": "cartoon",
            "daypart_profile": "after_school",
            "ad_avail_model": "kids_30",
        },
        "_meta": base_meta(),
    }
    validate_sidecar_json(payload)
    validate_authoritative_fields(payload)


