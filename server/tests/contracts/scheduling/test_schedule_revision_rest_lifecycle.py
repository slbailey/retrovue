"""Contract tests for ScheduleRevision REST lifecycle (RETA-61).

Covers:
  - Draft creation via service layer
  - Publish transition (draft → active), sets activated_at
  - Atomic supersession of existing active revision on publish
  - Reject publish of non-draft revision
  - Reject publish of empty revision (0 items)
  - Active revision immutability (no mutation via REST)
  - Listing with filters (broadcast_day, status)
  - Get single revision with items
  - REST endpoint shapes via FastAPI TestClient

Contract: docs/contracts/schedule_revision_lifecycle.md
Invariants: INV-SCHEDULEREVISION-IMMUTABLE-001, INV-PERSISTENCE-GUARD-NONEMPTY-001
"""

from __future__ import annotations

from retrovue.runtime.clock import SystemClock

import uuid as uuid_mod
from datetime import date, datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from retrovue.domain.entities import (
    Channel,
    ChannelActiveRevision,
    ScheduleItem,
    ScheduleRevision,
)
from retrovue.infra import db as db_module

# ---------------------------------------------------------------------------
# Service-layer imports
# ---------------------------------------------------------------------------
from retrovue.usecases.schedule_revision_lifecycle import (
    create_draft_revision,
    get_revision,
    list_revisions,
    publish_revision,
    RevisionNotDraftError,
    RevisionEmptyError,
    RevisionNotFoundError,
    ChannelNotFoundError,
)

# ---------------------------------------------------------------------------
# REST endpoint imports
# ---------------------------------------------------------------------------
from retrovue.web.api.scheduling import router, get_db


# ---------------------------------------------------------------------------
# Fixtures — use Postgres test DB via conftest auto-patching
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    """Get a test DB session via the conftest-patched SessionLocal."""
    session = db_module.SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def channel(db: Session) -> Channel:
    """Create a test channel, cleaned up via rollback."""
    ch = Channel(
        id=uuid_mod.uuid4(),
        slug=f"test-{uuid_mod.uuid4().hex[:8]}",
        title="Test Channel",
        grid_block_minutes=30,
        kind="network",
        programming_day_start="06:00",
        block_start_offsets_minutes=[0],
    )
    db.add(ch)
    db.flush()
    return ch


@pytest.fixture()
def client(db: Session):
    """FastAPI TestClient with dependency override for db session."""
    app = FastAPI()
    app.state.clock = SystemClock()
    app.include_router(router)

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    return TestClient(app)


def _make_items(broadcast_day: date, count: int = 2) -> list[dict]:
    base = datetime(broadcast_day.year, broadcast_day.month, broadcast_day.day,
                    6, 0, 0, tzinfo=timezone.utc)
    items = []
    for i in range(count):
        items.append({
            "start_time": (base.replace(hour=6 + i)).isoformat(),
            "duration_sec": 1800,
            "content_type": "episode",
        })
    return items


# ============================================================================
# Tier 1 — Service Layer Contract Tests
# ============================================================================


class TestCreateDraftRevision:
    """Draft creation returns status='draft' with deterministic slot indices."""

    def test_creates_draft_with_items(self, db: Session, channel: Channel):
        day = date(2026, 3, 4)
        items_data = _make_items(day, count=3)

        rev = create_draft_revision(
            db,
            channel_id=channel.id,
            broadcast_day=day,
            items=items_data,
            created_by="operator",
        )

        assert rev.status == "draft"
        assert rev.channel_id == channel.id
        assert rev.broadcast_day == day
        assert rev.activated_at is None
        assert rev.created_by == "operator"
        assert len(rev.items) == 3
        assert [item.slot_index for item in rev.items] == [0, 1, 2]

    def test_rejects_empty_items(self, db: Session, channel: Channel):
        with pytest.raises(RevisionEmptyError):
            create_draft_revision(
                db,
                channel_id=channel.id,
                broadcast_day=date(2026, 3, 4),
                items=[],
                created_by="operator",
            )

    def test_rejects_unknown_channel(self, db: Session):
        with pytest.raises(ChannelNotFoundError):
            create_draft_revision(
                db,
                channel_id=uuid_mod.uuid4(),
                broadcast_day=date(2026, 3, 4),
                items=_make_items(date(2026, 3, 4)),
                created_by="operator",
            )


