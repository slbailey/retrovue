"""RetroVue Studio — Interstitial Tagging UI + Tag Management API"""
from __future__ import annotations
import json, math, os, sqlite3 as sq
from pathlib import Path
from typing import Optional, Any
from uuid import UUID
import yaml
import psycopg
from fastapi import APIRouter, Query, Body
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from retrovue.domain.tag_normalization import canonicalize_tag

router = APIRouter(prefix="/studio", tags=["studio"])
SQLITE = "/opt/retrovue/data/retrovue.db"
TPL    = "/opt/retrovue/pkg/core/templates/studio/studio.html"
PGDSN  = os.environ.get("PGDSN", "host=192.168.1.50 dbname=retrovue user=retrovue")
CHANNEL_CONFIG_DIR = os.environ.get("RETROVUE_CHANNEL_CONFIG_DIR", "/opt/retrovue/config/channels")
INTERSTITIAL_COLS = ["commercials","promos","bumpers","psas","station_ids","trailers","teasers","shortform","oddities"]

def _sq():
    c = sq.connect(SQLITE); c.row_factory = sq.Row; return c

def _pg(): return psycopg.connect(PGDSN)

class _Enc(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, UUID): return str(o)
        return super().default(o)

def jr(data, status=200):
    return Response(json.dumps(data, cls=_Enc), media_type="application/json", status_code=status,
                    headers={"Deprecated": "true"})

@router.get("/", response_class=HTMLResponse)
def studio_index():
    return HTMLResponse(Path(TPL).read_text(), headers={"Deprecated": "true"})

def _build_assets_query(
    scope: Optional[str] = None,
    search: Optional[str] = None,
    collection: Optional[str] = None,
    untagged_only: bool = False,
) -> tuple[list[str], list]:
    """Build WHERE clause parts and params for the assets query.

    scope: 'all' (no container filter), 'interstitials' (INTERSTITIAL_COLS filter),
           or a specific collection name. Default is 'all'.
    """
    where_parts: list[str] = ["a.is_deleted = false"]
    params: list = []
    effective_scope = scope or "all"
    if effective_scope == "interstitials":
        where_parts.append("c.name = ANY(%s)")
        params.append(INTERSTITIAL_COLS)
    elif effective_scope != "all":
        where_parts.append("c.name = %s")
        params.append(effective_scope)
    if search:
        where_parts.append("(a.uri ILIKE %s OR ae.payload->>'title' ILIKE %s)")
        params += [f"%{search}%", f"%{search}%"]
    if collection:
        where_parts.append("c.name = %s")
        params.append(collection)
    if untagged_only:
        where_parts.append("NOT EXISTS (SELECT 1 FROM asset_tags at2 WHERE at2.asset_uuid = a.uuid)")
    return where_parts, params


@router.get("/api/assets")
def list_assets(
    search: Optional[str] = Query(default=None),
    untagged_only: bool = Query(default=False),
    collection: Optional[str] = Query(default=None),
    scope: Optional[str] = Query(default="all"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=100, ge=10, le=500),
):
    offset = (page - 1) * per_page
    where_parts, params = _build_assets_query(scope=scope, search=search, collection=collection, untagged_only=untagged_only)
    wsql = "WHERE " + " AND ".join(where_parts)

    with _pg() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM assets a JOIN containers c ON c.uuid=a.container_id LEFT JOIN asset_editorial ae ON ae.asset_uuid=a.uuid {wsql}", params)
            total = cur.fetchone()[0]
            untagged_w, untagged_p = _build_assets_query(scope=scope, untagged_only=True)
            cur.execute(f"SELECT COUNT(*) FROM assets a JOIN containers c ON c.uuid=a.container_id LEFT JOIN asset_editorial ae ON ae.asset_uuid=a.uuid WHERE {' AND '.join(untagged_w)}", untagged_p)
            untagged = cur.fetchone()[0]
            cur.execute(f"SELECT a.uuid, a.uri, a.duration_ms, c.name, ae.payload FROM assets a JOIN containers c ON c.uuid=a.container_id LEFT JOIN asset_editorial ae ON ae.asset_uuid=a.uuid {wsql} ORDER BY c.name, a.uri LIMIT %s OFFSET %s", params + [per_page, offset])
            rows = cur.fetchall()
            uuids = [str(r[0]) for r in rows]
            tmap: dict = {u: [] for u in uuids}
            if uuids:
                cur.execute("SELECT asset_uuid::text, tag FROM asset_tags WHERE asset_uuid::text = ANY(%s)", [uuids])
                for uid, tag in cur.fetchall():
                    cat, val = tag.split(":", 1) if ":" in tag else ("TAG", tag)
                    tmap[uid].append({"category": cat, "tag": val})

    out = []
    for r in rows:
        uid, uri, dur, coll, payload = str(r[0]), r[1], r[2], r[3], r[4] or {}
        p = Path(uri.replace("file://",""))
        out.append({
            "id": uid, "kind": payload.get("interstitial_type", coll),
            "title": payload.get("title", p.stem),
            "filename": p.name, "directory": coll, "directory_full": str(p.parent),
            "interstitial_category": payload.get("interstitial_category",""),
            "duration_ms": dur or 0, "file_path": uri, "tags": tmap.get(uid, []),
        })
    # Return all container names so the scope selector covers movies, TV, etc.
    with _pg() as conn2:
        with conn2.cursor() as cur2:
            cur2.execute("SELECT DISTINCT name FROM containers ORDER BY name")
            all_collections = [r[0] for r in cur2.fetchall()]

    return jr({"assets": out, "total": total, "page": page, "per_page": per_page,
               "pages": max(1, math.ceil(total/per_page)), "untagged_count": untagged,
               "collections": all_collections})

