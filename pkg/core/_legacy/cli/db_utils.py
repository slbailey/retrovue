"""
Database utilities for Retrovue CLI.

This module provides a centralized way to create SQLite connections
with proper foreign key enforcement enabled.
"""

import sqlite3


def connect(db_path: str) -> sqlite3.Connection:
    """
    Create a SQLite connection with foreign key enforcement enabled.

    Args:
        db_path: Path to the SQLite database file

    Returns:
        sqlite3.Connection: Connection with foreign keys enabled
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def connect_with_row_factory(db_path: str) -> sqlite3.Connection:
    """
    Create a SQLite connection with foreign key enforcement and row factory enabled.

    Args:
        db_path: Path to the SQLite database file

    Returns:
        sqlite3.Connection: Connection with foreign keys and row factory enabled
    """
    conn = connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
