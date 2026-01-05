#!/usr/bin/env python3
"""
Test script to verify database connection improvements.

This script tests the database connection with the new timeout settings
and retry logic to ensure the CI fixes work correctly.
"""

import os
import sys
import time

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError


def test_database_connection():
    """Test database connection with improved timeout settings."""
    
    # Use TEST_DATABASE_URL if available, otherwise use default
    db_url = os.getenv('TEST_DATABASE_URL', 'postgresql+psycopg://postgres:postgres@localhost:5432/retrovue_test')
    
    print(f"🔗 Testing database connection to: {db_url}")
    
    # Create engine with longer timeout and retry logic
    engine = create_engine(
        db_url,
        pool_pre_ping=True,
        pool_timeout=60,  # Increased timeout
        connect_args={'connect_timeout': 30}  # Connection timeout
    )
    
    # Retry connection with exponential backoff
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with engine.connect() as conn:
                # Check if database is accessible
                result = conn.execute(text('SELECT 1'))
                print(f'✅ Database connection successful (attempt {attempt + 1})')
                
                # Test a simple query
                result = conn.execute(text('SELECT version()'))
                version = result.scalar()
                print(f'📊 PostgreSQL version: {version}')
                
                return True
                
        except OperationalError as e:
            print(f'❌ Database connection failed (attempt {attempt + 1}/{max_retries}): {e}')
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff
                print(f'⏳ Waiting {wait_time} seconds before retry...')
                time.sleep(wait_time)
            else:
                print('❌ All connection attempts failed')
                return False
        except Exception as e:
            print(f'❌ Unexpected error during connection test: {e}')
            return False
    
    return False

if __name__ == "__main__":
    print("🧪 Testing database connection improvements...")
    success = test_database_connection()
    
    if success:
        print("✅ Database connection test passed!")
        sys.exit(0)
    else:
        print("❌ Database connection test failed!")
        sys.exit(1)
