#!/usr/bin/env python3
"""Test database connection and run migration if needed."""

from retrovue.infra.settings import settings
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

def test_connection(db_url: str, db_name: str) -> bool:
    """Test connection to a database."""
    try:
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar().split(" on ")[0]
            print(f"{db_name} connection: SUCCESS")
            print(f"  PostgreSQL version: {version}")
            return True
    except OperationalError as e:
        print(f"{db_name} connection: FAILED")
        print(f"  Error: {e}")
        return False

if __name__ == "__main__":
    print("Testing database connections...\n")
    
    # Test production database
    prod_ok = test_connection(settings.database_url, "Production Database")
    print()
    
    # Test test database
    if settings.test_database_url:
        test_ok = test_connection(settings.test_database_url, "Test Database")
    else:
        print("Test Database: TEST_DATABASE_URL not configured")
        test_ok = False

