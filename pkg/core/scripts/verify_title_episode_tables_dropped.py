#!/usr/bin/env python3
"""Verify that title/season/episode tables have been dropped."""

from retrovue.infra.db import get_engine
from sqlalchemy import text

engine = get_engine()
with engine.connect() as conn:
    result = conn.execute(
        text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE' 
            AND table_name IN ('titles', 'seasons', 'episodes', 'episode_assets')
            ORDER BY table_name
        """)
    )
    tables = [row[0] for row in result]
    
    if tables:
        print(f"WARNING: Found {len(tables)} title/episode tables still in database:")
        for table in tables:
            print(f"  - {table}")
    else:
        print("SUCCESS: All title/season/episode tables have been dropped from the database.")

