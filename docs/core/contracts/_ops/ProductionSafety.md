# Production Safety Contract

## Purpose

Define the observable guarantees for protecting production environments from accidental data loss during destructive operations. This contract specifies **what** protections exist, not how they are implemented.

---

## Scope

This contract applies to ALL destructive CLI commands that:

- Remove or delete data permanently
- Modify system state in irreversible ways
- Could impact live operations or historical data

**Affected commands:**

- `retrovue source delete`
- `retrovue collection wipe`
- `retrovue enricher remove`
- `retrovue channel delete`
- `retrovue playlist delete`

---

## Production Environment Detection

### PS-001: Environment Determination

**Guarantee:** Production status is explicitly configured, not inferred.

**Observable behavior:**
- Production status is determinable at runtime via configuration
- Production status does not change based on data state or usage patterns
- Non-production environments skip all production safety checks

**Verification:** Same command with same target produces different behavior in production vs. non-production.

---

## Safety Check Guarantees

### PS-010: Safety Checks Before Action

**Guarantee:** In production, safety checks run before any destructive action or confirmation prompt.

**Observable behavior:**
- Unsafe targets are identified before the user is asked to confirm
- No data is deleted before safety evaluation completes
- Safety check results are reported to the operator

**Verification:** Run destructive command on unsafe target in production; observe rejection before confirmation prompt.

---

### PS-011: Unsafe Targets Refused

**Guarantee:** Targets that fail safety checks are not deleted, regardless of flags.

**Observable behavior:**
- `--force` does NOT bypass production safety
- Unsafe targets produce clear error messages explaining why
- Exit code reflects the refusal

**Exit code:** `1` if all targets are unsafe; `2` if some targets are unsafe (batch)

**Verification:** Run `source delete <unsafe-source> --force` in production; observe refusal.

---

### PS-012: Safe Targets Proceed

**Guarantee:** Targets that pass safety checks may proceed (subject to confirmation).

**Observable behavior:**
- Safe targets are offered for confirmation
- Confirmation prompt shows what will be deleted
- After confirmation, deletion proceeds normally

---

## Batch Operation Guarantees

### PS-020: Per-Target Evaluation

**Guarantee:** Batch operations evaluate each target independently.

**Observable behavior:**
- Each target is classified as safe or unsafe
- Results are reported per target before any action
- Safe targets can proceed even if unsafe targets exist in the same batch

---

### PS-021: Batch Reporting

**Guarantee:** Batch operations clearly report which targets were skipped and why.

**Observable behavior:**
- Skipped targets are listed with their safety failure reason
- Proceeding targets are listed with their impact summary
- Final summary shows counts: processed, skipped

**Example output:**

```
⚠️  Production safety check results:
   ✅ Source: "test-plex-1" - Safe to delete
   ❌ Source: "live-plex-server" - Skipped (has aired assets)
   ✅ Source: "dev-plex-2" - Safe to delete

Proceeding with 2 safe sources, skipping 1 protected source.
```

---

### PS-022: Batch Exit Codes

| Exit Code | Meaning |
|-----------|---------|
| `0` | All targets processed successfully |
| `1` | Validation error or all targets failed safety |
| `2` | Partial success: some targets processed, some skipped |
| `3` | External dependency error |

---

## Resource-Specific Safety Rules

Each resource type defines its own safety criteria. This contract defines the enforcement mechanism; resource contracts define the criteria.

### Sources

**Contract:** [SourceDeleteContract.md](../resources/SourceDeleteContract.md)

**Safety rule:** A Source fails production safety if any Asset from that Source has appeared in PlaylogEvent or AsRunLog.

**Rationale:** Sources with aired assets have historical and compliance significance.

---

### Enrichers

**Contract:** [EnricherRemoveContract.md](../resources/EnricherRemoveContract.md)

**Safety rule:** An Enricher fails production safety if:
- It is currently in active use by an ingest or playout operation, OR
- It is flagged `protected_from_removal = true`

**Rationale:** Active enrichers are critical to ongoing operations.

---

### Collections

**Contract:** [CollectionWipeContract.md](../resources/CollectionWipeContract.md)

**Safety rule:** TBD

---

### Channels

**Contract:** [ChannelDeleteContract.md](../resources/ChannelDeleteContract.md)

**Safety rule:** TBD

---

## Non-Production Behavior

### PS-030: No Safety Checks in Non-Production

**Guarantee:** Non-production environments skip safety checks entirely.

**Observable behavior:**
- Destructive operations proceed directly to confirmation
- No "safe/unsafe" evaluation occurs
- All targets are eligible for deletion (subject to confirmation)

**Verification:** Run `source delete <any-source>` in non-production; observe no safety check output.

---

## JSON Output Format

### PS-040: Structured Safety Results

**Guarantee:** With `--json`, safety check results are machine-readable.

**Success format:**
```json
{
  "status": "ok",
  "targets_processed": 2,
  "targets_skipped": 1,
  "skipped": [
    {
      "id": "...",
      "name": "live-plex-server",
      "reason": "has aired assets"
    }
  ]
}
```

**Failure format (all unsafe):**
```json
{
  "status": "error",
  "code": "PRODUCTION_SAFETY_FAILED",
  "message": "All targets failed production safety checks",
  "targets_skipped": 1,
  "skipped": [
    {
      "id": "...",
      "name": "live-plex-server",
      "reason": "has aired assets"
    }
  ]
}
```

---

## Contract Integration

Destructive command contracts MUST reference this contract and define:

1. **Resource-specific safety rule** — what makes a target unsafe
2. **Safety failure message** — what the operator sees when target is unsafe

Example reference in a command contract:

```markdown
## Production Safety

This command complies with ProductionSafety (PS-010 through PS-022).

**Resource-specific safety rule:** A Source is unsafe if any of its Assets appear in PlaylogEvent or AsRunLog.

**Safety failure message:** "Source has aired assets and cannot be deleted in production"
```

---

## Behavioral Rules Summary

| Rule | Guarantee |
|------|-----------|
| PS-001 | Production status is explicit configuration |
| PS-010 | Safety checks run before action and confirmation |
| PS-011 | Unsafe targets are refused, even with `--force` |
| PS-012 | Safe targets proceed normally |
| PS-020 | Batch targets evaluated independently |
| PS-021 | Skipped targets reported with reasons |
| PS-022 | Exit codes reflect partial success |
| PS-030 | Non-production skips safety checks |
| PS-040 | JSON output includes structured safety results |

---

## Test Coverage

| Rule | Test File |
|------|-----------|
| PS-001, PS-010, PS-011 | `test_production_safety_contract.py` |
| PS-020, PS-021, PS-022 | `test_production_safety_contract.py` |
| PS-030 | `test_production_safety_contract.py` |
| PS-040 | `test_production_safety_contract.py` |

---

## See Also

- [DestructiveOperationConfirmation Contract](DestructiveOperationConfirmation.md) — confirmation flow (separate from safety)
- [Unit of Work Contract](UnitOfWorkContract.md) — atomicity guarantees
- [Contract Hygiene Checklist](../../../standards/contract-hygiene.md) — authoring guidelines