@router.get("/api/palette")
def get_palette():
    c = _sq()
    rows = c.execute("SELECT category,tag,color_bg,color_fg FROM tag_palette ORDER BY category,tag").fetchall()
    c.close()
    pal: dict = {}
    for r in rows:
        pal.setdefault(r["category"], []).append({"tag":r["tag"],"color_bg":r["color_bg"],"color_fg":r["color_fg"]})
    return jr(pal)

class NewTag(BaseModel):
    category: str; tag: str; color_bg: str = "#1a2840"; color_fg: str = "#6496d2"

class DelTag(BaseModel):
    category: str; tag: str

class ApplyTags(BaseModel):
    asset_ids: list[str]; category: str; tag: str

@router.post("/api/palette/tag")
def add_tag(body: NewTag):
    cat, tag = body.category.strip().upper(), body.tag.strip().lower()
    c = _sq(); c.execute("INSERT OR REPLACE INTO tag_palette (category,tag,color_bg,color_fg) VALUES (?,?,?,?)", (cat,tag,body.color_bg,body.color_fg)); c.commit(); c.close()
    return jr({"ok": True})

@router.delete("/api/palette/tag")
def del_tag(body: DelTag):
    c = _sq(); c.execute("DELETE FROM tag_palette WHERE category=? AND tag=?", (body.category.upper(),body.tag.lower())); c.commit(); c.close()
    return jr({"ok": True})

@router.post("/api/assets/tags")
def apply_tags(body: ApplyTags):
    canonical = canonicalize_tag(f"{body.category}:{body.tag}")
    with _pg() as conn:
        with conn.cursor() as cur:
            for aid in body.asset_ids:
                cur.execute("INSERT INTO asset_tags(asset_uuid,tag,source) VALUES(%s,%s,'operator') ON CONFLICT DO NOTHING", (aid, canonical))
        conn.commit()
    return jr({"ok": True, "applied": len(body.asset_ids)})

@router.delete("/api/assets/tags")
def remove_tags(body: ApplyTags):
    canonical = canonicalize_tag(f"{body.category}:{body.tag}")
    # Backward-compatible: match canonical, legacy colon, and raw forms
    legacy_str = f"{body.category.upper()}:{body.tag.lower()}"
    raw_str = body.tag.lower()
    with _pg() as conn:
        with conn.cursor() as cur:
            for aid in body.asset_ids:
                cur.execute("DELETE FROM asset_tags WHERE asset_uuid=%s AND tag = ANY(%s)", (aid, [canonical, legacy_str, raw_str]))
        conn.commit()
    return jr({"ok": True})


# ---------------------------------------------------------------------------
# Tag Management API — INV-TAG-RENAME-ATOMIC-001, INV-TAG-SUMMARY-COMPLETE-001
# ---------------------------------------------------------------------------

class TagRenameRequest(BaseModel):
    old_tag: str
    new_tag: str

class TagMergeRequest(BaseModel):
    source_tag: str
    target_tag: str

class TagBulkRemoveRequest(BaseModel):
    tag: str


