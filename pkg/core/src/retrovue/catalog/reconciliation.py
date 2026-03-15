"""
Reconciliation: compare discovered locators with catalog state and determine outcomes.

Implements the compare and determine-outcome steps of CatalogReconciliationContract.
Contract: docs/contracts/core/CatalogReconciliationContract_v0.1.md
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any

from ..infra.canonical import canonical_hash

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ..domain.entities import Asset

from .discovery import DiscoveredLocator

__all__ = [
    "ReconciliationOutcome",
    "load_catalog_state_for_collection",
    "determine_reconciliation_outcomes",
]


class ReconciliationOutcome(str, Enum):
    """Outcome for one discovered locator vs catalog. See CatalogReconciliationContract."""

    create = "create"
    update = "update"
    no_action = "no_action"
    mark_unavailable = "mark_unavailable"


def load_catalog_state_for_collection(
    db: Session,
    collection_uuid: Any,
) -> dict[str, Asset]:
    """
    Load current catalog state for a collection: canonical_key_hash -> Asset.

    Includes only non-deleted assets (is_deleted=False). Used in the compare step.
    Uses query API; if db has no .query (e.g. minimal test mocks), returns {}.
    """
    from ..domain.entities import Asset

    try:
        q = getattr(db, "query", None)
        if q is None:
            return {}
        rows = (
            db.query(Asset)
            .filter(
                Asset.collection_uuid == collection_uuid,
                Asset.is_deleted == False,  # noqa: E712
            )
            .all()
        )
        return {row.canonical_key_hash: row for row in rows}
    except AttributeError:
        return {}


def _fingerprint_matches(discovered: DiscoveredLocator, asset: Asset) -> bool:
    """True if asset fingerprint matches discovered fingerprint (or no fingerprint to compare)."""
    if not discovered.fingerprint:
        return True
    if discovered.fingerprint.size is not None and getattr(asset, "file_size", None) != discovered.fingerprint.size:
        return False
    if discovered.fingerprint.mtime is not None and getattr(asset, "file_mtime", None) != discovered.fingerprint.mtime:
        return False
    return True


def determine_reconciliation_outcomes(
    discovered_locators: list[DiscoveredLocator],
    catalog_state: dict[str, Asset],
    *,
    collection: Any = None,
    enable_fingerprint_updates: bool = False,
    full_collection_scope: bool = True,
) -> list[tuple[DiscoveredLocator | None, ReconciliationOutcome, Asset | None]]:
    """
    Determine outcome per discovered locator; add mark_unavailable for catalog-only.

    For each discovered locator: hash locator -> if not in catalog_state -> create;
    if in catalog_state and enable_fingerprint_updates is False -> no_action;
    if in catalog_state and enable_fingerprint_updates is True and fingerprint differs -> update,
    else no_action. When full_collection_scope is True, for each asset in catalog_state
    not seen in discovered set, add (None, mark_unavailable, asset).
    """
    result: list[tuple[DiscoveredLocator | None, ReconciliationOutcome, Asset | None]] = []
    seen_hashes: set[str] = set()

    for loc in discovered_locators:
        key_hash = canonical_hash(loc.locator)
        seen_hashes.add(key_hash)
        existing = catalog_state.get(key_hash)
        if existing is None:
            result.append((loc, ReconciliationOutcome.create, None))
            continue
        if not enable_fingerprint_updates:
            result.append((loc, ReconciliationOutcome.no_action, existing))
            continue
        if _fingerprint_matches(loc, existing):
            result.append((loc, ReconciliationOutcome.no_action, existing))
        else:
            result.append((loc, ReconciliationOutcome.update, existing))

    if full_collection_scope:
        for key_hash, asset in catalog_state.items():
            if key_hash not in seen_hashes:
                result.append((None, ReconciliationOutcome.mark_unavailable, asset))

    return result
