#!/usr/bin/env python3
"""
Analyze PostgreSQL database to find tables that aren't being used in the codebase.

This script:
1. Connects to the database and lists all tables
2. Compares with SQLAlchemy models defined in entities.py
3. Searches the codebase for references to each table
4. Reports which tables appear to be unused
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from retrovue.infra.db import get_engine
from retrovue.infra.settings import settings
from retrovue.domain import entities


def get_all_tables_from_db(engine: Engine) -> set[str]:
    """Query PostgreSQL to get all table names."""
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """)
        )
        return {row[0] for row in result}


def get_tables_from_models() -> set[str]:
    """Get table names from SQLAlchemy models."""
    tables = set()
    for name in dir(entities):
        obj = getattr(entities, name)
        if hasattr(obj, "__tablename__"):
            tables.add(obj.__tablename__)
    return tables


def search_codebase_for_table_references(table_name: str) -> list[str]:
    """Search codebase for references to a table name."""
    references = []
    project_root = Path(__file__).parent.parent
    
    # Search patterns to look for
    patterns = [
        f'"{table_name}"',  # SQL string literals
        f"'{table_name}'",  # SQL string literals (single quotes)
        f"__tablename__ = \"{table_name}\"",  # SQLAlchemy model definitions
        f"__tablename__ = '{table_name}'",  # SQLAlchemy model definitions
        f".{table_name}",  # Attribute access
        f"FROM {table_name}",  # SQL FROM clauses
        f"JOIN {table_name}",  # SQL JOIN clauses
        f"INTO {table_name}",  # SQL INSERT INTO
    ]
    
    # Directories to search
    search_dirs = [
        project_root / "src",
        project_root / "tests",
        project_root / "scripts",
        project_root / "alembic",
    ]
    
    # File extensions to search
    extensions = {".py", ".sql"}
    
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for file_path in search_dir.rglob("*"):
            if file_path.suffix not in extensions:
                continue
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                for pattern in patterns:
                    if pattern.lower() in content.lower():
                        references.append(str(file_path.relative_to(project_root)))
                        break
            except Exception:
                pass
    
    return references


def main():
    """Main analysis function."""
    print("Analyzing database tables for unused tables...\n")
    
    # Get database URL
    db_url = settings.database_url
    print(f"Connecting to database: {db_url.split('@')[-1] if '@' in db_url else db_url}\n")
    
    # Connect to database
    engine = get_engine()
    
    # Get all tables from database
    db_tables = get_all_tables_from_db(engine)
    print(f"[OK] Found {len(db_tables)} tables in database")
    print(f"   Tables: {', '.join(sorted(db_tables))}\n")
    
    # Get tables from models
    model_tables = get_tables_from_models()
    print(f"[OK] Found {len(model_tables)} tables defined in SQLAlchemy models")
    print(f"   Tables: {', '.join(sorted(model_tables))}\n")
    
    # Find tables in DB but not in models
    db_only = db_tables - model_tables
    # Find tables in models but not in DB
    model_only = model_tables - db_tables
    
    # Analyze usage for each table
    print("Searching codebase for table references...\n")
    
    all_tables = db_tables | model_tables
    table_usage = {}
    
    for table in sorted(all_tables):
        refs = search_codebase_for_table_references(table)
        table_usage[table] = refs
        if refs:
            print(f"  [OK] {table}: {len(refs)} reference(s)")
        else:
            print(f"  [WARN] {table}: NO REFERENCES FOUND")
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    # Tables in DB but not in models
    if db_only:
        print(f"\n[WARN] Tables in database but NOT in SQLAlchemy models ({len(db_only)}):")
        for table in sorted(db_only):
            refs = table_usage.get(table, [])
            if refs:
                print(f"   - {table} (referenced in: {', '.join(refs[:3])})")
            else:
                print(f"   - {table} (NO REFERENCES)")
    
    # Tables in models but not in DB
    if model_only:
        print(f"\n[WARN] Tables in SQLAlchemy models but NOT in database ({len(model_only)}):")
        for table in sorted(model_only):
            refs = table_usage.get(table, [])
            if refs:
                print(f"   - {table} (referenced in: {', '.join(refs[:3])})")
            else:
                print(f"   - {table} (NO REFERENCES)")
    
    # Tables with no references
    unused = [t for t, refs in table_usage.items() if not refs]
    if unused:
        print(f"\n[UNUSED] Tables with NO codebase references ({len(unused)}):")
        for table in sorted(unused):
            in_db = "YES" if table in db_tables else "NO"
            in_model = "YES" if table in model_tables else "NO"
            print(f"   - {table} [DB: {in_db}, Model: {in_model}]")
    else:
        print("\n[OK] All tables have at least one reference in the codebase")
    
    print("\n" + "=" * 80)
    print("Note: This analysis searches for string patterns. Some tables may be")
    print("referenced dynamically or via SQLAlchemy relationships.")
    print("=" * 80)


if __name__ == "__main__":
    main()