def _build_tag_summary(pg_conn, sqlite_path: Optional[str] = None) -> dict:
    """Build tag summary with namespace grouping and orphaned palette tags."""
    namespaces: dict[str, list[dict]] = {}
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT tag, source, COUNT(*) AS cnt FROM asset_tags GROUP BY tag, source ORDER BY tag"
        )
        tag_data: dict[str, dict] = {}
        for tag, source, cnt in cur.fetchall():
            if tag not in tag_data:
                ns, val = (tag.split(".", 1) + [""])[:2] if "." in tag else ("tag", tag)
                tag_data[tag] = {
                    "name": val, "canonical": tag, "asset_count": 0,
                    "sources": {"ingest": 0, "operator": 0, "enricher": 0},
                }
            tag_data[tag]["sources"][source] = tag_data[tag]["sources"].get(source, 0) + cnt
            tag_data[tag]["asset_count"] += cnt

    for canonical, entry in tag_data.items():
        ns = canonical.split(".", 1)[0] if "." in canonical else "tag"
        namespaces.setdefault(ns, []).append(entry)

    # Orphaned palette tags
    orphaned: list[dict] = []
    db_path = sqlite_path or SQLITE
    if os.path.exists(db_path):
        assigned_values = {e["name"] for entries in namespaces.values() for e in entries}
        c = sq.connect(db_path)
        c.row_factory = sq.Row
        rows = c.execute("SELECT category, tag, color_bg, color_fg FROM tag_palette").fetchall()
        c.close()
        for r in rows:
            if r["tag"] not in assigned_values:
                orphaned.append({"category": r["category"], "tag": r["tag"],
                                 "color_bg": r["color_bg"], "color_fg": r["color_fg"]})

    return {"namespaces": namespaces, "orphaned": orphaned}


def _execute_tag_rename(pg_conn, old_canonical: str, new_canonical: str, sqlite_path: Optional[str] = None) -> dict:
    """Rename a tag across all assets in a single transaction. INV-TAG-RENAME-ATOMIC-001."""
    with pg_conn.cursor() as cur:
        # Assets that already have the new tag — these need dedup (delete old row)
        cur.execute(
            "SELECT asset_uuid FROM asset_tags WHERE tag = %s AND asset_uuid IN "
            "(SELECT asset_uuid FROM asset_tags WHERE tag = %s)",
            (old_canonical, new_canonical),
        )
        dedup_uuids = {r[0] for r in cur.fetchall()}

        # Delete old tag for assets that already have new tag
        if dedup_uuids:
            cur.execute(
                "DELETE FROM asset_tags WHERE tag = %s AND asset_uuid = ANY(%s)",
                (old_canonical, list(dedup_uuids)),
            )

        # Update remaining old→new
        cur.execute(
            "UPDATE asset_tags SET tag = %s WHERE tag = %s",
            (new_canonical, old_canonical),
        )
        updated = cur.rowcount

    pg_conn.commit()

    # Update SQLite palette
    db_path = sqlite_path or SQLITE
    if os.path.exists(db_path):
        old_ns, old_val = (old_canonical.split(".", 1) + [""])[:2] if "." in old_canonical else ("tag", old_canonical)
        new_ns, new_val = (new_canonical.split(".", 1) + [""])[:2] if "." in new_canonical else ("tag", new_canonical)
        c = sq.connect(db_path)
        c.execute("UPDATE tag_palette SET category = ?, tag = ? WHERE category = ? AND tag = ?",
                  (new_ns.upper(), new_val, old_ns.upper(), old_val))
        c.commit()
        c.close()

    return {"ok": True, "affected_assets": updated + len(dedup_uuids), "deduped": len(dedup_uuids)}


