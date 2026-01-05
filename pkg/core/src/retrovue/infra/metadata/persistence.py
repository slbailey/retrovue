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
    # Editorial
    if editorial:
        ed_obj = db.get(AssetEditorial, asset.uuid)
        if ed_obj is None:
            ed_obj = AssetEditorial(asset_uuid=asset.uuid, payload=editorial)
        else:
            ed_obj.payload = editorial
        db.add(ed_obj)

    # Probed
    if probed:
        pr_obj = db.get(AssetProbed, asset.uuid)
        if pr_obj is None:
            pr_obj = AssetProbed(asset_uuid=asset.uuid, payload=probed)
        else:
            pr_obj.payload = probed
        db.add(pr_obj)

    # Station ops
    if station_ops:
        st_obj = db.get(AssetStationOps, asset.uuid)
        if st_obj is None:
            st_obj = AssetStationOps(asset_uuid=asset.uuid, payload=station_ops)
        else:
            st_obj.payload = station_ops
        db.add(st_obj)

    # Relationships
    if relationships:
        rel_obj = db.get(AssetRelationships, asset.uuid)
        if rel_obj is None:
            rel_obj = AssetRelationships(asset_uuid=asset.uuid, payload=relationships)
        else:
            rel_obj.payload = relationships
        db.add(rel_obj)

    # Sidecar
    if sidecar:
        sc_obj = db.get(AssetSidecar, asset.uuid)
        if sc_obj is None:
            sc_obj = AssetSidecar(asset_uuid=asset.uuid, payload=sidecar)
        else:
            sc_obj.payload = sidecar
        db.add(sc_obj)


