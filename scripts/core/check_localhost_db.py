#!/usr/bin/env python3
"""Check the localhost database structure."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text

db_url = os.getenv("RETROVUE_DATABASE_URL", "postgresql://retrovue_user:retrovue_pass@localhost:5432/retrovue")
print(f"Checking database: {db_url.split('@')[1] if '@' in db_url else 'unknown'}\n")

engine = create_engine(db_url)
with engine.connect() as conn:
    result = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'schedule_template_blocks' AND table_schema = 'public' ORDER BY column_name"
        )
    )
    cols = [r[0] for r in result]
    print("Columns in schedule_template_blocks:")
    for col in cols:
        print(f"  - {col}")
    
    has_old = "template_id" in cols and "start_time" in cols
    has_new = "name" in cols and "template_id" not in cols
    
    print(f"\nHas old structure: {has_old}")
    print(f"Has new structure: {has_new}")

