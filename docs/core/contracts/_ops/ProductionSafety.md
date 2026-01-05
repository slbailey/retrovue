# Production Safety Contract

> **This document is part of the RetroVue Contract System.**  
> For enforcement status, see `tests/CONTRACT_MIGRATION.md`.

This contract defines the standardized production safety model for all destructive operations in RetroVue. It ensures that production environments are protected from accidental data loss while maintaining operational flexibility in non-production environments.

## Purpose

Production safety prevents destructive operations from causing harm to live systems. This contract standardizes:

- How production environments are identified
- When production safety checks are required
- How safety checks are applied and enforced
- How batch operations handle mixed safe/unsafe targets
- Resource-specific safety rules and their documentation

## Scope

This contract applies to ALL destructive CLI commands that:

- Remove or delete data permanently
- Modify system state in irreversible ways
- Could impact live operations or historical data

**Examples:**

- `retrovue source delete`
- `retrovue collection wipe`
- `retrovue enricher remove`
- `retrovue channel delete`
- `retrovue playlist delete`

## Production Environment Definition

**Production is determined by environment configuration (e.g. `env.is_production() == true`).**

This check MUST be enforced by the removal command before performing any destructive action.

**Implementation Requirements:**

- Environment detection MUST be explicit and configurable
- Production status MUST be determinable at runtime
- Non-production environments remain permissive (no safety checks)
- Production status MUST NOT be inferred from usage patterns or data state

## Production Safety Rules (PS-#)

### PS-1: Production Safety Requirement

**Rule:** In production environments, destructive operations MUST apply a safety check before proceeding.

**Behavior:**

- Safety checks run BEFORE any destructive action
- Safety checks run BEFORE confirmation prompts
- Non-production environments skip safety checks entirely
- Safety check results determine which targets are eligible for operation

### PS-2: Safety Check Enforcement

**Rule:** A destructive operation MUST refuse to act on any target that fails its safety check. `--force` MUST NOT override this refusal.

**Behavior:**

- Targets that fail safety checks are skipped
- Skipped targets are reported to the operator
- `--force` flag does NOT bypass production safety
- Operation proceeds only on targets that pass safety checks

### PS-3: Batch Operation Safety

**Rule:** Batch operations MUST evaluate production safety per target, and MAY proceed with safe targets even if unsafe targets were skipped. Skipped targets MUST be reported.

**Behavior:**

- Each target is evaluated independently
- Safe targets can be processed even if unsafe targets exist
- Clear reporting of which targets were skipped and why
- Operation is considered successful if any targets were processed

**Example Output:**

```
⚠️  Production safety check results:
   ✅ Source: "test-plex-1" - Safe to delete
   ❌ Source: "live-plex-server" - Skipped (has aired assets)
   ✅ Source: "dev-plex-2" - Safe to delete

Proceeding with 2 safe sources, skipping 1 protected source.
```

### PS-4: Resource-Specific Safety Documentation

**Rule:** The safety check for a given resource type MUST be documented in that resource's specific contract.

**Behavior:**

- Each resource type defines its own safety criteria
- Safety rules are documented in the resource's contract
- Safety rules reference this contract for enforcement
- Resource contracts cannot redefine production environment detection

## Resource-Specific Safety Rules

### Sources (SourceDelete Contract)

**Reference:** `docs/contracts/resources/SourceDeleteContract.md` (D-5)

**Safety Rule:** A Source fails production safety if any Asset from that Source has appeared in PlaylogEvent or AsRunLog.

**Rationale:** Sources with aired assets have historical significance and operational dependencies that make them unsafe to delete in production.

### Enrichers (EnricherRemove Contract)

**Reference:** `docs/contracts/resources/EnricherRemoveContract.md` (D-5)

**Safety Rule:** An Enricher fails production safety if removing it would cause harm. Harm is defined as either:

- (a) It is currently in active use by an ingest or playout operation
- (b) It is flagged `protected_from_removal = true`

**Rationale:** Enrichers that are actively processing content or explicitly protected are critical to operations and cannot be safely removed.

### Collections (CollectionWipe Contract)

**Reference:** `docs/contracts/resources/CollectionWipeContract.md` (TBD)

**Safety Rule:** [To be defined when CollectionWipe contract is created]

### Channels (ChannelDelete Contract)

**Reference:** `docs/contracts/resources/ChannelContract.md` (TBD)

**Safety Rule:** [To be defined when ChannelDelete contract is created]

## Command Integration Pattern

### Contract Reference Format

Each destructive command contract MUST include:

```markdown
## Production Safety

This command MUST comply with ProductionSafety (PS-1 through PS-4).

**Resource-Specific Safety Rule:**
[Specific safety criteria for this resource type]

**Safety Check Implementation:**
[How the safety check is implemented for this resource]
```

