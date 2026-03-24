"""Contract tests: INV-POOL-RESOLUTION-VISIBILITY-001

Pool resolution MUST produce per-filter exclusion diagnostics when assets
are excluded by type, tags, rating, duration, or editorial field mismatches.

These tests validate the diagnostic output structure and the accuracy of
exclusion reason classification — they do NOT modify core query behavior.
"""

from __future__ import annotations

import pytest

try:
    from retrovue.runtime.asset_resolver import (
        AssetMetadata,
        PoolDiagnostics,
        StubAssetResolver,
    )
except ImportError:
    pytest.skip(
        "retrovue.runtime dependencies not available",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_resolver() -> StubAssetResolver:
    """Build a resolver with a mixed catalog of assets.

    Includes assets with deliberate deficiencies for diagnostic testing:
    - wrong_type_promo: promo where pool expects bumper
    - missing_tags_bumper: bumper missing required "intros" tag
    - missing_all_tags: bumper with no tags at all
    - valid_intro_1/2: correctly tagged bumpers
    - long_movie: movie exceeding max_duration
    - wrong_rating_movie: R-rated where pool expects PG
    """
    resolver = StubAssetResolver()

    # Valid intros — match pool {type: bumper, tags: [hbo, presentation, intros]}
    resolver.add("valid-intro-1", AssetMetadata(
        type="bumper", duration_sec=30, title="HBO City 1982",
        tags=("hbo", "presentation", "intros"),
        file_uri="/mnt/bumpers/intro1.mp4",
    ))
    resolver.add("valid-intro-2", AssetMetadata(
        type="bumper", duration_sec=28, title="HBO City 1983",
        tags=("hbo", "presentation", "intros"),
        file_uri="/mnt/bumpers/intro2.mp4",
    ))

    # Wrong type — promo, not bumper
    resolver.add("wrong-type-promo", AssetMetadata(
        type="promo", duration_sec=30, title="Wrong Type Promo",
        tags=("hbo", "presentation", "intros"),
        file_uri="/mnt/promos/wrong_type.mp4",
    ))

    # Missing required tag — has "hbo" and "presentation" but not "intros"
    resolver.add("missing-tag-bumper", AssetMetadata(
        type="bumper", duration_sec=15, title="Missing Tag Bumper",
        tags=("hbo", "presentation"),
        file_uri="/mnt/bumpers/missing_tag.mp4",
    ))

    # No tags at all
    resolver.add("no-tags-bumper", AssetMetadata(
        type="bumper", duration_sec=12, title="No Tags Bumper",
        tags=(),
        file_uri="/mnt/bumpers/no_tags.mp4",
    ))

    # Movies for duration/rating tests
    resolver.add("normal-movie", AssetMetadata(
        type="movie", duration_sec=5400, title="Ghostbusters",
        rating="PG", file_uri="/mnt/movies/ghostbusters.mkv",
    ))
    resolver.add("long-movie", AssetMetadata(
        type="movie", duration_sec=12000, title="Das Boot Director's Cut",
        rating="PG", file_uri="/mnt/movies/das_boot.mkv",
    ))
    resolver.add("wrong-rating-movie", AssetMetadata(
        type="movie", duration_sec=6000, title="Alien",
        rating="R", file_uri="/mnt/movies/alien.mkv",
    ))

    # Register pools
    resolver.register_pools({
        "intros": {
            "match": {"type": "bumper", "tags": ["hbo", "presentation", "intros"]},
        },
        "short_pg_movies": {
            "match": {
                "type": "movie",
                "max_duration_sec": 7200,
                "rating": {"include": ["PG", "PG-13"]},
            },
        },
        "nonexistent": {
            "match": {"type": "bumper", "tags": ["does_not_exist"]},
        },
    })

    return resolver


# ===========================================================================
# Diagnostic structure validation
# ===========================================================================


class TestDiagnosticStructure:
    """PoolDiagnostics dataclass must contain all required fields."""

    # Tier: 1 | Structural invariant
    def test_diagnostics_has_required_fields(self):
        """PoolDiagnostics must expose all INV-POOL-RESOLUTION-VISIBILITY-001 fields."""
        diag = PoolDiagnostics(
            total_considered=10,
            excluded_by_type=2,
            excluded_by_tags=3,
            excluded_by_rating=1,
            excluded_by_duration=1,
            excluded_by_editorial=0,
            matched=3,
            exclusion_reasons={"asset-1": ["type mismatch: expected 'bumper', got 'promo'"]},
        )
        assert diag.total_considered == 10
        assert diag.excluded_by_type == 2
        assert diag.excluded_by_tags == 3
        assert diag.excluded_by_rating == 1
        assert diag.excluded_by_duration == 1
        assert diag.excluded_by_editorial == 0
        assert diag.matched == 3
        assert "asset-1" in diag.exclusion_reasons

    # Tier: 1 | Structural invariant
    def test_diagnostics_is_frozen(self):
        """PoolDiagnostics must be immutable (frozen dataclass)."""
        diag = PoolDiagnostics(
            total_considered=0, excluded_by_type=0, excluded_by_tags=0,
            excluded_by_rating=0, excluded_by_duration=0,
            excluded_by_editorial=0, matched=0, exclusion_reasons={},
        )
        with pytest.raises(AttributeError):
            diag.matched = 99  # type: ignore[misc]


# ===========================================================================
# Empty pool diagnostics
# ===========================================================================


class TestPoolEmptyProvidesDiagnostics:
    """When a pool resolves to zero assets, diagnostics must explain why."""

    # Tier: 2 | Scheduling logic invariant
    def test_empty_pool_diagnostics_nonzero_total(self):
        """Pool matching zero assets must still report total_considered > 0
        (assets were evaluated, they just all failed).
        """
        resolver = _make_resolver()
        match = resolver._pools["nonexistent"]["match"]
        matched, diag = resolver.query_with_diagnostics(match)

        assert matched == []
        assert diag.matched == 0
        assert diag.total_considered > 0, (
            "INV-POOL-RESOLUTION-VISIBILITY-001: must report how many assets "
            "were considered before exclusion"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_empty_pool_diagnostics_sum_equals_total(self):
        """Sum of all exclusion buckets + matched must equal total_considered."""
        resolver = _make_resolver()
        match = resolver._pools["nonexistent"]["match"]
        _, diag = resolver.query_with_diagnostics(match)

        bucket_sum = (
            diag.excluded_by_type + diag.excluded_by_tags
            + diag.excluded_by_rating + diag.excluded_by_duration
            + diag.excluded_by_editorial + diag.matched
        )
        assert bucket_sum == diag.total_considered, (
            f"Bucket sum ({bucket_sum}) != total_considered ({diag.total_considered}). "
            f"Diagnostics: {diag}"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_empty_pool_exclusion_reasons_populated(self):
        """Every excluded asset must have at least one entry in exclusion_reasons."""
        resolver = _make_resolver()
        match = resolver._pools["nonexistent"]["match"]
        _, diag = resolver.query_with_diagnostics(match)

        excluded_count = diag.total_considered - diag.matched
        assert len(diag.exclusion_reasons) == excluded_count, (
            f"Expected {excluded_count} exclusion reason entries, "
            f"got {len(diag.exclusion_reasons)}"
        )
        for asset_id, reasons in diag.exclusion_reasons.items():
            assert len(reasons) >= 1, (
                f"Asset {asset_id} excluded but has no reasons"
            )


# ===========================================================================
# Missing tag diagnostics
# ===========================================================================


class TestMissingTagReported:
    """Assets excluded by missing tags must report which tags are missing."""

    # Tier: 2 | Scheduling logic invariant
    def test_missing_single_tag_reported(self):
        """missing-tag-bumper has [hbo, presentation] but pool requires [hbo, presentation, intros].
        Diagnostic must report "intros" as the missing tag.
        """
        resolver = _make_resolver()
        match = resolver._pools["intros"]["match"]
        _, diag = resolver.query_with_diagnostics(match)

        assert "missing-tag-bumper" in diag.exclusion_reasons
        reasons = diag.exclusion_reasons["missing-tag-bumper"]
        tag_reasons = [r for r in reasons if "missing required tags" in r]
        assert len(tag_reasons) >= 1, (
            f"Expected 'missing required tags' reason for missing-tag-bumper, "
            f"got: {reasons}"
        )
        # The missing tag must be "intros"
        assert "intros" in tag_reasons[0], (
            f"Expected 'intros' in tag reason, got: {tag_reasons[0]}"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_all_tags_missing_reported(self):
        """no-tags-bumper has zero tags. All required tags must appear as missing."""
        resolver = _make_resolver()
        match = resolver._pools["intros"]["match"]
        _, diag = resolver.query_with_diagnostics(match)

        assert "no-tags-bumper" in diag.exclusion_reasons
        reasons = diag.exclusion_reasons["no-tags-bumper"]
        tag_reasons = [r for r in reasons if "missing required tags" in r]
        assert len(tag_reasons) >= 1

        # All three required tags must be named
        reason_text = tag_reasons[0]
        for required_tag in ("hbo", "intros", "presentation"):
            assert required_tag in reason_text, (
                f"Expected '{required_tag}' in reason, got: {reason_text}"
            )

    # Tier: 2 | Scheduling logic invariant
    def test_excluded_by_tags_count(self):
        """Diagnostics must count tag-excluded assets in excluded_by_tags bucket."""
        resolver = _make_resolver()
        match = resolver._pools["intros"]["match"]
        _, diag = resolver.query_with_diagnostics(match)

        # missing-tag-bumper and no-tags-bumper are type=bumper but fail tags
        # (wrong-type-promo fails type first, so it goes to excluded_by_type)
        assert diag.excluded_by_tags >= 2, (
            f"Expected >=2 excluded_by_tags, got {diag.excluded_by_tags}"
        )


# ===========================================================================
# Missing editorial field diagnostics
# ===========================================================================


class TestMissingEditorialReported:
    """Assets excluded by missing editorial fields (interstitial_type, series_title)
    must report the specific missing field.
    """

    # Tier: 2 | Scheduling logic invariant
    def test_missing_interstitial_type_via_type_mismatch(self):
        """In the StubAssetResolver, interstitial_type is encoded as the 'type' field.
        A promo in a bumper pool is a type mismatch — the diagnostic must say so.

        In production (CatalogAssetResolver), interstitial_type from editorial metadata
        determines the detected_type. Missing interstitial_type on an interstitial
        asset causes it to be typed as 'episode' or 'movie' instead of the expected
        'bumper'/'promo'/'station_id' — which manifests as a type mismatch.
        """
        resolver = _make_resolver()
        match = resolver._pools["intros"]["match"]
        _, diag = resolver.query_with_diagnostics(match)

        # wrong-type-promo has type=promo, pool wants type=bumper
        assert "wrong-type-promo" in diag.exclusion_reasons
        reasons = diag.exclusion_reasons["wrong-type-promo"]
        type_reasons = [r for r in reasons if "type mismatch" in r]
        assert len(type_reasons) >= 1, (
            f"Expected 'type mismatch' reason for wrong-type-promo, got: {reasons}"
        )
        assert "'bumper'" in type_reasons[0] and "'promo'" in type_reasons[0], (
            f"Type mismatch must name both expected and actual types: {type_reasons[0]}"
        )


# ===========================================================================
# Wrong type diagnostics
# ===========================================================================


class TestWrongTypeReported:
    """Assets excluded by type mismatch must report expected vs actual type."""

    # Tier: 2 | Scheduling logic invariant
    def test_type_mismatch_in_exclusion_reasons(self):
        """wrong-type-promo is type=promo but pool expects type=bumper."""
        resolver = _make_resolver()
        match = resolver._pools["intros"]["match"]
        _, diag = resolver.query_with_diagnostics(match)

        assert diag.excluded_by_type >= 1
        assert "wrong-type-promo" in diag.exclusion_reasons
        reasons = diag.exclusion_reasons["wrong-type-promo"]
        assert any("type mismatch" in r for r in reasons)

    # Tier: 2 | Scheduling logic invariant
    def test_movies_excluded_from_bumper_pool(self):
        """Movies must be excluded from the intros pool (type=bumper)."""
        resolver = _make_resolver()
        match = resolver._pools["intros"]["match"]
        _, diag = resolver.query_with_diagnostics(match)

        assert "normal-movie" in diag.exclusion_reasons
        reasons = diag.exclusion_reasons["normal-movie"]
        assert any("type mismatch" in r for r in reasons)


# ===========================================================================
# Duration filter diagnostics
# ===========================================================================


class TestDurationFilterReported:
    """Assets excluded by duration bounds must report the specific violation."""

    # Tier: 2 | Scheduling logic invariant
    def test_duration_too_long_reported(self):
        """long-movie (12000s) exceeds short_pg_movies max (7200s)."""
        resolver = _make_resolver()
        match = resolver._pools["short_pg_movies"]["match"]
        _, diag = resolver.query_with_diagnostics(match)

        assert "long-movie" in diag.exclusion_reasons
        reasons = diag.exclusion_reasons["long-movie"]
        dur_reasons = [r for r in reasons if "duration too long" in r]
        assert len(dur_reasons) >= 1, (
            f"Expected 'duration too long' reason, got: {reasons}"
        )
        assert "12000" in dur_reasons[0] and "7200" in dur_reasons[0], (
            f"Duration reason must name actual and limit: {dur_reasons[0]}"
        )


# ===========================================================================
# Rating filter diagnostics
# ===========================================================================


class TestRatingFilterReported:
    """Assets excluded by rating filter must report the specific violation."""

    # Tier: 2 | Scheduling logic invariant
    def test_wrong_rating_reported(self):
        """wrong-rating-movie (R) excluded from short_pg_movies (PG/PG-13 only)."""
        resolver = _make_resolver()
        match = resolver._pools["short_pg_movies"]["match"]
        _, diag = resolver.query_with_diagnostics(match)

        assert "wrong-rating-movie" in diag.exclusion_reasons
        reasons = diag.exclusion_reasons["wrong-rating-movie"]
        rating_reasons = [r for r in reasons if "rating excluded" in r]
        assert len(rating_reasons) >= 1, (
            f"Expected 'rating excluded' reason, got: {reasons}"
        )


# ===========================================================================
# Matched assets pass through
# ===========================================================================


class TestMatchedAssetsCorrect:
    """Diagnostics must not interfere with correct match results."""

    # Tier: 1 | Structural invariant
    def test_matched_ids_identical_to_query(self):
        """query_with_diagnostics returns the same matched IDs as query."""
        resolver = _make_resolver()
        match = resolver._pools["intros"]["match"]

        regular_result = resolver.query(match)
        diagnostic_result, diag = resolver.query_with_diagnostics(match)

        assert diagnostic_result == regular_result, (
            f"query_with_diagnostics must return same results as query. "
            f"query={regular_result}, diagnostic={diagnostic_result}"
        )
        assert diag.matched == len(regular_result)

    # Tier: 1 | Structural invariant
    def test_valid_assets_not_in_exclusion_reasons(self):
        """Matched assets must not appear in exclusion_reasons."""
        resolver = _make_resolver()
        match = resolver._pools["intros"]["match"]
        matched, diag = resolver.query_with_diagnostics(match)

        for asset_id in matched:
            assert asset_id not in diag.exclusion_reasons, (
                f"Matched asset {asset_id} must not appear in exclusion_reasons"
            )

    # Tier: 1 | Structural invariant
    def test_accounting_identity(self):
        """matched + sum(excluded buckets) must equal total_considered."""
        resolver = _make_resolver()
        for pool_name in ("intros", "short_pg_movies", "nonexistent"):
            match = resolver._pools[pool_name]["match"]
            _, diag = resolver.query_with_diagnostics(match)

            bucket_sum = (
                diag.excluded_by_type + diag.excluded_by_tags
                + diag.excluded_by_rating + diag.excluded_by_duration
                + diag.excluded_by_editorial + diag.matched
            )
            assert bucket_sum == diag.total_considered, (
                f"Pool '{pool_name}': bucket sum ({bucket_sum}) != "
                f"total ({diag.total_considered}). Diag: {diag}"
            )


# ===========================================================================
# Multi-filter exclusion
# ===========================================================================


class TestMultiFilterExclusion:
    """Assets failing multiple filters must report all applicable reasons."""

    # Tier: 2 | Scheduling logic invariant
    def test_asset_failing_type_and_tags(self):
        """An asset failing both type AND tags should have reasons for both,
        but count in the primary bucket (type) for the summary.
        """
        resolver = StubAssetResolver()
        resolver.add("double-fail", AssetMetadata(
            type="promo",  # wrong type
            duration_sec=10,
            title="Double Fail",
            tags=("wrong",),  # wrong tags
        ))
        resolver.register_pools({
            "strict": {"match": {"type": "bumper", "tags": ["hbo", "intros"]}},
        })

        _, diag = resolver.query_with_diagnostics(
            resolver._pools["strict"]["match"]
        )

        assert "double-fail" in diag.exclusion_reasons
        reasons = diag.exclusion_reasons["double-fail"]
        assert len(reasons) >= 2, (
            f"Asset failing type AND tags should have >=2 reasons, got: {reasons}"
        )
        assert any("type mismatch" in r for r in reasons)
        assert any("missing required tags" in r for r in reasons)
