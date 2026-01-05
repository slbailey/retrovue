# Testing Strategy: Collection Contracts with Asset Dependencies

## Problem Statement

Collection ingest contracts have significant dependencies on the Asset domain:

- **D-9 to D-17**: Asset persistence, lifecycle states, duplicate detection, timestamps
- **B-15 to B-20**: Asset statistics, duplicate detection, content change detection

However, the Asset domain hasn't been built yet. How should we proceed?

## Recommended Approach: Phased Testing with Minimal Asset Domain

### Phase 1: Test Asset-Independent Rules (Start Now)

**Can be tested immediately without Asset domain:**

#### Behavior Rules (B-#):

- **B-1 to B-13**: Collection validation, scope resolution, prerequisites, importer enumeration
- **B-14**: Importer/service separation (verify importer doesn't write to DB)

#### Data Rules (D-#):

- **D-1 to D-8**: Transaction boundaries, scope isolation, validation
- **D-5a, D-5b**: Importer/service separation (verify importer returns data, service persists)

**Test Files:**

- `test_collection_ingest_contract.py` - Test B-1 to B-14
- `test_collection_ingest_data_contract.py` - Test D-1 to D-8, D-5a, D-5b

**Implementation Notes:**

- Use mocks/stubs for Asset operations in Phase 1
- Verify service layer calls Asset persistence methods correctly
- Verify importer returns `DiscoveredItem` objects without DB writes
- Mark Asset-dependent tests as `@pytest.mark.skip("Requires Asset domain - Phase 2")`

### Phase 2: Build Minimal Asset Domain for Contract Testing

**Build only what's needed to satisfy contract rules:**

#### Required Asset Domain Features:

1. **Asset Model** (minimal):

   - `uuid` (primary key)
   - `collection_uuid` (foreign key)
   - `state` (`new`, `enriching`, `ready`, `retired`)
   - `canonical_id` (for duplicate detection)
   - `content_hash` (for change detection)
   - `updated_at` (timestamp)
   - `created_at` (timestamp)

2. **Asset Repository/Service** (minimal):

   - `find_by_canonical_hash(collection_uuid, canonical_key_hash)` → Asset | None
   - `create(asset)` → Asset
   - `update(asset)` → Asset
   - `update_timestamp(asset)` → Asset

**Contract-Driven Requirements:**
The contracts define exactly what Asset domain needs to provide:

- **D-9**: Canonical identity lookup
- **D-10**: Content signature comparison
- **D-13**: Lifecycle state management (`new`/`enriching`)
- **D-14**: State transitions (`ready` → `new`/`enriching`)
- **D-17**: Timestamp updates

#### Implementation Strategy:

1. Create minimal Asset SQLAlchemy model with only required fields
2. Create AssetRepository with only contract-required methods
3. Implement AssetProcessor (Layer 1) using minimal Asset domain
4. Wire up tests to use real Asset domain (no mocks)

**Test Files:**

- Enable previously skipped tests
- Add tests for D-9 to D-17
- Add tests for B-15 to B-20

### Phase 3: Complete Asset Domain Implementation

**After contracts are tested, build full Asset domain:**

- All fields from `docs/domain/Asset.md`
- Full lifecycle management
- Enricher integration
- Broadcast approval workflow
- Soft delete functionality

This phase is driven by broader requirements, not just contract testing.

## Alternative Approach: Mock-Heavy Testing (Not Recommended)

**Why not recommended:**

- Mocks hide real integration issues
- Contracts should test real behavior, not mock behavior
- Risk of mocks diverging from actual implementation
- Violates "test the contract, not the implementation" principle

**When mocks ARE appropriate:**

- External dependencies (Plex API, filesystem)
- Testing importer/service separation (verify importer doesn't call DB)
- Isolating test scope (not replacing core domain objects)

## Recommended Testing Strategy

### Step 1: Write Contract Tests Now (Phase 1)

```python
# test_collection_ingest_contract.py

def test_b14_importer_returns_discovered_items_without_db_writes():
    """B-14: Verify importer returns DiscoveredItem objects without DB writes."""
    # Mock importer
    # Verify discover() returns DiscoveredItem objects
    # Verify no database writes occur in importer

@pytest.mark.skip("Requires Asset domain - Phase 2")
def test_b15_duplicate_detection():
    """B-15: Duplicate detection prevents creating duplicate Asset records."""
    # Will be implemented in Phase 2
    pass
```

### Step 2: Build Minimal Asset Domain (Phase 2)

```python
# Minimal Asset model for contract testing
class Asset(Base):
    __tablename__ = 'assets'

    uuid = Column(UUID, primary_key=True)
    collection_uuid = Column(UUID, ForeignKey('collections.uuid'))
    state = Column(String(20), nullable=False)  # new, enriching, ready, retired
    canonical_id = Column(String(255), nullable=False)  # For duplicate detection
    content_hash = Column(String(64))  # For change detection
    updated_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True))

class AssetRepository:
    def find_by_canonical_id(self, collection_id: UUID, canonical_id: str) -> Asset | None:
        """D-9: Find existing asset by canonical identity."""
        ...

    def create(self, asset: Asset) -> Asset:
        """D-13: Create new asset in 'new' or 'enriching' state."""
        ...

    def update(self, asset: Asset) -> Asset:
        """D-11, D-14: Update existing asset."""
        ...
```

### Step 3: Complete Contract Tests (Phase 2)

```python
# test_collection_ingest_data_contract.py

def test_d9_duplicate_detection():
    """D-9: Prevent duplicate Asset records for same canonical identity."""
    # Use real Asset domain
    # Create asset with canonical_id="test-123"
    # Try to ingest same canonical_id
    # Verify only one Asset record exists

def test_d13_asset_lifecycle_state():
    """D-13: New assets begin in 'new' or 'enriching' state."""
    # Use real Asset domain
    # Ingest new asset
    # Verify asset.state in ['new', 'enriching']
```

## Benefits of This Approach

1. **Contract-Driven**: Contracts define what Asset domain needs to provide
2. **Incremental**: Can start testing immediately, build domain as needed
3. **Real Testing**: Tests use real Asset domain, not mocks
4. **Clear Boundaries**: Phase 1 tests validation/orchestration, Phase 2 tests persistence
5. **Risk Mitigation**: Identify integration issues early with real domain objects

## Test Coverage Mapping

### Phase 1 (Asset-Independent):

- **B-1..B-14** → `test_collection_ingest_contract.py` ✅ Can test now
- **D-1..D-8, D-5a..D-5b** → `test_collection_ingest_data_contract.py` ✅ Can test now
- **D-9..D-17** → `test_collection_ingest_data_contract.py` ⏸️ Skip until Phase 2
- **B-15..B-20** → `test_collection_ingest_contract.py` ⏸️ Skip until Phase 2

### Phase 2 (With Minimal Asset Domain):

- **D-9..D-17** → `test_collection_ingest_data_contract.py` ✅ Enable tests
- **B-15..B-20** → `test_collection_ingest_contract.py` ✅ Enable tests

## Implementation Checklist

### Phase 1 (Immediate):

- [ ] Write tests for B-1 to B-14 (collection validation, importer separation)
- [ ] Write tests for D-1 to D-8, D-5a, D-5b (transaction boundaries, validation)
- [ ] Use mocks for Asset operations where needed
- [ ] Mark Asset-dependent tests as `@pytest.mark.skip` with clear reason

### Phase 2 (Next):

- [ ] Create minimal Asset SQLAlchemy model (only contract-required fields)
- [ ] Create AssetRepository with contract-required methods
- [ ] Implement AssetProcessor (Layer 1) using minimal Asset domain
- [ ] Enable skipped tests
- [ ] Write tests for D-9 to D-17
- [ ] Write tests for B-15 to B-20

### Phase 3 (Later):

- [ ] Build full Asset domain per `docs/domain/Asset.md`
- [ ] Implement complete lifecycle management
- [ ] Add enricher integration
- [ ] Add broadcast approval workflow

## See Also

- [Collection Ingest Contract](../contracts/resources/CollectionIngestContract.md)
- [Asset Domain](../domain/Asset.md)
- [Ingest Architecture](../developer/IngestArchitecture.md)
- [Contract Test Guidelines](../contracts/resources/CONTRACT_TEST_GUIDELINES.md)

