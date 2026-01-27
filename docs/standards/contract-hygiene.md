# Contract Hygiene Checklist

## Purpose

Ensure contracts specify **what** the system guarantees (observable outcomes) without prescribing **how** to implement those guarantees (internal mechanisms). This prevents brittleness: implementations can evolve freely as long as they satisfy the contract.

## The Rewrite Test

> **Gold standard**: "Could someone rewrite the implementation from scratch, using only the contract, and pass all contract tests?"

If the contract references internal names, method signatures, or implementation patterns, the answer is no—and that's brittleness.

---

## What Contracts SHOULD Specify (WHAT)

| Category | Examples |
|----------|----------|
| **Exit codes** | `0` = success, `1` = validation error |
| **JSON response structure** | Required fields, types, semantics |
| **Observable side effects** | "A Source record is created", "Asset state becomes `ready`" |
| **Error conditions and messages** | "If channel not found → exit 1, message: ..." |
| **Timing guarantees** | "Completes within 500ms", "Time never goes backward" |
| **Forbidden side effects** | "MUST NOT write to production database in test mode" |
| **Idempotency rules** | "Calling twice with same input produces same result" |
| **Atomicity guarantees** | "All changes succeed or all are rolled back" |

---

## What Contracts MUST NOT Specify (HOW)

| Category | Violation Example | Why It's Brittle |
|----------|-------------------|------------------|
| **Internal method names** | "MUST call `get_config_schema()`" | Renaming the method breaks the contract |
| **Internal class/interface names** | "MUST implement `ImporterInterface`" | Refactoring inheritance breaks the contract |
| **Implementation code snippets** | Python/C++ showing how to implement | Forces copy-paste; alternative approaches "violate" contract |
| **IPC mechanisms** | "Send via stdin", "close stdin after write" | Switching to gRPC or sockets "violates" contract |
| **Internal state tracking** | "MUST track PID", "MUST maintain refcount" | Internal bookkeeping is implementation choice |
| **Specific CLI flags for internal calls** | "`--mode live --request-json-stdin`" | Flag names are implementation detail |
| **Transaction mechanics** | "MUST use `with session() as db:`" | ORM choice is implementation detail |
| **Internal field mappings** | "`asset_path` → `asset_path`, `start_pts` = 0" | Field names may change |

---

## PR Review Checklist

Before approving any contract change, verify:

### ✅ Observable Outcomes Only

- [ ] All behavioral rules (B-#) describe **externally observable** results
- [ ] All data rules (D-#) describe **what persists**, not how persistence works
- [ ] Exit codes and error messages are specified
- [ ] JSON output structure is defined (if applicable)

### ✅ No Implementation Leakage

- [ ] No internal function/method names appear in normative rules
- [ ] No internal class/interface names appear in normative rules
- [ ] No code snippets in the contract body (move to architecture docs if needed)
- [ ] No IPC/communication mechanism details (stdin, sockets, PIDs)
- [ ] No specific CLI flags for internal tool invocations

### ✅ Testable From Outside

- [ ] Every rule can be verified by invoking the CLI or API and inspecting outputs
- [ ] No rule requires inspecting internal state to verify compliance
- [ ] Contract tests don't need to mock internal methods by name

### ✅ Flexible Implementation

- [ ] An alternative implementation (different language, different architecture) could satisfy this contract
- [ ] Renaming internal methods would not break contract compliance
- [ ] Refactoring internal class hierarchy would not break contract compliance

---

## Refactoring Patterns

### Before (leaks "how")

```markdown
**B-11:** Configuration parameters MUST be validated against importer's `get_config_schema()` method.
```

### After (specifies "what")

```markdown
**B-11:** Configuration MUST be validated before source creation. Invalid configuration MUST cause exit code 1 with a descriptive error message.
```

---

### Before (leaks "how")

```markdown
**B-21:** PlayoutRequest MUST be sent to Air via stdin as JSON-encoded data.
**B-22:** ChannelManager MUST close stdin immediately after writing complete PlayoutRequest JSON.
```

### After (specifies "what")

```markdown
**B-21:** ChannelManager MUST deliver a valid PlayoutRequest to Air before playout begins.
```

---

### Before (leaks "how")

```markdown
## Implementation Pattern

```python
def destructive_operation(targets, force=False):
    if env.is_production():
        safe_targets = [t for t in targets if passes_safety_check(t)]
        ...
```

### After (specifies "what")

```markdown
## Safety Behavior

- In production, targets that fail safety checks MUST be skipped
- Skipped targets MUST be reported to the operator
- Safe targets MAY proceed even if unsafe targets were skipped
```

---

## Where Implementation Guidance Belongs

If you need to document *how* something should be implemented:

| Content Type | Location |
|--------------|----------|
| Recommended patterns | `docs/{component}/architecture/` |
| Code examples | `docs/{component}/developer/` |
| Internal API reference | Code comments or `docs/{component}/developer/` |
| Design rationale | Architecture docs or ADRs |

Contracts reference these docs as "See also" but don't duplicate implementation details.

---

## Exceptions

Some contracts legitimately specify interface details:

1. **Public API contracts** (gRPC proto, REST endpoints) — method names are the contract surface
2. **File format contracts** — field names and structure are the contract
3. **Environment variable contracts** — variable names are the contract surface

Even here, prefer specifying the *observable behavior* over internal implementation:
- ✅ "The `/metrics` endpoint MUST return Prometheus text format"
- ❌ "MetricsHTTPServer MUST call `formatPrometheus()` to generate output"

---

## See Also

- [Documentation Standards](documentation-standards.md)
- [Test Methodology](test-methodology.md)
- [AI Assistant Methodology](ai-assistant-methodology.md)
- [Repository Conventions](repository-conventions.md)
