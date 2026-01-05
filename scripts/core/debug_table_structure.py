#!/usr/bin/env python3
"""Debug table structure to see what's actually in the database."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, inspect, text
from src.retrovue.infra.settings import settings

engine = create_engine(settings.database_url)
inspector = inspect(engine)

print(f"Database: {settings.database_url.split('@')[1] if '@' in settings.database_url else 'unknown'}\n")

with engine.connect() as conn:
    # List all tables
    tables = inspector.get_table_names()
    print("All tables containing 'template_block':")
    for t in tables:
        if 'template_block' in t.lower():
            print(f"  - {t}")
    
    print("\n" + "="*60)
    
    # Check schedule_template_blocks
    if "schedule_template_blocks" in tables:
        print("\nschedule_template_blocks columns:")
        columns = inspector.get_columns("schedule_template_blocks")
        for col in columns:
            print(f"  - {col['name']}: {col['type']}")
        
        # Count rows
        result = conn.execute(text("SELECT COUNT(*) FROM schedule_template_blocks"))
        count = result.scalar()
        print(f"\nRow count: {count}")
    else:
        print("\nschedule_template_blocks does NOT exist")
    
    # Check schedule_template_blocks_new
    if "schedule_template_blocks_new" in tables:
        print("\nschedule_template_blocks_new columns:")
        columns = inspector.get_columns("schedule_template_blocks_new")
        for col in columns:
            print(f"  - {col['name']}: {col['type']}")
        
        result = conn.execute(text("SELECT COUNT(*) FROM schedule_template_blocks_new"))
        count = result.scalar()
        print(f"\nRow count: {count}")
    
    # Check instances table
    if "schedule_template_block_instances" in tables:
        print("\nschedule_template_block_instances exists")
        result = conn.execute(text("SELECT COUNT(*) FROM schedule_template_block_instances"))
        count = result.scalar()
        print(f"Row count: {count}")

