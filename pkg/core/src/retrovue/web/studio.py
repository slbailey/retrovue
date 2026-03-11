"""RetroVue Studio — Interstitial Tagging UI"""
from __future__ import annotations
import json, math, sqlite3 as sq
from pathlib import Path
from typing import Optional, Any
from uuid import UUID
import psycopg
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

router = APIRouter(prefix="/studio", tags=["studio"])
SQLITE = "/opt/retrovue/data/retrovue.db"
TPL    = "/opt/retrovue/pkg/core/templates/studio/studio.html"
PGDSN  = "host=192.168.1.50 dbname=retrovue user=retrovue password=mb061792"
INTERSTITIAL_COLS = ["commercials","promos","bumpers","psas","station_ids","trailers","teasers","shortform","oddities"]

def _sq():
    c = sq.connect(SQLITE); c.row_factory = sq.Row; return c

def _pg(): return psycopg.connect(PGDSN)

class _Enc(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, UUID): return str(o)
        return super().default(o)

def jr(data, status=200):
    return Response(json.dumps(data, cls=_Enc), media_type="application/json", status_code=status)

@router.get("/", response_class=HTMLResponse)
def studio_index():
    return HTMLResponse(Path(TPL).read_text())

@router.get("/api/assets")
def list_assets(
    search: Optional[str] = Query(default=None),
    untagged_only: bool = Query(default=False),
    collection: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=100, ge=10, le=500),
):
    offset = (page - 1) * per_page
    where_parts = ["c.name = ANY(%s)", "a.is_deleted = false"]
    params: list = [INTERSTITIAL_COLS]
    if search:
        where_parts.append("(a.uri ILIKE %s OR ae.payload->>'title' ILIKE %s)")
        params += [f"%{search}%", f"%{search}%"]
    if collection:
        where_parts.append("c.name = %s")
        params.append(collection)
    if untagged_only:
        where_parts.append("NOT EXISTS (SELECT 1 FROM asset_tags at2 WHERE at2.asset_uuid = a.uuid)")
    wsql = "WHERE " + " AND ".join(where_parts)

    with _pg() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM assets a JOIN collections c ON c.uuid=a.collection_uuid LEFT JOIN asset_editorial ae ON ae.asset_uuid=a.uuid {wsql}", params)
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM assets a JOIN collections c ON c.uuid=a.collection_uuid WHERE c.name=ANY(%s) AND NOT EXISTS(SELECT 1 FROM asset_tags at2 WHERE at2.asset_uuid=a.uuid)", [INTERSTITIAL_COLS])
            untagged = cur.fetchone()[0]
            cur.execute(f"SELECT a.uuid, a.uri, a.duration_ms, c.name, ae.payload FROM assets a JOIN collections c ON c.uuid=a.collection_uuid LEFT JOIN asset_editorial ae ON ae.asset_uuid=a.uuid {wsql} ORDER BY c.name, a.uri LIMIT %s OFFSET %s", params + [per_page, offset])
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
    return jr({"assets": out, "total": total, "page": page, "per_page": per_page,
               "pages": max(1, math.ceil(total/per_page)), "untagged_count": untagged,
               "collections": INTERSTITIAL_COLS})

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
    tag_str = f"{body.category.upper()}:{body.tag.lower()}"
    with _pg() as conn:
        with conn.cursor() as cur:
            for aid in body.asset_ids:
                cur.execute("INSERT INTO asset_tags(asset_uuid,tag,source) VALUES(%s,%s,'operator') ON CONFLICT DO NOTHING", (aid, tag_str))
        conn.commit()
    return jr({"ok": True, "applied": len(body.asset_ids)})

@router.delete("/api/assets/tags")
def remove_tags(body: ApplyTags):
    tag_str = f"{body.category.upper()}:{body.tag.lower()}"
    raw_str = body.tag.lower()
    with _pg() as conn:
        with conn.cursor() as cur:
            for aid in body.asset_ids:
                # Match both namespaced (CATEGORY:tag) and raw tags
                cur.execute("DELETE FROM asset_tags WHERE asset_uuid=%s AND tag = ANY(%s)", (aid, [tag_str, raw_str]))
        conn.commit()
    return jr({"ok": True})
