from __future__ import annotations

import json
from pathlib import Path

import pytest


def _load_example(filename: str) -> dict:
    base = Path(__file__).resolve().parents[2] / "docs" / "metadata" / "examples"
    with (base / filename).open("r", encoding="utf-8") as f:
        return json.load(f)


def _get_resolver():
    # Skip tests until resolver is implemented
    mod = pytest.importorskip("retrovue.runtime.metadata_resolver")
    resolve = getattr(mod, "resolve", None)
    if resolve is None or not callable(resolve):
        pytest.skip("retrovue.runtime.metadata_resolver.resolve not implemented yet")
    return resolve


def test_manual_sidecar_beats_plex_on_editorial():
    resolve = _get_resolver()
    data = _load_example("promo-sidecar-overrides.json")
    sources = {
        "asset_type": data["asset_type"],
        "plex": data["inputs"]["plex"],
        "sidecar": data["inputs"]["sidecar"],
    }
    resolved = resolve(sources)
    exp = data["expected"]["resolved"]

    assert resolved.get("title") == exp["title"]
    assert resolved.get("runtime_seconds") == exp["runtime_seconds"]
    # Sidecar authoritative fields must win over Plex
    assert resolved.get("air_window_start") == exp["air_window_start"]
    assert resolved.get("air_window_end") == exp["air_window_end"]


def test_probe_beats_plex_for_technical_fields():
    resolve = _get_resolver()
    data = _load_example("episode-fs-vs-plex.json")
    sources = {
        "asset_type": data["asset_type"],
        "plex": data["inputs"]["plex"],
        "filename": data["inputs"]["filename"]["parsed"],
        "probe": data["inputs"]["probe"],
    }
    resolved = resolve(sources)
    exp = data["expected"]["resolved"]

    # Plex editorial wins over filename for title, but probe must win for technicals
    assert resolved.get("title") == exp["title"]
    assert resolved.get("season_number") == exp["season_number"]
    assert resolved.get("episode_number") == exp["episode_number"]
    assert resolved.get("runtime_seconds") == exp["runtime_seconds"]
    assert resolved.get("aspect_ratio") == exp["aspect_ratio"]
    assert resolved.get("resolution") == exp["resolution"]


def test_ai_only_fills_missing_editorial_fields():
    resolve = _get_resolver()

    # Movie: genres missing → AI backfill allowed
    mov = _load_example("movie-missing-genres.json")
    sources_movie = {
        "asset_type": mov["asset_type"],
        "plex": mov["inputs"]["plex"],
        "probe": mov["inputs"]["probe"],
        "ai": mov["inputs"]["ai"],
    }
    res_movie = resolve(sources_movie)
    exp_movie = mov["expected"]["resolved"]
    assert res_movie.get("genres") == exp_movie["genres"], "AI should backfill missing genres"
    assert res_movie.get("runtime_seconds") == exp_movie["runtime_seconds"]

    # Ad: AI adds content_warnings but must not override advertiser
    ad = _load_example("ad-ai-tagging.json")
    sources_ad = {
        "asset_type": ad["asset_type"],
        "plex": ad["inputs"]["plex"],
        "ai": ad["inputs"]["ai"],
    }
    res_ad = resolve(sources_ad)
    exp_ad = ad["expected"]["resolved"]
    assert res_ad.get("content_warnings") == exp_ad["content_warnings"], (
        "AI may add content warnings"
    )
    assert res_ad.get("advertiser") == exp_ad["advertiser"], (
        "AI must not override advertiser supplied by Plex/manual"
    )



