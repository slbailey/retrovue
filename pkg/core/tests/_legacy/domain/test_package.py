"""
Tests for Package domain models.

This module tests the Package and PackageItem domain models to ensure
they work correctly with the database and relationships.
"""

import uuid

from sqlalchemy.orm import Session

from retrovue.domain.package import AssetType, Package, PackageItem, PackageType


class TestPackage:
    """Test cases for Package model."""

    def test_package_creation(self, temp_db_session: Session):
        """Test creating a basic package."""
        package = Package(
            name="Test Package",
            description="A test package",
            type=PackageType.BLOCK,
            duration=1800000  # 30 minutes
        )
        
        temp_db_session.add(package)
        temp_db_session.commit()
        temp_db_session.refresh(package)
        
        assert package.id is not None
        assert package.name == "Test Package"
        assert package.description == "A test package"
        assert package.type == PackageType.BLOCK
        assert package.duration == 1800000
        assert package.created_at is not None
        assert package.updated_at is not None
        assert len(package.items) == 0

    def test_package_with_items(self, temp_db_session: Session):
        """Test creating a package with items."""
        package = Package(
            name="TV Show Block",
            type=PackageType.BLOCK,
            duration=1800000
        )
        
        temp_db_session.add(package)
        temp_db_session.flush()  # Get the package ID
        
        # Create items
        item1 = PackageItem(
            package_id=package.id,
            asset_type=AssetType.INTRO,
            asset_id=uuid.uuid4(),
            duration_override=30000,  # 30 seconds
            notes="Intro bumper"
        )
        
        item2 = PackageItem(
            package_id=package.id,
            asset_type=AssetType.EPISODE,
            asset_id=uuid.uuid4(),
            next_item_id=None,  # Last item
            notes="Main episode"
        )
        
        temp_db_session.add_all([item1, item2])
        temp_db_session.flush()  # Get the IDs
        
        # Link items
        item1.next_item_id = item2.id
        
        temp_db_session.commit()
        
        # Refresh and check relationships
        temp_db_session.refresh(package)
        assert len(package.items) == 2
        
        # Check linked list structure
        assert len(package.items) == 2
        # Find items by their next_item_id relationships
        first_item = next((item for item in package.items if item.next_item_id is not None), None)
        last_item = next((item for item in package.items if item.next_item_id is None), None)
        
        assert first_item is not None
        assert last_item is not None
        assert first_item.next_item_id == last_item.id

    def test_package_types(self, temp_db_session: Session):
        """Test different package types."""
        types_to_test = [
            PackageType.BLOCK,
            PackageType.MOVIE,
            PackageType.SPECIAL,
            PackageType.BUMPER,
            PackageType.CUSTOM
        ]
        
        for package_type in types_to_test:
            package = Package(
                name=f"Test {package_type} Package",
                type=package_type
            )
            
            temp_db_session.add(package)
            temp_db_session.commit()
            temp_db_session.refresh(package)
            
            assert package.type == package_type

    def test_package_repr(self, temp_db_session: Session):
        """Test package string representation."""
        package = Package(
            name="Test Package",
            type=PackageType.BLOCK
        )
        
        temp_db_session.add(package)
        temp_db_session.commit()
        temp_db_session.refresh(package)
        
        repr_str = repr(package)
        assert "Package" in repr_str
        assert str(package.id) in repr_str
        assert "Test Package" in repr_str
        assert PackageType.BLOCK in repr_str


