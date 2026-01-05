# Database Scheduling Domain Tests

This document defines the testing requirements and best practices for the Broadcast Scheduling Domain database tests. These tests validate the complete data model and ensure proper integration with Alembic migrations.

## Test Environment Requirements

### Database Backend

**Postgres Only**: All scheduling domain tests MUST use Postgres as the database backend. SQLite is not permitted for these tests.

**Rationale**:

- Alembic migrations are designed for Postgres and may use Postgres-specific features
- Production environment uses Postgres, so tests must match production behavior
- SQLite has different constraint handling and data type behavior that could mask issues
- Postgres-specific time functions are critical for broadcast scheduling

### Migration Management

**Alembic Migrations Required**: Tests MUST run Alembic migrations before execution. Programmatic table creation is forbidden.

**Migration Process**:

```python
# Test setup must include:
from alembic import command
from alembic.config import Config

# Run migrations before test execution
alembic_cfg = Config("alembic.ini")
command.upgrade(alembic_cfg, "head")
```

**Rationale**:

- Tests must validate the actual production schema created by migrations
- Programmatic table creation can diverge from migration definitions
- Alembic migrations are the authoritative source of schema truth
- Migration testing ensures schema changes don't break existing functionality

### Prohibited Approaches

**No SQLite**: SQLite is not permitted for scheduling domain tests.

**No Programmatic Table Creation**: Tests must not use `Base.metadata.create_all()` or similar programmatic schema creation.

**No Schema Drops**: Tests must not drop entire schemas or databases during cleanup.

## Test Structure and Organization

### Test Categories

**Unit Tests**: Individual model validation and basic CRUD operations
**Integration Tests**: Model relationships and foreign key constraints
**End-to-End Tests**: Complete workflow validation from configuration to playout
**Migration Tests**: Alembic migration validation and rollback testing

### Test File Organization

```
tests/
├── test_scheduling_domain/
│   ├── test_broadcast_channel.py
│   ├── test_schedule_template.py
│   ├── test_schedule_template_block.py
│   ├── test_broadcast_schedule_day.py
│   ├── test_catalog_asset.py
│   ├── test_broadcast_playlog_event.py
│   └── test_integration.py
```

## Database Setup and Teardown

### Test Database Configuration

**Database URL**: Tests must use a dedicated test database URL:

```python
# test_config.py
TEST_DATABASE_URL = "postgresql://user:pass@localhost/retrovue_test"
```

**Connection Management**: Use connection pooling and proper session management:

```python
from retrovue.infra.db import get_engine, get_sessionmaker

# Test setup
engine = get_engine(TEST_DATABASE_URL)
SessionLocal = get_sessionmaker()
```

### Migration Setup

**Pre-Test Migration**: All tests must run migrations before execution:

```python
import pytest
from alembic import command
from alembic.config import Config

@pytest.fixture(scope="session")
def migrated_db():
    """Run Alembic migrations before test execution."""
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    yield
    # Cleanup handled by logical cleanup, not schema drops
```

### Logical Cleanup Strategy

**Data Cleanup Only**: Tests must clean up data logically, not by dropping schemas.

**Cleanup Order**: Respect foreign key constraints during cleanup:

1. Delete dependent records first (playlog events, schedule days, template blocks)
2. Delete parent records last (channels, templates, catalog assets)

**Example Cleanup**:

```python
def cleanup_test_data(session):
    """Clean up test data in proper order."""
    # Delete dependent records first
    session.query(BroadcastPlaylogEvent).delete()
    session.query(BroadcastScheduleDay).delete()
    session.query(ScheduleTemplateBlock).delete()

    # Delete parent records
    session.query(ScheduleTemplate).delete()
    session.query(Channel).delete()

    session.commit()
```

**No Schema Drops**: Tests must not drop tables, schemas, or databases. Only data cleanup is permitted.

## End-to-End Test Requirements

### Broadcast Channel Tests

**Channel Creation**: Validate channel creation with all required fields:

- Name uniqueness and validation
- Grid configuration (size, offset, anchor)
- Active status management

**Channel Relationships**: Test foreign key relationships:

- Channel to schedule day relationships
- Channel to playlog event relationships
- Cascade delete behavior

**Channel Configuration**: Validate timing and grid settings:

- Grid size and offset calculations
- Broadcast day anchor handling

### Schedule Template Tests

**Template Creation**: Validate template creation and management:

- Name uniqueness and validation
- Description handling
- Active status management

**Template Relationships**: Test template relationships:

- Template to template block relationships
- Template to schedule day relationships
- Cascade delete behavior

**Template Lifecycle**: Validate template activation/deactivation:

- Active template filtering
- Template usage validation
- Template dependency checking

### Schedule Template Block Tests

**Block Creation**: Validate block creation within templates:

- Time range validation (start_time, end_time)
- Rule JSON validation and parsing
- Template relationship integrity

**Content Selection Rules**: Test rule JSON functionality:

- Tag-based content selection
- Episode policy handling
- Duration constraints
- Rule validation and error handling

**Block Timing**: Validate time block logic:

- Time format validation (HH:MM)
- Time range overlap detection
- Block sequencing validation

### Broadcast Schedule Day Tests

**Schedule Assignment**: Validate template-to-channel assignments:

