"""INV-STRUCTURAL-DURATION-001: Compiler must not pick duration_sec=0 presentation assets."""

from __future__ import annotations

import pytest

try:
    from retrovue.dev.stub_asset_resolver import StubAssetResolver
    from retrovue.runtime.asset_resolver import AssetMetadata
    from retrovue.runtime.program_definition import AssemblyResult, AssemblySegment
    from retrovue.runtime.schedule_compiler import _expand_to_compiled_segments
except ImportError:
    pytest.skip(
        "retrovue.runtime dependencies not available",
        allow_module_level=True,
    )


@pytest.mark.contract
def test_template_preroll_skips_zero_duration_bumpers_in_order():
    """First matching bumper with duration_sec>0 wins; 0-duration rows are ignored."""
    resolver = StubAssetResolver()
    resolver.add(
        "intro-broken",
        AssetMetadata(
            type="bumper",
            duration_sec=0,
            title="City Intro",
            file_uri="file:///media/City Intro (1982).mp4",
            tags=("hbo", "presentation", "intros"),
        ),
    )
    resolver.add(
        "intro-ok",
        AssetMetadata(
            type="bumper",
            duration_sec=18,
            title="Valid Intro",
            file_uri="file:///media/valid.mp4",
            tags=("hbo", "presentation", "intros"),
        ),
    )
    result = AssemblyResult(
        segments=[
            AssemblySegment(
                asset_id="ep-001",
                duration_ms=1_800_000,
                segment_type="content",
            ),
        ],
        total_runtime_ms=1_800_000,
    )
    resolver.add(
        "ep-001",
        AssetMetadata(
            type="movie",
            duration_sec=7200,
            title="Feature",
            file_uri="file:///media/movie.mkv",
        ),
    )

    compiled = _expand_to_compiled_segments(
        result,
        resolver,
        slot_duration_ms=1_800_000,
        start_utc_ms=1_700_000_000_000,
        channel_type="premium",
        template_preroll=[{"pool": "intros"}],
    )

    presentations = [s for s in compiled if s.get("segment_type") == "presentation"]
    assert presentations, "expected a presentation segment from template preroll"
    assert presentations[0].get("asset_id") == "intro-ok"
    assert presentations[0].get("duration_ms") == 18_000