class TestPublishRevision:
    """Publish transitions draft → active with atomic supersession."""

    def test_publish_sets_active_and_activated_at(self, db: Session, channel: Channel):
        day = date(2026, 3, 4)
        rev = create_draft_revision(
            db, channel_id=channel.id, broadcast_day=day,
            items=_make_items(day), created_by="test",
        )
        assert rev.status == "draft"

        published = publish_revision(db, revision_id=rev.id, now=SystemClock().now_utc())

        assert published.status == "active"
        assert published.activated_at is not None

    def test_publish_supersedes_existing_active(self, db: Session, channel: Channel):
        day = date(2026, 3, 4)

        # Create and publish first revision
        rev1 = create_draft_revision(
            db, channel_id=channel.id, broadcast_day=day,
            items=_make_items(day), created_by="test",
        )
        publish_revision(db, revision_id=rev1.id, now=SystemClock().now_utc())

        # Create and publish second revision — should supersede first
        rev2 = create_draft_revision(
            db, channel_id=channel.id, broadcast_day=day,
            items=_make_items(day, count=3), created_by="test",
        )
        result = publish_revision(db, revision_id=rev2.id, now=SystemClock().now_utc())

        assert result.status == "active"

        # Refresh rev1 from DB
        db.refresh(rev1)
        assert rev1.status == "superseded"
        assert rev1.superseded_at is not None

    def test_publish_upserts_channel_active_pointer(self, db: Session, channel: Channel):
        day = date(2026, 3, 4)
        rev = create_draft_revision(
            db, channel_id=channel.id, broadcast_day=day,
            items=_make_items(day), created_by="test",
        )
        publish_revision(db, revision_id=rev.id, now=SystemClock().now_utc())

        pointer = db.query(ChannelActiveRevision).filter(
            ChannelActiveRevision.channel_id == channel.id,
            ChannelActiveRevision.broadcast_day == day,
        ).first()

        assert pointer is not None
        assert pointer.schedule_revision_id == rev.id

    def test_reject_publish_non_draft(self, db: Session, channel: Channel):
        day = date(2026, 3, 4)
        rev = create_draft_revision(
            db, channel_id=channel.id, broadcast_day=day,
            items=_make_items(day), created_by="test",
        )
        publish_revision(db, revision_id=rev.id, now=SystemClock().now_utc())

        # Already active — cannot publish again
        with pytest.raises(RevisionNotDraftError):
            publish_revision(db, revision_id=rev.id, now=SystemClock().now_utc())

    def test_reject_publish_empty_revision(self, db: Session, channel: Channel):
        """A revision that somehow has items removed cannot be published."""
        day = date(2026, 3, 4)
        rev = create_draft_revision(
            db, channel_id=channel.id, broadcast_day=day,
            items=_make_items(day), created_by="test",
        )
        # Manually remove items to simulate edge case
        for item in list(rev.items):
            db.delete(item)
        db.flush()

        with pytest.raises(RevisionEmptyError):
            publish_revision(db, revision_id=rev.id, now=SystemClock().now_utc())

    def test_reject_publish_nonexistent(self, db: Session):
        with pytest.raises(RevisionNotFoundError):
            publish_revision(db, revision_id=uuid_mod.uuid4(), now=SystemClock().now_utc())


class TestListRevisions:
    """List revisions with optional filters."""

    def test_list_all_for_channel(self, db: Session, channel: Channel):
        day = date(2026, 3, 4)
        create_draft_revision(
            db, channel_id=channel.id, broadcast_day=day,
            items=_make_items(day), created_by="test",
        )
        create_draft_revision(
            db, channel_id=channel.id, broadcast_day=date(2026, 3, 5),
            items=_make_items(date(2026, 3, 5)), created_by="test",
        )

        revisions = list_revisions(db, channel_id=channel.id)
        assert len(revisions) == 2

    def test_filter_by_broadcast_day(self, db: Session, channel: Channel):
        day1 = date(2026, 3, 4)
        day2 = date(2026, 3, 5)
        create_draft_revision(
            db, channel_id=channel.id, broadcast_day=day1,
            items=_make_items(day1), created_by="test",
        )
        create_draft_revision(
            db, channel_id=channel.id, broadcast_day=day2,
            items=_make_items(day2), created_by="test",
        )

        revisions = list_revisions(db, channel_id=channel.id, broadcast_day=day1)
        assert len(revisions) == 1
        assert revisions[0].broadcast_day == day1

    def test_filter_by_status(self, db: Session, channel: Channel):
        day = date(2026, 3, 4)
        rev = create_draft_revision(
            db, channel_id=channel.id, broadcast_day=day,
            items=_make_items(day), created_by="test",
        )
        publish_revision(db, revision_id=rev.id, now=SystemClock().now_utc())

        drafts = list_revisions(db, channel_id=channel.id, status="draft")
        assert len(drafts) == 0

        actives = list_revisions(db, channel_id=channel.id, status="active")
        assert len(actives) == 1

    def test_rejects_unknown_channel(self, db: Session):
        with pytest.raises(ChannelNotFoundError):
            list_revisions(db, channel_id=uuid_mod.uuid4())