- Unique constraint enforcement (channel_id, schedule_date)
- Date format validation (YYYY-MM-DD)
- Template and channel relationship integrity

**Schedule Resolution**: Test schedule assignment resolution:

- Active template identification
- Date-based template selection
- Channel-specific schedule retrieval

**Schedule Management**: Validate schedule assignment lifecycle:

- Assignment creation and modification
- Schedule conflict detection
- Assignment cleanup and removal

### Catalog Asset Tests

**Asset Creation**: Validate catalog asset creation:

- Title and metadata validation
- Duration handling (milliseconds)
- Tag management and parsing
- File path validation

**Approval Workflow**: Test canonical asset management:

- Canonical status enforcement
- Approval workflow validation
- Content eligibility checking

**Content Selection**: Validate asset selection criteria:

- Tag-based filtering
- Duration-based selection
- Canonical status filtering
- Content availability checking

### Broadcast Playlog Event Tests

**Event Generation**: Validate playlog event creation:

- Event timing and sequencing
- Content and channel relationships
- UTC time handling
- Broadcast day tracking

**Event Relationships**: Test playlog event relationships:

- Channel relationship integrity
- Asset relationship integrity
- Event sequencing validation

**Event Execution**: Validate playlog event execution:

- Event timing accuracy
- Content playback coordination
- Event status tracking

## Integration Test Requirements

### Cross-Model Integration

**Template-to-Playlog Flow**: Test complete workflow from template to playlog:

1. Create broadcast channel
2. Create broadcast template with blocks
3. Create catalog assets
4. Assign template to channel for specific date
5. Generate playlog events
6. Validate event content and timing

**Content Selection Integration**: Test content selection across models:

1. Create template with content selection rules
2. Create catalog assets with matching tags
3. Validate content selection accuracy
4. Verify content eligibility

**Schedule Generation Integration**: Test complete schedule generation:

1. Set up channel, template, and assets
2. Create schedule assignment
3. Generate playlog events
4. Validate event timing and content

### Constraint Validation

**Foreign Key Constraints**: Test all foreign key relationships:

- Channel references in schedule days and playlog events
- Template references in schedule days and template blocks
- Asset references in playlog events

**Unique Constraints**: Test unique constraint enforcement:

- Channel name uniqueness
- Template name uniqueness
- Schedule day uniqueness (channel_id, schedule_date)

**Data Integrity**: Validate data integrity across models:

- Referential integrity
- Constraint enforcement
- Data consistency

## Test Data Management

### Test Data Creation

**Realistic Data**: Use realistic test data that matches production scenarios:

- Representative local-time scenarios
- Valid date formats
- Realistic content tags
- Proper file paths

**Data Relationships**: Create test data with proper relationships:

- Linked channels, templates, and assets
- Valid foreign key references
- Consistent data across models

### Test Data Cleanup

**Logical Cleanup**: Clean up test data without dropping schemas:

- Delete records in proper order
- Respect foreign key constraints
- Maintain schema integrity

**Isolation**: Ensure test isolation:

- Each test cleans up its own data
- No test data leakage between tests
- Consistent test environment

## Performance and Scalability

### Test Performance

**Migration Performance**: Validate migration execution time:

- Migration completion within reasonable time
- No migration timeouts
- Efficient migration execution

**Query Performance**: Test database query performance:

- Efficient content selection queries
- Proper index usage
- Query execution time validation

### Scalability Testing

**Data Volume**: Test with realistic data volumes:

- Multiple channels and templates
- Large catalog asset collections
- Extended schedule periods

**Concurrent Access**: Test concurrent database access:

- Multiple session handling
- Transaction isolation
- Lock management

## Error Handling and Edge Cases

### Error Scenarios

**Invalid Data**: Test error handling for invalid data:

- Malformed date formats
- Invalid JSON in rule_json
- Constraint violation handling

**Missing References**: Test handling of missing references:

- Orphaned foreign key references
- Missing template or channel references
- Invalid asset references

### Edge Cases

**Time Handling**: Test edge cases:

- Daylight saving time transitions
- Rollover handling across the broadcast day boundary

**Date Boundaries**: Test date boundary handling:

- Broadcast day rollover
- Date format edge cases
- Schedule date validation

## Test Execution Requirements

### Test Environment

**Postgres Database**: All tests must run against Postgres database
**Alembic Migrations**: Tests must run migrations before execution
**Clean Environment**: Tests must start with clean database state
**Logical Cleanup**: Tests must clean up data without dropping schemas

### Test Validation

**Schema Validation**: Validate schema matches migration definitions
**Data Integrity**: Validate data integrity and constraints
**Relationship Validation**: Validate all model relationships
**End-to-End Validation**: Validate complete workflows

### Test Reporting

**Test Coverage**: Ensure comprehensive test coverage
**Performance Metrics**: Track test execution performance
**Error Reporting**: Clear error messages and debugging information
**Test Documentation**: Clear test documentation and examples

## Conclusion

Database scheduling domain tests must use Postgres with Alembic migrations, validate end-to-end behavior across all models, and maintain data integrity through logical cleanup. These tests ensure the scheduling domain works correctly in production-like conditions while maintaining schema integrity and data consistency.
