"""Lightweight fake DB for contract tests.

Provides model-aware query routing so that ``db.query(Source)`` and
``db.query(Container)`` return different result sets — something
MagicMock cannot do.

Usage::

    db = FakeDB()
    db.seed(Source, [my_source])
    db.seed(Container, [c1, c2])
    db.seed(Asset, [])

    # db.query(Source).filter(...).first() → my_source
    # db.query(Container).filter(...).all() → [c1, c2]
"""

from __future__ import annotations

from typing import Any


class _MockExecuteResult:
    """Minimal result from db.execute()."""
    rowcount = 1


class _QueryChain:
    """Chainable query result supporting filter/first/all/count."""

    def __init__(self, items: list[Any]) -> None:
        self._items = list(items)

    def filter(self, *args, **kwargs) -> "_QueryChain":
        return self  # no-op filtering for contract tests

    def first(self) -> Any | None:
        return self._items[0] if self._items else None

    def all(self) -> list[Any]:
        return list(self._items)

    def count(self) -> int:
        return len(self._items)

    def one_or_none(self) -> Any | None:
        return self.first()

    def order_by(self, *args) -> "_QueryChain":
        return self


class FakeDB:
    """Deterministic, model-aware fake database session.

    Supports the subset of SQLAlchemy Session API used by CLI commands
    and ingest services: query, execute, add, flush, commit, scalar,
    begin_nested, close.
    """

    def __init__(self) -> None:
        self._stores: dict[type, list[Any]] = {}
        self.added: list[Any] = []
        self.flushed: bool = False
        self._scalar_value: Any = None

    # -- Seeding ----------------------------------------------------------

    def seed(self, model: type, items: list[Any]) -> None:
        """Pre-load items for a given model class."""
        self._stores[model] = list(items)

    # -- Query API --------------------------------------------------------

    def query(self, model: type) -> _QueryChain:
        items = self._stores.get(model, [])
        return _QueryChain(items)

    # -- Execute API (SQLAlchemy 2.0 style) --------------------------------

    def execute(self, stmt, *args, **kwargs) -> _MockExecuteResult:
        return _MockExecuteResult()

    def scalar(self, stmt=None, *args, **kwargs) -> Any:
        """Return pre-configured scalar value (default None)."""
        return self._scalar_value

    # -- Mutation API ------------------------------------------------------

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        self.flushed = True

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass

    def merge(self, obj: Any) -> Any:
        return obj

    def begin_nested(self) -> "_FakeNested":
        return _FakeNested()

    def __enter__(self) -> "FakeDB":
        return self

    def __exit__(self, *args) -> None:
        pass

    def get(self, model: type, pk: Any) -> Any | None:
        for item in self._stores.get(model, []):
            if getattr(item, "id", None) == pk or getattr(item, "uuid", None) == pk:
                return item
        return None


class _FakeNested:
    """Fake savepoint context for begin_nested()."""

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def __enter__(self) -> "_FakeNested":
        return self

    def __exit__(self, *args) -> None:
        pass