def _execute_tag_merge(pg_conn, source_canonical: str, target_canonical: str, sqlite_path: Optional[str] = None) -> dict:
    """Merge source tag into target tag. INV-TAG-RENAME-ATOMIC-001."""
    with pg_conn.cursor() as cur:
        # Find assets that have both source and target
        cur.execute(
            "SELECT asset_uuid FROM asset_tags WHERE tag = %s AND asset_uuid IN "
            "(SELECT asset_uuid FROM asset_tags WHERE tag = %s)",
            (source_canonical, target_canonical),
        )
        overlap_uuids = {r[0] for r in cur.fetchall()}

        # Delete source tag for assets that already have target
        if overlap_uuids:
            cur.execute(
                "DELETE FROM asset_tags WHERE tag = %s AND asset_uuid = ANY(%s)",
                (source_canonical, list(overlap_uuids)),
            )

        # Update remaining source→target
        cur.execute(
            "UPDATE asset_tags SET tag = %s WHERE tag = %s",
            (target_canonical, source_canonical),
        )
        moved = cur.rowcount

    pg_conn.commit()

    # Remove source from SQLite palette
    db_path = sqlite_path or SQLITE
    if os.path.exists(db_path):
        src_ns, src_val = (source_canonical.split(".", 1) + [""])[:2] if "." in source_canonical else ("tag", source_canonical)
        c = sq.connect(db_path)
        c.execute("DELETE FROM tag_palette WHERE category = ? AND tag = ?", (src_ns.upper(), src_val))
        c.commit()
        c.close()

    return {"ok": True, "affected_assets": moved + len(overlap_uuids), "already_had_target": len(overlap_uuids)}


def _execute_tag_bulk_remove(pg_conn, canonical: str) -> dict:
    """Delete a tag from all assets in a single transaction."""
    with pg_conn.cursor() as cur:
        cur.execute("DELETE FROM asset_tags WHERE tag = %s", (canonical,))
        affected = cur.rowcount
    pg_conn.commit()
    return {"ok": True, "affected_assets": affected}


def _scan_pool_references(tag_value: str, config_dir: Optional[str] = None) -> list[dict]:
    """Scan channel YAML configs for pool DSL references to a tag value."""
    chan_dir = Path(config_dir or CHANNEL_CONFIG_DIR)
    refs: list[dict] = []
    if not chan_dir.exists():
        return refs
    # Strip namespace for matching — pool DSL uses plain tag values
    plain = tag_value.split(".", 1)[1] if "." in tag_value else tag_value
    for yf in sorted(chan_dir.glob("*.yaml")):
        try:
            cfg = yaml.safe_load(yf.read_text())
        except Exception:
            continue
        if not cfg or "pools" not in cfg:
            continue
        channel = cfg.get("channel", yf.stem)
        for pool_name, pool_def in (cfg["pools"] or {}).items():
            sel = (pool_def or {}).get("select", {})
            where = (sel or {}).get("where", {})
            tags = (where or {}).get("tags", {})
            for op in ("contains_all", "contains_any", "excludes_any"):
                tag_list = tags.get(op, [])
                if plain in tag_list:
                    refs.append({"channel": channel, "pool_name": pool_name, "operator": op})
    return refs


def _build_rename_preview(pg_conn, old_canonical: str, new_canonical: str, config_dir: Optional[str] = None) -> dict:
    """Read-only preview of a tag rename's impact."""
    with pg_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM asset_tags WHERE tag = %s", (old_canonical,))
        affected = cur.fetchone()[0]
    pool_refs = _scan_pool_references(old_canonical, config_dir)
    return {"affected_assets": affected, "pool_references": pool_refs}


# --- HTTP Endpoints ---

@router.get("/api/tags/summary")
def tag_summary():
    with _pg() as conn:
        result = _build_tag_summary(conn)
    return jr(result)


@router.post("/api/tags/rename")
def tag_rename(body: TagRenameRequest):
    old_c = canonicalize_tag(body.old_tag)
    new_c = canonicalize_tag(body.new_tag)
    with _pg() as conn:
        result = _execute_tag_rename(conn, old_c, new_c)
    return jr(result)


@router.post("/api/tags/merge")
def tag_merge(body: TagMergeRequest):
    src_c = canonicalize_tag(body.source_tag)
    tgt_c = canonicalize_tag(body.target_tag)
    with _pg() as conn:
        result = _execute_tag_merge(conn, src_c, tgt_c)
    return jr(result)


@router.post("/api/tags/bulk-remove")
def tag_bulk_remove(body: TagBulkRemoveRequest):
    canonical = canonicalize_tag(body.tag)
    with _pg() as conn:
        result = _execute_tag_bulk_remove(conn, canonical)
    return jr(result)


@router.post("/api/tags/rename/preview")
def tag_rename_preview(body: TagRenameRequest):
    old_c = canonicalize_tag(body.old_tag)
    new_c = canonicalize_tag(body.new_tag)
    with _pg() as conn:
        result = _build_rename_preview(conn, old_c, new_c)
    return jr(result)
