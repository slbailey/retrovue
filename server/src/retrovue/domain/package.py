"""
Package domain models for schedulable content containers.

A Package represents a schedulable container — a linked list of assets (episodes, bumpers, movies, etc.)
that play sequentially as one logical item. This is scaffolding for linked-list packages, to be
integrated into the scheduler in a future milestone.

Examples:
- A "SpongeBob 30-Minute Block" → intro bumper → random episode → random episode → end credits
- An "HBO Horror Movie Presentation" → HBO intro → random horror movie → end credits
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..shared.types import PackageType
from .entities import Base

if TYPE_CHECKING:
    pass


class Package(Base):
    """
    A schedulable container representing a linked list of assets.

    Packages are the core scheduling unit - they contain ordered sequences of assets
    that play together as one logical programming block. The package points to the
    first asset, and each asset points to the next asset in the sequence.
    """

    __tablename__ = "packages"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Basic package information
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False, default=PackageType.BLOCK.value)

    # Duration information (in milliseconds)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Pointer to first asset in the linked list
    first_asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    items: Mapped[list[PackageItem]] = relationship(
        "PackageItem", back_populates="package", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Package(id={self.id}, name='{self.name}', type='{self.type}')>"


class PackageItem(Base):
    """
    An item within a package, representing a single asset in the sequence.

    PackageItems form a linked list structure where each item points to the next
    item in the sequence. This allows for flexible ordering and easy insertion/removal.
    """

    __tablename__ = "package_items"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign key to package
    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packages.id"), nullable=False
    )

    # Asset information
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Linked list structure - points to next asset in sequence
    next_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("package_items.id"), nullable=True
    )

    # Optional overrides
    duration_override: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # Override asset duration in ms
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    package: Mapped[Package] = relationship("Package", back_populates="items")
    next_item: Mapped[PackageItem | None] = relationship("PackageItem", remote_side=[id])

    def __repr__(self) -> str:
        return f"<PackageItem(id={self.id}, package_id={self.package_id}, asset_type='{self.asset_type}')>"
