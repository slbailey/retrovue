# Destructive Operation Confirmation Contract

## Purpose

Establish a consistent standard for confirmation and authorization of destructive operations (such as deleting Sources, Collections, Enrichers) across all CLI commands. This contract ensures operator safety, reliable automation, consistent testability, and production invariants are respected.

---

## Command-Line Flags

All destructive commands **MUST** use the following flags (with identical names):

- `--force`  
  _Skips all confirmation prompts_.  
  Proceeds immediately with destructive actions, subject to production safety controls.

- `--confirm`  
  _Non-interactive explicit approval for automation/CI_.  
  Acts as if the user answered "yes" to any confirmation prompt, but requires no stdin interaction.

If _both_ `--force` and `--confirm` are specified, **`--force` takes precedence**.

---

## Confirmation Flow

### C-1. Interactive Confirmation Required

If **neither** `--force` nor `--confirm` are provided, the command **MUST** require interactive confirmation _before_ any destructive action.

### C-2. Prompt Requirements

The destructive prompt **MUST** include, at minimum:

- **Description** of objects being deleted
- **Cascade impact summary** (e.g., "This will also remove: 4 collections")
- **Warning**: the action is irreversible
- **Instruction**: Type `yes` to continue

### C-3. Confirmation Matching

The command **MUST** require the user to type `yes` (**case-insensitive** or strict, but must be standardized—document your choice here).  
Any other response **MUST** be treated as denial.

### C-4. Cancel Behavior

If the operator does **not** confirm:

- Print: `Removal cancelled.`
- Exit with code `0` (cancelling is _not_ an error)

---

## Multi-Target / Batch Confirmation

Destructive actions that affect multiple objects (e.g., deleting 12 Sources) must:

- **C-5:** Aggregate the confirmation prompt:
  - Show the total number of objects selected for deletion
  - Show total cascade impact in aggregate (e.g., "37 collections will also be removed")
  - Include all requirements from C-2 and C-3
- **C-6:** Prompt for confirmation once _per batch_, not per individual object (to avoid operator fatigue and enable efficient bulk operations).

---

## Non-Interactive Approval

- **C-7:** If `--confirm` is set, skip interactive prompts and act as if the operator answered "yes", BUT _still respect_ all production safety checks (e.g., do not delete protected targets).
- **C-8:** If `--force` is set, skip _all_ prompts, acting immediately, but again, _never_ bypass production safety checks.

_This formalizes the relationship: `--force` > `--confirm` > interactive, but **safety is never bypassed**._

---

## Production Safety Enforcement

**C-9:** No confirmation (interactive, `--confirm`, or `--force`) can override production safety policies.  
If deletion is blocked by a production safety rule (e.g., "cannot delete a Source referenced in a PlaylogEvent/AsRunLog"), the object **MUST NOT** be deleted, regardless of confirmation status.

Confirmation only authorizes the _allowed_ destructive operation.

---

## Implementation Guidance

- **C-10:** Implement confirmation logic as a reusable helper function that:
  - Accepts a structured summary (number of objects, cascade counts, etc.)
  - Accepts `--force` and `--confirm`
  - Optionally accepts a user response string (for testing)
  - Returns a tuple: `(proceed: bool, message: str | None)`
- **C-11:** The helper **SHOULD** be fully testable **without** requiring stdin/stdout mocking.  
  Commands can add thin wrappers for actual CLI I/O.

---

## Exit Code and Output Standardization

- **C-12:** If the operator cancels (declines to type `yes` interactively), the command **MUST**:
  - Print: `Removal cancelled.`
  - Exit with code `0`
- **C-13:** On successful deletion, exit with code `0`.  
  If all deletions are blocked due to safety, still exit `0` and state that no objects were deleted.
- **C-14:** If no targets are found for deletion (e.g., selector finds nothing):
  - Print an error: `name/ID not found`
  - Exit with code `1`

_This aligns with existing conventions in SourceDelete and EnricherRemove contracts._

---