class TestGetRevision:
    """Get single revision with items."""

    def test_get_returns_revision_with_items(self, db: Session, channel: Channel):
        day = date(2026, 3, 4)
        rev = create_draft_revision(
            db, channel_id=channel.id, broadcast_day=day,
            items=_make_items(day, count=3), created_by="test",
        )

        result = get_revision(db, revision_id=rev.id)
        assert result.id == rev.id
        assert len(result.items) == 3

    def test_get_nonexistent_raises(self, db: Session):
        with pytest.raises(RevisionNotFoundError):
            get_revision(db, revision_id=uuid_mod.uuid4())


# ============================================================================
# Tier 2 — REST Endpoint Shape Tests
# ============================================================================


class TestRevisionRESTEndpoints:
    """Verify REST endpoints exist and return correct shapes."""

    def test_create_draft_endpoint(self, client: TestClient, channel: Channel):
        resp = client.post(
            f"/api/scheduling/channels/{channel.id}/revisions",
            json={
                "broadcast_day": "2026-03-04",
                "created_by": "operator",
                "items": [
                    {
                        "start_time": "2026-03-04T06:00:00+00:00",
                        "duration_sec": 1800,
                        "content_type": "episode",
                    }
                ],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "draft"
        assert len(data["items"]) == 1
        assert data["items"][0]["slot_index"] == 0

    def test_create_draft_empty_items_422(self, client: TestClient, channel: Channel):
        resp = client.post(
            f"/api/scheduling/channels/{channel.id}/revisions",
            json={
                "broadcast_day": "2026-03-04",
                "created_by": "operator",
                "items": [],
            },
        )
        assert resp.status_code == 422

    def test_list_revisions_endpoint(self, client: TestClient, channel: Channel):
        # Create a draft first
        client.post(
            f"/api/scheduling/channels/{channel.id}/revisions",
            json={
                "broadcast_day": "2026-03-04",
                "created_by": "operator",
                "items": [
                    {
                        "start_time": "2026-03-04T06:00:00+00:00",
                        "duration_sec": 1800,
                        "content_type": "episode",
                    }
                ],
            },
        )

        resp = client.get(f"/api/scheduling/channels/{channel.id}/revisions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "item_count" in data[0]

    def test_get_revision_endpoint(self, client: TestClient, channel: Channel):
        create_resp = client.post(
            f"/api/scheduling/channels/{channel.id}/revisions",
            json={
                "broadcast_day": "2026-03-04",
                "created_by": "operator",
                "items": [
                    {
                        "start_time": "2026-03-04T06:00:00+00:00",
                        "duration_sec": 1800,
                        "content_type": "episode",
                    }
                ],
            },
        )
        rev_id = create_resp.json()["id"]

        resp = client.get(f"/api/scheduling/revisions/{rev_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == rev_id
        assert "items" in data

    def test_publish_endpoint(self, client: TestClient, channel: Channel):
        create_resp = client.post(
            f"/api/scheduling/channels/{channel.id}/revisions",
            json={
                "broadcast_day": "2026-03-04",
                "created_by": "operator",
                "items": [
                    {
                        "start_time": "2026-03-04T06:00:00+00:00",
                        "duration_sec": 1800,
                        "content_type": "episode",
                    }
                ],
            },
        )
        rev_id = create_resp.json()["id"]

        resp = client.post(f"/api/scheduling/revisions/{rev_id}/publish")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert data["activated_at"] is not None

    def test_publish_non_draft_409(self, client: TestClient, channel: Channel):
        create_resp = client.post(
            f"/api/scheduling/channels/{channel.id}/revisions",
            json={
                "broadcast_day": "2026-03-04",
                "created_by": "operator",
                "items": [
                    {
                        "start_time": "2026-03-04T06:00:00+00:00",
                        "duration_sec": 1800,
                        "content_type": "episode",
                    }
                ],
            },
        )
        rev_id = create_resp.json()["id"]

        # Publish once
        client.post(f"/api/scheduling/revisions/{rev_id}/publish")

        # Publish again — should be 409
        resp = client.post(f"/api/scheduling/revisions/{rev_id}/publish")
        assert resp.status_code == 409

    def test_get_nonexistent_revision_404(self, client: TestClient):
        resp = client.get(f"/api/scheduling/revisions/{uuid_mod.uuid4()}")
        assert resp.status_code == 404

    def test_list_filter_by_status(self, client: TestClient, channel: Channel):
        resp = client.get(
            f"/api/scheduling/channels/{channel.id}/revisions",
            params={"status": "active"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_filter_by_broadcast_day(self, client: TestClient, channel: Channel):
        resp = client.get(
            f"/api/scheduling/channels/{channel.id}/revisions",
            params={"broadcast_day": "2026-03-04"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