class TestPackageItem:
    """Test cases for PackageItem model."""

    def test_package_item_creation(self, temp_db_session: Session):
        """Test creating a basic package item."""
        # Create package first
        package = Package(
            name="Test Package",
            type=PackageType.BLOCK
        )
        
        temp_db_session.add(package)
        temp_db_session.flush()
        
        item = PackageItem(
            package_id=package.id,
            asset_type=AssetType.EPISODE,
            asset_id=uuid.uuid4(),
            duration_override=1800000,  # 30 minutes
            notes="Test episode"
        )
        
        temp_db_session.add(item)
        temp_db_session.commit()
        temp_db_session.refresh(item)
        
        assert item.id is not None
        assert item.package_id == package.id
        assert item.asset_type == AssetType.EPISODE
        assert item.duration_override == 1800000
        assert item.notes == "Test episode"
        assert item.next_item_id is None

    def test_package_item_linked_list(self, temp_db_session: Session):
        """Test package item linked list structure."""
        # Create package
        package = Package(
            name="Linked List Test",
            type=PackageType.BLOCK
        )
        
        temp_db_session.add(package)
        temp_db_session.flush()
        
        # Create items
        item1 = PackageItem(
            package_id=package.id,
            asset_type=AssetType.INTRO,
            asset_id=uuid.uuid4()
        )
        
        item2 = PackageItem(
            package_id=package.id,
            asset_type=AssetType.EPISODE,
            asset_id=uuid.uuid4()
        )
        
        item3 = PackageItem(
            package_id=package.id,
            asset_type=AssetType.OUTRO,
            asset_id=uuid.uuid4()
        )
        
        temp_db_session.add_all([item1, item2, item3])
        temp_db_session.flush()
        
        # Link items: item1 -> item2 -> item3
        item1.next_item_id = item2.id
        item2.next_item_id = item3.id
        # item3.next_item_id remains None (end of list)
        
        temp_db_session.commit()
        temp_db_session.refresh(package)
        
        # Verify linked list structure
        assert len(package.items) == 3
        
        # Find the chain: item1 -> item2 -> item3
        first_item = next((item for item in package.items if item.next_item_id is not None), None)
        middle_item = next((item for item in package.items if item.id == first_item.next_item_id), None)
        last_item = next((item for item in package.items if item.next_item_id is None), None)
        
        assert first_item is not None
        assert middle_item is not None
        assert last_item is not None
        assert first_item.next_item_id == middle_item.id
        assert middle_item.next_item_id == last_item.id
        assert last_item.next_item_id is None

    def test_package_item_asset_types(self, temp_db_session: Session):
        """Test different asset types."""
        # Create package
        package = Package(
            name="Asset Type Test",
            type=PackageType.BLOCK
        )
        
        temp_db_session.add(package)
        temp_db_session.flush()
        
        asset_types = [
            AssetType.EPISODE,
            AssetType.MOVIE,
            AssetType.BUMPER,
            AssetType.COMMERCIAL,
            AssetType.INTRO,
            AssetType.OUTRO,
            AssetType.CREDITS
        ]
        
        for asset_type in asset_types:
            item = PackageItem(
                package_id=package.id,
                asset_type=asset_type,
                asset_id=uuid.uuid4()
            )
            
            temp_db_session.add(item)
            temp_db_session.commit()
            temp_db_session.refresh(item)
            
            assert item.asset_type == asset_type

    def test_package_item_repr(self, temp_db_session: Session):
        """Test package item string representation."""
        # Create package
        package = Package(
            name="Test Package",
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
        
        repr_str = repr(item)
        assert "PackageItem" in repr_str
        assert str(item.id) in repr_str
        assert str(package.id) in repr_str
        assert AssetType.EPISODE in repr_str

    def test_package_item_relationships(self, temp_db_session: Session):
        """Test package item relationships."""
        # Create package
        package = Package(
            name="Relationship Test",
            type=PackageType.BLOCK
        )
        
        temp_db_session.add(package)
        temp_db_session.flush()
        
        # Create items
        item1 = PackageItem(
            package_id=package.id,
            asset_type=AssetType.INTRO,
            asset_id=uuid.uuid4()
        )
        
        item2 = PackageItem(
            package_id=package.id,
            asset_type=AssetType.EPISODE,
            asset_id=uuid.uuid4()
        )
        
        temp_db_session.add_all([item1, item2])
        temp_db_session.flush()
        
        # Link items
        item1.next_item_id = item2.id
        
        temp_db_session.commit()
        temp_db_session.refresh(package)
        temp_db_session.refresh(item1)
        temp_db_session.refresh(item2)
        
        # Test relationships
        assert item1.package == package
        assert item2.package == package
        assert item1.next_item == item2
        assert item2.next_item is None
        
        # Test package items relationship
        assert len(package.items) == 2
        assert item1 in package.items
        assert item2 in package.items
