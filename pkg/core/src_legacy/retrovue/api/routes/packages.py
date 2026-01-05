"""
Package API routes for CRUD operations.

This module provides REST API endpoints for managing packages and package items.
This is scaffolding for linked-list packages, to be integrated into the scheduler in a future milestone.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ...domain.package import Package, PackageItem
from ...infra.uow import get_db
from ...shared.schemas import (
    PackageCreate,
    PackageItemCreate,
    PackageItemRead,
    PackageList,
    PackageListResponse,
    PackageRead,
    PackageResponse,
    PackageUpdate,
)

router = APIRouter(prefix="/packages", tags=["packages"])


@router.get("/", response_model=PackageListResponse)
async def list_packages(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    package_type: Annotated[str | None, Query()] = None,
    db: Session = Depends(get_db),
):
    """
    List all packages with optional filtering.

    Args:
        skip: Number of packages to skip
        limit: Maximum number of packages to return
        package_type: Filter by package type
        db: Database session

    Returns:
        List of packages with metadata
    """
    try:
        query = db.query(Package)

        if package_type:
            query = query.filter(Package.type == package_type)

        total = query.count()
        packages = query.offset(skip).limit(limit).all()

        package_list = []
        for package in packages:
            package_list.append(
                PackageList(
                    id=package.id,
                    name=package.name,
                    type=package.type,
                    duration=package.duration,
                    created_at=package.created_at,
                    updated_at=package.updated_at,
                    item_count=len(package.items),
                )
            )

        return PackageListResponse(
            success=True,
            message=f"Retrieved {len(package_list)} packages",
            data=package_list,
            total=total,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list packages: {str(e)}",
        )


@router.get("/{package_id}", response_model=PackageResponse)
async def get_package(
    package_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """
    Get a specific package by ID.

    Args:
        package_id: ID of the package to retrieve
        db: Database session

    Returns:
        Package data with items
    """
    try:
        package = db.query(Package).filter(Package.id == package_id).first()

        if not package:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Package {package_id} not found"
            )

        # Convert items to read format
        items = []
        for item in package.items:
            items.append(
                PackageItemRead(
                    id=item.id,
                    package_id=item.package_id,
                    asset_type=item.asset_type,
                    asset_id=item.asset_id,
                    next_item_id=item.next_item_id,
                    duration_override=item.duration_override,
                    notes=item.notes,
                )
            )

        package_data = PackageRead(
            id=package.id,
            name=package.name,
            description=package.description,
            type=package.type,
            duration=package.duration,
            created_at=package.created_at,
            updated_at=package.updated_at,
            items=items,
        )

        return PackageResponse(
            success=True,
            message=f"Retrieved package {package_id}",
            data=package_data,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get package: {str(e)}",
        )


@router.post("/", response_model=PackageResponse, status_code=status.HTTP_201_CREATED)
async def create_package(
    package_data: PackageCreate,
    db: Session = Depends(get_db),
):
    """
    Create a new package.

    Args:
        package_data: Package creation data
        db: Database session

    Returns:
        Created package data
    """
    try:
        package = Package(
            name=package_data.name,
            description=package_data.description,
            type=package_data.type,
            duration=package_data.duration,
        )

        db.add(package)
        db.flush()
        db.refresh(package)

        package_response = PackageRead(
            id=package.id,
            name=package.name,
            description=package.description,
            type=package.type,
            duration=package.duration,
            created_at=package.created_at,
            updated_at=package.updated_at,
            items=[],
        )

        return PackageResponse(
            success=True,
            message=f"Created package {package.id}",
            data=package_response,
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create package: {str(e)}",
        )


@router.put("/{package_id}", response_model=PackageResponse)
async def update_package(
    package_id: uuid.UUID,
    package_data: PackageUpdate,
    db: Session = Depends(get_db),
):
    """
    Update an existing package.

    Args:
        package_id: ID of the package to update
        package_data: Package update data
        db: Database session

    Returns:
        Updated package data
    """
    try:
        package = db.query(Package).filter(Package.id == package_id).first()

        if not package:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Package {package_id} not found"
            )

        # Update fields if provided
        if package_data.name is not None:
            package.name = package_data.name
        if package_data.description is not None:
            package.description = package_data.description
        if package_data.type is not None:
            package.type = package_data.type
        if package_data.duration is not None:
            package.duration = package_data.duration

        db.flush()
        db.refresh(package)

        # Convert items to read format
        items = []
        for item in package.items:
            items.append(
                PackageItemRead(
                    id=item.id,
                    package_id=item.package_id,
                    asset_type=item.asset_type,
                    asset_id=item.asset_id,
                    next_item_id=item.next_item_id,
                    duration_override=item.duration_override,
                    notes=item.notes,
                )
            )

        package_response = PackageRead(
            id=package.id,
            name=package.name,
            description=package.description,
            type=package.type,
            duration=package.duration,
            created_at=package.created_at,
            updated_at=package.updated_at,
            items=items,
        )

        return PackageResponse(
            success=True,
            message=f"Updated package {package_id}",
            data=package_response,
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update package: {str(e)}",
        )


@router.delete("/{package_id}", response_model=PackageResponse)
async def delete_package(
    package_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """
    Delete a package and all its items.

    Args:
        package_id: ID of the package to delete
        db: Database session

    Returns:
        Deletion confirmation
    """
    try:
        package = db.query(Package).filter(Package.id == package_id).first()

        if not package:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Package {package_id} not found"
            )

        db.delete(package)
        db.flush()

        return PackageResponse(
            success=True,
            message=f"Deleted package {package_id}",
            data=None,
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete package: {str(e)}",
        )


@router.post("/{package_id}/items", response_model=PackageResponse)
async def add_package_item(
    package_id: uuid.UUID,
    item_data: PackageItemCreate,
    db: Session = Depends(get_db),
):
    """
    Add an item to a package.

    Args:
        package_id: ID of the package
        item_data: Package item creation data
        db: Database session

    Returns:
        Updated package data
    """
    try:
        package = db.query(Package).filter(Package.id == package_id).first()

        if not package:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Package {package_id} not found"
            )

        package_item = PackageItem(
            package_id=package_id,
            asset_type=item_data.asset_type,
            asset_id=item_data.asset_id,
            next_item_id=item_data.next_item_id,
            duration_override=item_data.duration_override,
            notes=item_data.notes,
        )

        db.add(package_item)
        db.flush()
        db.refresh(package_item)

        # Return updated package
        db.refresh(package)

        # Convert items to read format
        items = []
        for item in package.items:
            items.append(
                PackageItemRead(
                    id=item.id,
                    package_id=item.package_id,
                    asset_type=item.asset_type,
                    asset_id=item.asset_id,
                    next_item_id=item.next_item_id,
                    duration_override=item.duration_override,
                    notes=item.notes,
                )
            )

        package_response = PackageRead(
            id=package.id,
            name=package.name,
            description=package.description,
            type=package.type,
            duration=package.duration,
            created_at=package.created_at,
            updated_at=package.updated_at,
            items=items,
        )

        return PackageResponse(
            success=True,
            message=f"Added item to package {package_id}",
            data=package_response,
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add package item: {str(e)}",
        )


@router.delete("/{package_id}/items/{item_id}", response_model=PackageResponse)
async def remove_package_item(
    package_id: uuid.UUID,
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """
    Remove an item from a package.

    Args:
        package_id: ID of the package
        item_id: ID of the item to remove
        db: Database session

    Returns:
        Updated package data
    """
    try:
        package = db.query(Package).filter(Package.id == package_id).first()

        if not package:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Package {package_id} not found"
            )

        package_item = (
            db.query(PackageItem)
            .filter(PackageItem.id == item_id, PackageItem.package_id == package_id)
            .first()
        )

        if not package_item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Package item {item_id} not found"
            )

        db.delete(package_item)
        db.flush()

        # Return updated package
        db.refresh(package)

        # Convert items to read format
        items = []
        for item in package.items:
            items.append(
                PackageItemRead(
                    id=item.id,
                    package_id=item.package_id,
                    asset_type=item.asset_type,
                    asset_id=item.asset_id,
                    next_item_id=item.next_item_id,
                    duration_override=item.duration_override,
                    notes=item.notes,
                )
            )

        package_response = PackageRead(
            id=package.id,
            name=package.name,
            description=package.description,
            type=package.type,
            duration=package.duration,
            created_at=package.created_at,
            updated_at=package.updated_at,
            items=items,
        )

        return PackageResponse(
            success=True,
            message=f"Removed item from package {package_id}",
            data=package_response,
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove package item: {str(e)}",
        )
