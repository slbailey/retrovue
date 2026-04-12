from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft7Validator


@lru_cache(maxsize=1)
def load_sidecar_validator(path: str = "docs/metadata/sidecar-schema.json") -> Draft7Validator:
    """Load and cache the Draft-07 validator for the sidecar schema.

    The path is resolved relative to the current working directory if not absolute.
    """
    schema_path = Path(path)
    if not schema_path.is_absolute():
        # Try common project structure roots from this module location
        here = Path(__file__).resolve()
        # repo root guess 3 levels up -> src/retrovue/infra/metadata/
        candidate = (here.parents[3] / path).resolve()
        if candidate.exists():
            schema_path = candidate
    with schema_path.open("r", encoding="utf-8") as fp:
        schema = json.load(fp)
    return Draft7Validator(schema)


def validate_sidecar_json(sidecar: dict) -> None:
    """Validate a sidecar JSON object against the cached Draft-07 sidecar schema.

    Raises ValueError with a newline-joined list of error messages if invalid.
    """
    validator = load_sidecar_validator()
    errors = sorted(validator.iter_errors(sidecar), key=lambda e: e.path)
    if errors:
        messages: list[str] = []
        for err in errors:
            loc = "/".join([str(p) for p in err.path])
            messages.append(f"{loc}: {err.message}")
        raise ValueError("Sidecar JSON validation failed:\n" + "\n".join(messages))



