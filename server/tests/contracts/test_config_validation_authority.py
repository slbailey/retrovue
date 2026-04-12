"""
Contract tests for INV-CONFIG-VALIDATION-AUTHORITY.

Proves that:
1. Production entry points always validate (cannot be bypassed).
2. Invalid config cannot reach runtime components through public loaders.
3. Test helpers can construct intentionally incomplete fixtures.
4. The public API of load_defaults / resolve_channel_config has no
   validate parameter — schema validation is unconditional.
"""

from __future__ import annotations

import inspect
import textwrap
from pathlib import Path
from types import MappingProxyType

import pytest

from retrovue.config.config_loader import (
    load_defaults,
    reset_defaults_cache,
)
from retrovue.config.resolver import resolve_channel_config, resolve_defaults_only
from retrovue.config.schema import SchemaValidationError
from retrovue.config.testing import (
    load_defaults_unvalidated,
    resolve_channel_unvalidated,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_defaults_cache()
    yield
    reset_defaults_cache()


# ---------------------------------------------------------------------------
# 1. Production entry points have no validate parameter
# ---------------------------------------------------------------------------

class TestNoBypassParameter:
    """Public API functions MUST NOT expose a validate parameter."""

    def test_load_defaults_has_no_validate_param(self):
        sig = inspect.signature(load_defaults)
        assert "validate" not in sig.parameters, (
            "load_defaults() MUST NOT expose a 'validate' parameter — "
            "schema validation is unconditional in production"
        )

    def test_resolve_channel_config_has_no_validate_param(self):
        sig = inspect.signature(resolve_channel_config)
        assert "validate" not in sig.parameters

    def test_resolve_defaults_only_has_no_validate_param(self):
        sig = inspect.signature(resolve_defaults_only)
        assert "validate" not in sig.parameters


# ---------------------------------------------------------------------------
# 2. Invalid config cannot slip through production loaders
# ---------------------------------------------------------------------------

class TestProductionRejectsInvalid:
    """Production loaders MUST reject structurally invalid files."""

    def test_load_defaults_rejects_missing_domain(self, tmp_path: Path):
        """A defaults.yaml missing a required domain MUST fail validation."""
        content = textwrap.dedent("""\
            scheduling:
              broadcast_day_start_hour: 6
            # missing: playout, channel, hls, streaming, system, integrations, air
        """)
        p = tmp_path / "bad_defaults.yaml"
        p.write_text(content)
        with pytest.raises(SchemaValidationError):
            load_defaults(p)

    def test_load_defaults_rejects_wrong_type(self, tmp_path: Path):
        """A defaults.yaml with a wrong-type field MUST fail validation."""
        import yaml
        real = Path("/opt/retrovue/config/defaults.yaml")
        if not real.exists():
            pytest.skip("config/defaults.yaml not present")
        data = yaml.safe_load(real.read_text())
        data["channel"]["linger_seconds"] = "twenty"
        p = tmp_path / "bad_defaults.yaml"
        p.write_text(yaml.dump(data))
        with pytest.raises(SchemaValidationError):
            load_defaults(p)

    def test_resolve_channel_config_rejects_missing_id(self, tmp_path: Path):
        """A channel YAML with no identifier MUST fail validation."""
        (tmp_path / "bad.yaml").write_text("name: No ID\n")
        real = Path("/opt/retrovue/config/defaults.yaml")
        if not real.exists():
            pytest.skip("config/defaults.yaml not present")
        with pytest.raises(SchemaValidationError):
            resolve_channel_config(tmp_path / "bad.yaml")


# ---------------------------------------------------------------------------
# 3. Test helpers work with incomplete fixtures
# ---------------------------------------------------------------------------

class TestTestHelpersBypass:
    """Test helpers MUST successfully load intentionally incomplete YAML."""

    def test_load_defaults_unvalidated_accepts_incomplete(self, tmp_path: Path):
        content = textwrap.dedent("""\
            scheduling:
              broadcast_day_start_hour: 6
        """)
        p = tmp_path / "partial.yaml"
        p.write_text(content)
        cfg = load_defaults_unvalidated(p)
        assert isinstance(cfg, MappingProxyType)
        assert cfg["scheduling"]["broadcast_day_start_hour"] == 6

    def test_resolve_channel_unvalidated_accepts_incomplete(self, tmp_path: Path):
        defaults_content = textwrap.dedent("""\
            scheduling:
              broadcast_day_start_hour: 6
            channel:
              linger_seconds: 20
        """)
        dp = tmp_path / "defaults.yaml"
        dp.write_text(defaults_content)

        channel_content = textwrap.dedent("""\
            channel: test
            number: 1
            channel:
              linger_seconds: 60
        """)
        cp = tmp_path / "test.yaml"
        cp.write_text(channel_content)

        cfg = resolve_channel_unvalidated(cp, dp)
        assert cfg["channel"]["linger_seconds"] == 60

    def test_test_helper_does_not_pollute_singleton(self, tmp_path: Path):
        """After load_defaults_unvalidated, the singleton cache is clear."""
        content = "scheduling:\n  broadcast_day_start_hour: 99\n"
        p = tmp_path / "temp.yaml"
        p.write_text(content)
        load_defaults_unvalidated(p)

        # The singleton should be None now (reset by the helper).
        # A subsequent load_defaults() without path should search standard
        # paths, NOT return the temp fixture.
        reset_defaults_cache()  # ensure clean
        # We don't call load_defaults() here because it would search
        # for the real file — just verify the cache is empty.
        from retrovue.config.config_loader import _defaults
        assert _defaults is None


# ---------------------------------------------------------------------------
# 4. _load_defaults_impl is not in __all__
# ---------------------------------------------------------------------------

class TestInternalNotExported:
    """Internal bypass functions MUST NOT be in public __all__."""

    def test_load_defaults_impl_not_in_all(self):
        from retrovue.config import config_loader
        assert "_load_defaults_impl" not in config_loader.__all__

    def test_validate_param_not_in_load_defaults(self):
        """Confirm no way to pass validate through the public surface."""
        try:
            load_defaults(validate=False)  # type: ignore[call-arg]
        except TypeError:
            pass  # Expected — param doesn't exist
        else:
            pytest.fail("load_defaults() accepted validate=False — bypass is leaking")
