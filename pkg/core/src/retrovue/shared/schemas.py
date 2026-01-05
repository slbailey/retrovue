"""
Pydantic schemas for API serialization.

This module contains all Pydantic models used for API request/response serialization.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# Base schemas
class PackageBase(BaseModel):
    """Base package schema with common fields."""

    name: str = Field(..., min_length=1, max_length=255, description="Package name")
    description: str | None = Field(None, description="Package description")
    type: str = Field(..., description="Package type")
    duration: int | None = Field(None, ge=0, description="Package duration in milliseconds")
    first_asset_id: uuid.UUID | None = Field(
        None, description="ID of the first asset in the package"
    )


class PackageItemBase(BaseModel):
    """Base package item schema with common fields."""

    asset_type: str = Field(..., description="Type of asset")
    asset_id: uuid.UUID = Field(..., description="ID of the asset")
    next_item_id: uuid.UUID | None = Field(None, description="ID of the next item in sequence")
    duration_override: int | None = Field(
        None, ge=0, description="Override duration in milliseconds"
    )
    notes: str | None = Field(None, description="Additional notes")


# Create schemas
class PackageCreate(PackageBase):
    """Schema for creating a new package."""

    pass


class PackageItemCreate(PackageItemBase):
    """Schema for creating a new package item."""

    pass


# Read schemas
class PackageItemRead(PackageItemBase):
    """Schema for reading package item data."""

    id: uuid.UUID
    package_id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)


class PackageRead(PackageBase):
    """Schema for reading package data."""

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    items: list[PackageItemRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


# Update schemas
class PackageUpdate(BaseModel):
    """Schema for updating package data."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    type: str | None = None
    duration: int | None = Field(None, ge=0)


class PackageItemUpdate(BaseModel):
    """Schema for updating package item data."""

    asset_type: str | None = None
    asset_id: uuid.UUID | None = None
    next_item_id: uuid.UUID | None = None
    duration_override: int | None = Field(None, ge=0)
    notes: str | None = None


# List schemas
class PackageList(BaseModel):
    """Schema for package list responses."""

    id: uuid.UUID
    name: str
    type: str
    duration: int | None
    created_at: datetime
    updated_at: datetime
    item_count: int = Field(..., description="Number of items in the package")

    model_config = ConfigDict(from_attributes=True)


# Bulk operation schemas
class PackageItemBulkCreate(BaseModel):
    """Schema for bulk creating package items."""

    items: list[PackageItemCreate] = Field(..., min_length=1, description="List of items to create")


class PackageItemBulkUpdate(BaseModel):
    """Schema for bulk updating package items."""

    items: list[PackageItemUpdate] = Field(..., min_length=1, description="List of items to update")


# Response schemas
class PackageResponse(BaseModel):
    """Standard response schema for package operations."""

    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(..., description="Response message")
    data: PackageRead | None = Field(None, description="Package data if applicable")


class PackageListResponse(BaseModel):
    """Response schema for package list operations."""

    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(..., description="Response message")
    data: list[PackageList] = Field(..., description="List of packages")
    total: int = Field(..., description="Total number of packages")


# Validation schemas
class PackageTypeValidation(BaseModel):
    """Schema for validating package types."""

    type: Literal["block", "movie", "special", "bumper", "custom"]


class AssetTypeValidation(BaseModel):
    """Schema for validating asset types."""

    asset_type: Literal["episode", "movie", "bumper", "commercial", "intro", "outro", "credits"]
