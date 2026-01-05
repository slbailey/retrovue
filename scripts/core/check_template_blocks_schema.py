#!/usr/bin/env python3
"""Check schedule_template_blocks table structure."""

import os
import sys

from sqlalchemy import create_engine, inspect, text

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.retrovue.infra.settings import settings


def main():
    """Check the table structure."""
    engine = create_engine(settings.database_url)
    inspector = inspect(engine)

    print("Checking schedule_template_blocks table structure...\n")

    # Check if table exists
    tables = inspector.get_table_names()
    if "schedule_template_blocks" not in tables:
        print("❌ Table 'schedule_template_blocks' does not exist!")
        if "schedule_template_blocks_new" in tables:
            print("⚠️  Found 'schedule_template_blocks_new' - migration may not have completed rename")
        return

    # Get columns
    columns = inspector.get_columns("schedule_template_blocks")
    column_names = [col["name"] for col in columns]

    print(f"Table 'schedule_template_blocks' exists with {len(columns)} columns:")
    for col in columns:
        print(f"  - {col['name']}: {col['type']}")

    # Check for expected structure
    expected_columns = {"id", "name", "rule_json", "created_at", "updated_at"}
    old_columns = {"id", "template_id", "start_time", "end_time", "rule_json", "created_at", "updated_at"}

    has_new_structure = expected_columns.issubset(set(column_names))
    has_old_structure = old_columns.issubset(set(column_names))

    print("\nStructure analysis:")
    if has_new_structure and not has_old_structure:
        print("✅ Table has correct NEW structure (standalone blocks)")
    elif has_old_structure and not has_new_structure:
        print("❌ Table has OLD structure (blocks belong to templates)")
        print("   Migration may have failed partway through")
    elif has_new_structure and has_old_structure:
        print("⚠️  Table has BOTH structures - inconsistent state")
    else:
        print("⚠️  Table structure doesn't match expected patterns")

    # Check for instances table
    if "schedule_template_block_instances" in tables:
        print("\n✅ 'schedule_template_block_instances' table exists")
    else:
        print("\n❌ 'schedule_template_block_instances' table missing")


if __name__ == "__main__":
    main()