### Implementation Pattern

```python
def destructive_operation(targets: List[Target], force: bool = False):
    # 1. Check if we're in production
    if env.is_production():
        # 2. Apply safety checks per target
        safe_targets = []
        skipped_targets = []

        for target in targets:
            if passes_safety_check(target):
                safe_targets.append(target)
            else:
                skipped_targets.append(target)

        # 3. Report skipped targets
        if skipped_targets:
            report_skipped_targets(skipped_targets)

        # 4. Proceed only with safe targets
        targets = safe_targets

    # 5. Apply confirmation (if not --force)
    if not force:
        if not require_confirmation(targets):
            return  # User cancelled

    # 6. Execute operation
    execute_operation(targets)
```

## Exit Codes

| Code | Meaning                   | Usage                                               |
| ---- | ------------------------- | --------------------------------------------------- |
| `0`  | Success                   | Operation completed successfully                    |
| `1`  | Validation Error          | Invalid arguments, missing required flags           |
| `2`  | Partial Success           | Some targets succeeded, others failed safety checks |
| `3`  | External Dependency Error | Database unavailable, network issues                |

## Examples

### Single Target with Safety Check

```bash
# Production environment - unsafe target
$ retrovue source delete live-plex-server
❌ Production safety check failed:
   Source "live-plex-server" has aired assets and cannot be deleted in production.
Operation cancelled.

# Production environment - safe target
$ retrovue source delete test-plex-server
⚠️  WARNING: This will permanently delete:
   • Source: "test-plex-server" (ID: abc-123)
   • Collections: 5 collections
   • Assets: ~500 assets
This action cannot be undone. Type "yes" to confirm: yes
Successfully deleted source: test-plex-server
```

### Batch Operation with Mixed Safety

```bash
# Production environment - mixed targets
$ retrovue source delete "plex-*"
⚠️  Production safety check results:
   ✅ Source: "plex-dev-1" - Safe to delete
   ❌ Source: "plex-live" - Skipped (has aired assets)
   ✅ Source: "plex-test-2" - Safe to delete

⚠️  WARNING: This will permanently delete 2 sources:
   • Source: "plex-dev-1" (ID: abc-123) - 3 collections, ~300 assets
   • Source: "plex-test-2" (ID: def-456) - 2 collections, ~200 assets
Total impact: 5 collections, ~500 assets
This action cannot be undone. Type "yes" to confirm: yes
Successfully deleted 2 sources, skipped 1 protected source.
```

### Non-Production Environment

```bash
# Non-production environment - no safety checks
$ retrovue source delete live-plex-server
⚠️  WARNING: This will permanently delete:
   • Source: "live-plex-server" (ID: abc-123)
   • Collections: 15 collections
   • Assets: ~2,500 assets
This action cannot be undone. Type "yes" to confirm: yes
Successfully deleted source: live-plex-server
```

## Implementation Guidance

### Environment Detection

```python
def is_production() -> bool:
    """Determine if we're running in a production environment."""
    return os.getenv('RETROVUE_ENVIRONMENT') == 'production'
```

### Safety Check Interface

```python
def passes_safety_check(target: Target) -> bool:
    """Check if target passes production safety requirements."""
    # Resource-specific implementation
    pass

def report_skipped_targets(skipped: List[Target]):
    """Report targets that were skipped due to safety checks."""
    for target in skipped:
        print(f"❌ {target.name} - Skipped ({target.safety_reason})")
```

## Test Coverage Mapping

| Rule Range   | Enforced By             | Test File                                 |
| ------------ | ----------------------- | ----------------------------------------- |
| `PS-1..PS-2` | Production safety tests | `test_production_safety_contract.py`      |
| `PS-3..PS-4` | Integration tests       | `test_production_safety_data_contract.py` |

## Dependencies

- **DestructiveOperationConfirmation Contract**: Confirmation flow for destructive operations
- **Unit of Work Contract**: Transaction management for atomic operations
- **Resource-Specific Contracts**: SourceDelete, EnricherRemove, CollectionWipe, etc.

## See Also

- [DestructiveOperationConfirmation Contract](DestructiveOperationConfirmation.md) - Confirmation flow
- [Unit of Work Contract](UnitOfWorkContract.md) - Transaction management
- [Source Delete Contract](../resources/SourceDeleteContract.md) - Source safety rules
- [Enricher Remove Contract](../resources/EnricherRemoveContract.md) - Enricher safety rules
- [CLI Change Policy](../resources/CLI_CHANGE_POLICY.md) - Governance rules

---

## Traceability

- **Linked Tests:** `tests/contracts/_ops/test_production_safety_contract.py`
- **Dependencies:** All destructive command contracts
- **Last Audit:** 2025-10-28
- **Status:** DRAFT (not yet ENFORCED)
