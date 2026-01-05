#!/usr/bin/env python3
"""Verify actual table structure vs what migration sees."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from src.retrovue.infra.settings import settings

print(f"Connecting to: {settings.database_url.split('@')[1] if '@' in settings.database_url else settings.database_url}\n")

engine = create_engine(settings.database_url)
with engine.connect() as conn:
    result = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'schedule_template_blocks' AND table_schema = 'public' ORDER BY column_name"
        )
    )
    cols = [r[0] for r in result]
    print("Actual columns in database:")
    for col in cols:
        print(f"  - {col}")
    
    has_template_id = "template_id" in cols
    has_name = "name" in cols
    
    print(f"\nHas template_id (old): {has_template_id}")
    print(f"Has name (new): {has_name}")
    
    if has_template_id and not has_name:
        print("\n*** TABLE NEEDS TRANSFORMATION ***")
    elif has_name and not has_template_id:
        print("\n*** TABLE HAS NEW STRUCTURE ***")
    else:
        print("\n*** UNEXPECTED STATE ***")

