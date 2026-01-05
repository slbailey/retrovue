"""
SQLAlchemy models for RetroVue broadcast scheduling domain.
"""

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from retrovue.infra.db import Base

# BroadcastChannel model moved to domain/entities.py


class BroadcastTemplate(Base):
    """Broadcast template model for scheduling."""

    __tablename__ = "broadcast_template"

    id = sa.Column(sa.Integer, primary_key=True)
    name = sa.Column(sa.Text, nullable=False, unique=True)
    description = sa.Column(sa.Text, nullable=True)
    is_active = sa.Column(sa.Boolean, nullable=False, server_default=sa.text("true"))
    created_at = sa.Column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")
    )

    blocks = sa.orm.relationship(
        "BroadcastTemplateBlock", back_populates="template", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<BroadcastTemplate(id={self.id}, name='{self.name}')>"


class BroadcastTemplateBlock(Base):
    """Broadcast template block model for time blocks within templates."""

    __tablename__ = "broadcast_template_block"

    id = sa.Column(sa.Integer, primary_key=True)
    template_id = sa.Column(
        sa.Integer,
        sa.ForeignKey("broadcast_template.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_time = sa.Column(sa.Text, nullable=False)  # "HH:MM" local wallclock
    end_time = sa.Column(sa.Text, nullable=False)  # "HH:MM"
    rule_json = sa.Column(
        sa.Text, nullable=False
    )  # e.g. {"tags":["sitcom"], "episode_policy":"syndication"}
    created_at = sa.Column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")
    )

    template = sa.orm.relationship("BroadcastTemplate", back_populates="blocks")

    def __repr__(self):
        return f"<BroadcastTemplateBlock(id={self.id}, template_id={self.template_id}, start='{self.start_time}', end='{self.end_time}')>"


class BroadcastScheduleDay(Base):
    """Broadcast schedule day model for assigning templates to channels on specific days."""

    __tablename__ = "broadcast_schedule_day"

    id = sa.Column(sa.Integer, primary_key=True)
    channel_id = sa.Column(
        sa.Integer,
        sa.ForeignKey("broadcast_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_id = sa.Column(
        sa.Integer, sa.ForeignKey("broadcast_template.id", ondelete="RESTRICT"), nullable=False
    )
    schedule_date = sa.Column(
        sa.Text, nullable=False
    )  # "YYYY-MM-DD" broadcast-day label, 06:00→06:00 policy
    created_at = sa.Column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "channel_id", "schedule_date", name="uq_broadcast_schedule_day_channel_date"
        ),
    )

    channel = sa.orm.relationship("BroadcastChannel")
    template = sa.orm.relationship("BroadcastTemplate")

    def __repr__(self):
        return f"<BroadcastScheduleDay(id={self.id}, channel_id={self.channel_id}, template_id={self.template_id}, date='{self.schedule_date}')>"


class BroadcastPlaylogEvent(Base):
    """Broadcast playlog event model for tracking what was actually played."""

    __tablename__ = "broadcast_playlog_event"

    id = sa.Column(sa.Integer, primary_key=True)
    uuid = sa.Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False, unique=True)
    channel_id = sa.Column(
        sa.Integer,
        sa.ForeignKey("broadcast_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    asset_uuid = sa.Column(
        UUID(as_uuid=True), sa.ForeignKey("assets.uuid", ondelete="RESTRICT"), nullable=False
    )
    start_utc = sa.Column(sa.DateTime(timezone=True), nullable=False)
    end_utc = sa.Column(sa.DateTime(timezone=True), nullable=False)
    broadcast_day = sa.Column(sa.Text, nullable=False)  # "YYYY-MM-DD" broadcast day label
    created_at = sa.Column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")
    )

    __table_args__ = (
        sa.Index("ix_broadcast_playlog_event_channel_start", "channel_id", "start_utc"),
        sa.Index("ix_broadcast_playlog_event_broadcast_day", "broadcast_day"),
        sa.Index("ix_broadcast_playlog_event_asset_uuid", "asset_uuid"),
    )

    channel = sa.orm.relationship("BroadcastChannel")
    asset = sa.orm.relationship("Asset", foreign_keys=[asset_uuid])

    def __repr__(self):
        return f"<BroadcastPlaylogEvent(id={self.id}, channel_id={self.channel_id}, asset_uuid={self.asset_uuid}, start='{self.start_utc}')>"
