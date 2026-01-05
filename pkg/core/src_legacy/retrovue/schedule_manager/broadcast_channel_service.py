"""
BroadcastChannelService - Authoritative CRUD/business layer for BroadcastChannel.

This service is the authoritative source for BroadcastChannel operations in RetroVue.
It enforces business rules, validation, and data integrity for channel management.

The CLI calls this service for operator management.
ScheduleService and ChannelManager should treat BroadcastChannel from this service
as the source of truth for channel identity and scheduling context.

This service handles:
- Channel creation with validation
- Channel updates with business rule enforcement
- Channel deletion with referential integrity
- Channel listing and retrieval
- Name uniqueness enforcement
- Timezone and grid parameter validation
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..domain.entities import BroadcastChannel
from ..infra.uow import session


class BroadcastChannelService:
    """
    Service class for BroadcastChannel CRUD operations and business logic.

    This service enforces validation rules and business logic for channel management.
    All database access goes through SQLAlchemy sessions with proper transaction handling.
    """

    @staticmethod
    def list_channels() -> list[dict[str, Any]]:
        """
        Return a list of all BroadcastChannels with core fields.

        Returns:
            List of dicts with: id, name, timezone, is_active, grid_size_minutes,
            grid_offset_minutes, rollover_minutes, created_at
        """
        with session() as db:
            channels = db.execute(select(BroadcastChannel)).scalars().all()

            result = []
            for channel in channels:
                result.append(
                    {
                        "id": channel.id,
                        "name": channel.name,
                        "timezone": channel.timezone,
                        "is_active": channel.is_active,
                        "grid_size_minutes": channel.grid_size_minutes,
                        "grid_offset_minutes": channel.grid_offset_minutes,
                        "rollover_minutes": channel.rollover_minutes,
                        "created_at": channel.created_at.isoformat(),
                        "updated_at": channel.updated_at.isoformat()
                        if channel.updated_at
                        else None,
                    }
                )

            return result

    @staticmethod
    def get_channel(channel_id: int) -> dict[str, Any] | None:
        """
        Return full details for one BroadcastChannel.

        Args:
            channel_id: The ID of the channel to retrieve

        Returns:
            Dict with all channel fields, or None if not found
        """
        with session() as db:
            channel = db.execute(
                select(BroadcastChannel).where(BroadcastChannel.id == channel_id)
            ).scalar_one_or_none()

            if not channel:
                return None

            return {
                "id": channel.id,
                "name": channel.name,
                "timezone": channel.timezone,
                "grid_size_minutes": channel.grid_size_minutes,
                "grid_offset_minutes": channel.grid_offset_minutes,
                "rollover_minutes": channel.rollover_minutes,
                "is_active": channel.is_active,
                "created_at": channel.created_at.isoformat(),
                "updated_at": channel.updated_at.isoformat() if channel.updated_at else None,
            }

    @staticmethod
    def create_channel(
        name: str,
        timezone: str,
        grid_size_minutes: int,
        grid_offset_minutes: int,
        rollover_minutes: int,
        is_active: bool = True,
    ) -> dict[str, Any]:
        """
        Create a new BroadcastChannel with validation.

        Args:
            name: Channel name (required, must be unique)
            timezone: IANA timezone string (required)
            grid_size_minutes: Base grid slot size (required, non-negative)
            grid_offset_minutes: Grid alignment offset (required, non-negative)
            rollover_minutes: Broadcast day rollover time (required, non-negative)
            is_active: Whether channel is active (default True)

        Returns:
            Dict with created channel data

        Raises:
            ValueError: If validation fails or name is not unique
        """
        # Validate required fields
        if not name or not name.strip():
            raise ValueError("Channel name is required")

        if not timezone or not timezone.strip():
            raise ValueError("Timezone is required")

        # Validate numeric fields
        if grid_size_minutes < 0:
            raise ValueError("grid_size_minutes must be non-negative")

        if grid_offset_minutes < 0:
            raise ValueError("grid_offset_minutes must be non-negative")

        if rollover_minutes < 0:
            raise ValueError("rollover_minutes must be non-negative")

        # Validate is_active is boolean
        if not isinstance(is_active, bool):
            raise ValueError("is_active must be a boolean")

        with session() as db:
            try:
                channel = BroadcastChannel(
                    name=name.strip(),
                    timezone=timezone.strip(),
                    grid_size_minutes=grid_size_minutes,
                    grid_offset_minutes=grid_offset_minutes,
                    rollover_minutes=rollover_minutes,
                    is_active=is_active,
                )
                db.add(channel)
                db.commit()

                return {
                    "id": channel.id,
                    "name": channel.name,
                    "timezone": channel.timezone,
                    "grid_size_minutes": channel.grid_size_minutes,
                    "grid_offset_minutes": channel.grid_offset_minutes,
                    "rollover_minutes": channel.rollover_minutes,
                    "is_active": channel.is_active,
                    "created_at": channel.created_at.isoformat(),
                    "updated_at": channel.updated_at.isoformat() if channel.updated_at else None,
                }

            except IntegrityError:
                db.rollback()
                raise ValueError(f"Channel with name '{name}' already exists")

    @staticmethod
    def update_channel(channel_id: int, **fields) -> dict[str, Any]:
        """
        Update a BroadcastChannel with partial updates.

        Args:
            channel_id: ID of channel to update
            **fields: Fields to update (name, timezone, grid_size_minutes,
                     grid_offset_minutes, rollover_minutes, is_active)

        Returns:
            Dict with updated channel data

        Raises:
            ValueError: If channel not found or validation fails
        """
        with session() as db:
            channel = db.execute(
                select(BroadcastChannel).where(BroadcastChannel.id == channel_id)
            ).scalar_one_or_none()

            if not channel:
                raise ValueError(f"Channel with ID {channel_id} not found")

            # Validate and update fields
            if "name" in fields:
                name = fields["name"]
                if not name or not name.strip():
                    raise ValueError("Channel name cannot be empty")
                channel.name = name.strip()

            if "timezone" in fields:
                timezone = fields["timezone"]
                if not timezone or not timezone.strip():
                    raise ValueError("Timezone cannot be empty")
                channel.timezone = timezone.strip()

            if "grid_size_minutes" in fields:
                grid_size = fields["grid_size_minutes"]
                if grid_size < 0:
                    raise ValueError("grid_size_minutes must be non-negative")
                channel.grid_size_minutes = grid_size

            if "grid_offset_minutes" in fields:
                grid_offset = fields["grid_offset_minutes"]
                if grid_offset < 0:
                    raise ValueError("grid_offset_minutes must be non-negative")
                channel.grid_offset_minutes = grid_offset

            if "rollover_minutes" in fields:
                rollover = fields["rollover_minutes"]
                if rollover < 0:
                    raise ValueError("rollover_minutes must be non-negative")
                channel.rollover_minutes = rollover

            if "is_active" in fields:
                is_active = fields["is_active"]
                if not isinstance(is_active, bool):
                    raise ValueError("is_active must be a boolean")
                channel.is_active = is_active

            try:
                db.commit()

                return {
                    "id": channel.id,
                    "name": channel.name,
                    "timezone": channel.timezone,
                    "grid_size_minutes": channel.grid_size_minutes,
                    "grid_offset_minutes": channel.grid_offset_minutes,
                    "rollover_minutes": channel.rollover_minutes,
                    "is_active": channel.is_active,
                    "created_at": channel.created_at.isoformat(),
                    "updated_at": channel.updated_at.isoformat() if channel.updated_at else None,
                }

            except IntegrityError:
                db.rollback()
                raise ValueError(f"Channel with name '{channel.name}' already exists")

    @staticmethod
    def delete_channel(channel_id: int) -> None:
        """
        Delete a BroadcastChannel.

        Args:
            channel_id: ID of channel to delete

        Raises:
            ValueError: If channel not found
        """
        with session() as db:
            channel = db.execute(
                select(BroadcastChannel).where(BroadcastChannel.id == channel_id)
            ).scalar_one_or_none()

            if not channel:
                raise ValueError(f"Channel with ID {channel_id} not found")

            db.delete(channel)
            db.commit()
