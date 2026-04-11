"""
Tests for Package API routes.

This module tests the FastAPI routes for Package CRUD operations.
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from retrovue.api.routes.packages import router
from retrovue.domain.package import AssetType, Package, PackageItem, PackageType


class TestPackageAPI:
    """Test cases for Package API endpoints."""

    def test_list_packages_empty(self, temp_db_session: Session):
        """Test listing packages when none exist."""
        from fastapi import FastAPI

        from retrovue.api.routes.packages import get_db_session
        
        app = FastAPI()
        app.include_router(router)
        
        # Override the dependency
        def override_get_db():
            return temp_db_session
        
        app.dependency_overrides[get_db_session] = override_get_db
        
        client = TestClient(app)
        response = client.get("/packages/")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total"] == 0
        assert len(data["data"]) == 0

    def test_list_packages_with_data(self, temp_db_session: Session):
        """Test listing packages with existing data."""
        from fastapi import FastAPI

        from retrovue.api.routes.packages import get_db_session
        
        # Create test packages
        package1 = Package(
            name="Test Package 1",
            type=PackageType.BLOCK,
            duration=1800000
        )
        
        package2 = Package(
            name="Test Package 2",
            type=PackageType.MOVIE,
            duration=7200000
        )
        
        temp_db_session.add_all([package1, package2])
        temp_db_session.commit()
        
        app = FastAPI()
        app.include_router(router)
        
        def override_get_db():
            return temp_db_session
        
        app.dependency_overrides[get_db_session] = override_get_db
        
        client = TestClient(app)
        response = client.get("/packages/")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total"] == 2
        assert len(data["data"]) == 2
        
        # Check package data
        package_names = [pkg["name"] for pkg in data["data"]]
        assert "Test Package 1" in package_names
        assert "Test Package 2" in package_names

    def test_get_package_by_id(self, temp_db_session: Session):
        """Test getting a specific package by ID."""
        from fastapi import FastAPI

        from retrovue.api.routes.packages import get_db_session
        
        # Create test package
        package = Package(
            name="Test Package",
            description="A test package",
            type=PackageType.BLOCK,
            duration=1800000
        )
        
        temp_db_session.add(package)
        temp_db_session.commit()
        temp_db_session.refresh(package)
        
        app = FastAPI()
        app.include_router(router)
        
        def override_get_db():
            return temp_db_session
        
        app.dependency_overrides[get_db_session] = override_get_db
        
        client = TestClient(app)
        response = client.get(f"/packages/{package.id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["id"] == str(package.id)
        assert data["data"]["name"] == "Test Package"
        assert data["data"]["description"] == "A test package"
        assert data["data"]["type"] == PackageType.BLOCK
        assert data["data"]["duration"] == 1800000

    def test_get_package_not_found(self, temp_db_session: Session):
        """Test getting a non-existent package."""
        from fastapi import FastAPI

        from retrovue.api.routes.packages import get_db_session
        
        app = FastAPI()
        app.include_router(router)
        
        def override_get_db():
            return temp_db_session
        
        app.dependency_overrides[get_db_session] = override_get_db
        
        client = TestClient(app)
        fake_id = uuid.uuid4()
        response = client.get(f"/packages/{fake_id}")
        
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"]

    def test_create_package(self, temp_db_session: Session):
        """Test creating a new package."""
        from fastapi import FastAPI

        from retrovue.api.routes.packages import get_db_session
        
        app = FastAPI()
        app.include_router(router)
        
        def override_get_db():
            return temp_db_session
        
        app.dependency_overrides[get_db_session] = override_get_db
        
        client = TestClient(app)
        
        package_data = {
            "name": "New Test Package",
            "description": "A newly created package",
            "type": PackageType.BLOCK,
            "duration": 1800000
        }
        
        response = client.post("/packages/", json=package_data)
        
        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["data"]["name"] == "New Test Package"
        assert data["data"]["description"] == "A newly created package"
        assert data["data"]["type"] == PackageType.BLOCK
        assert data["data"]["duration"] == 1800000
        assert data["data"]["id"] is not None

    def test_update_package(self, temp_db_session: Session):
        """Test updating an existing package."""
        from fastapi import FastAPI

        from retrovue.api.routes.packages import get_db_session
        
        # Create test package
        package = Package(
            name="Original Name",
            type=PackageType.BLOCK
        )
        
        temp_db_session.add(package)
        temp_db_session.commit()
        temp_db_session.refresh(package)
        
        app = FastAPI()
        app.include_router(router)
        
        def override_get_db():
            return temp_db_session
        
        app.dependency_overrides[get_db_session] = override_get_db
        
        client = TestClient(app)
        
        update_data = {
            "name": "Updated Name",
            "description": "Updated description",
            "duration": 3600000
        }
        
        response = client.put(f"/packages/{package.id}", json=update_data)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["name"] == "Updated Name"
        assert data["data"]["description"] == "Updated description"
        assert data["data"]["duration"] == 3600000

    def test_delete_package(self, temp_db_session: Session):
        """Test deleting a package."""
        from fastapi import FastAPI

        from retrovue.api.routes.packages import get_db_session
        
        # Create test package
        package = Package(
            name="Package to Delete",
            type=PackageType.BLOCK
        )
        
        temp_db_session.add(package)
        temp_db_session.commit()
        temp_db_session.refresh(package)
        
        app = FastAPI()
        app.include_router(router)
        
        def override_get_db():
            return temp_db_session
        
        app.dependency_overrides[get_db_session] = override_get_db
        
        client = TestClient(app)
        response = client.delete(f"/packages/{package.id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Deleted package" in data["message"]
        assert data["data"] is None

    def test_add_package_item(self, temp_db_session: Session):
        """Test adding an item to a package."""
        from fastapi import FastAPI

        from retrovue.api.routes.packages import get_db_session
        
        # Create test package
        package = Package(
            name="Package with Items",
            type=PackageType.BLOCK
        )
        
        temp_db_session.add(package)
        temp_db_session.commit()
        temp_db_session.refresh(package)
        
        app = FastAPI()
        app.include_router(router)
        
        def override_get_db():
            return temp_db_session
        
        app.dependency_overrides[get_db_session] = override_get_db
        
        client = TestClient(app)
        
        item_data = {
            "asset_type": AssetType.EPISODE,
            "asset_id": str(uuid.uuid4()),
            "duration_override": 1800000,
            "notes": "Test episode"
        }
        
        response = client.post(f"/packages/{package.id}/items", json=item_data)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]["items"]) == 1
        
        item = data["data"]["items"][0]
        assert item["asset_type"] == AssetType.EPISODE
        assert item["duration_override"] == 1800000
        assert item["notes"] == "Test episode"

    def test_remove_package_item(self, temp_db_session: Session):
        """Test removing an item from a package."""
        from fastapi import FastAPI

        from retrovue.api.routes.packages import get_db_session
        
        # Create test package with item
        package = Package(
            name="Package with Item",
            type=PackageType.BLOCK
        )
        
        temp_db_session.add(package)
        temp_db_session.flush()
        
        item = PackageItem(
            package_id=package.id,
            asset_type=AssetType.EPISODE,
            asset_id=uuid.uuid4()
        )
        
        temp_db_session.add(item)
        temp_db_session.commit()
        temp_db_session.refresh(item)
        
        app = FastAPI()
        app.include_router(router)
        
        def override_get_db():
            return temp_db_session
        
        app.dependency_overrides[get_db_session] = override_get_db
        
        client = TestClient(app)
        response = client.delete(f"/packages/{package.id}/items/{item.id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Removed item" in data["message"]
        assert len(data["data"]["items"]) == 0
