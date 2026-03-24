from __future__ import annotations

from sqlalchemy.orm import Session

from retrovue.domain.entities import (
    Asset,
    AssetEditorial,
    AssetProbed,
    AssetRelationships,
    AssetSidecar,
    AssetStationOps,
)


def persist_asset_metadata(
    db: Session,
    asset: Asset,
    *,
    editorial: dict | None = None,
    probed: dict | None = None,
    station_ops: dict | None = None,
    relationships: dict | None = None,
    sidecar: dict | None = None,
) -> None:
    # Editorial — INV-ASSET-INTERSTITIAL-TYPE-PERSISTED-001: merge with
    # existing payload so that fields set by earlier enrichers (e.g.
    # interstitial_type) are not silently dropped by subsequent callers
    # that provide a partial dict.
    if editorial:
        ed_obj = db.get(AssetEditorial, asset.uuid)
        if ed_obj is None:
            ed_obj = AssetEditorial(asset_uuid=asset.uuid, payload=editorial)
        else:
            merged = dict(ed_obj.payload or {})
            merged.update(editorial)
            ed_obj.payload = merged
        db.add(ed_obj)

    # Probed — same merge pattern to protect fields set by prior enrichers.
    if probed:
        pr_obj = db.get(AssetProbed, asset.uuid)
        if pr_obj is None:
            pr_obj = AssetProbed(asset_uuid=asset.uuid, payload=probed)
        else:
            merged = dict(pr_obj.payload or {})
            merged.update(probed)
            pr_obj.payload = merged
        db.add(pr_obj)

    # Station ops
    if station_ops:
        st_obj = db.get(AssetStationOps, asset.uuid)
        if st_obj is None:
            st_obj = AssetStationOps(asset_uuid=asset.uuid, payload=station_ops)
        else:
            merged = dict(st_obj.payload or {})
            merged.update(station_ops)
            st_obj.payload = merged
        db.add(st_obj)

    # Relationships
    if relationships:
        rel_obj = db.get(AssetRelationships, asset.uuid)
        if rel_obj is None:
            rel_obj = AssetRelationships(asset_uuid=asset.uuid, payload=relationships)
        else:
            merged = dict(rel_obj.payload or {})
            merged.update(relationships)
            rel_obj.payload = merged
        db.add(rel_obj)

    # Sidecar
    if sidecar:
        sc_obj = db.get(AssetSidecar, asset.uuid)
        if sc_obj is None:
            sc_obj = AssetSidecar(asset_uuid=asset.uuid, payload=sidecar)
        else:
            merged = dict(sc_obj.payload or {})
            merged.update(sidecar)
            sc_obj.payload = merged
        db.add(sc_obj)


