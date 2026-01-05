"""
This is the canonical Unit of Work boundary for RetroVue. All transactional changes must go through this.

Do not open ad hoc sessions elsewhere.

This module provides the single source of truth for database session management across
the entire RetroVue system, ensuring consistent transaction semantics for both CLI
operations and API requests.
"""

from __future__ import annotations

import contextlib
from collections.abc import Generator

from sqlalchemy.orm import Session

from .db import SessionLocal


@contextlib.contextmanager
def session() -> Generator[Session, None, None]:
    """
    Database session context manager for CLI operations and batch jobs.

    Provides Unit of Work semantics:
    - Opens a DB session
    - Yields it for use
    - On success: commits the transaction
    - On exception: rolls back and re-raises the exception
    - Always closes the session

    Usage:
        with session() as db:
            # perform database operations
            db.add(some_object)
            # transaction will be committed automatically on success
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency generator for database sessions.

    Provides the same Unit of Work semantics as session() but as a generator
    for use with FastAPI's dependency injection system.

    Usage in FastAPI endpoints:
        @app.get("/items/")
        def read_items(db: Session = Depends(get_db)):
            # perform database operations
            # transaction will be committed automatically on success
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
