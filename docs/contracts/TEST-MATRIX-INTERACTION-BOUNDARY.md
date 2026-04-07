# Test Matrix — Interaction Boundary Invariants

**Status:** Active
**Test file:** `pkg/core/tests/contracts/test_interaction_boundary_contract.py` (not yet implemented)

---

## Section 1: CLI Business Logic Prohibition

### INV-CLI-NO-BUSINESS-LOGIC-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TIBCLI-001 | CLI command modules import only from workflows/, usecases/, and CLI utilities | Valid | Not yet implemented |
| TIBCLI-002 | CLI command module contains db.query() or db.add() | Rejected: `INV-CLI-NO-BUSINESS-LOGIC-001-VIOLATED` | Not yet implemented |
| TIBCLI-003 | CLI command module performs entity state mutation | Rejected: `INV-CLI-NO-BUSINESS-LOGIC-001-VIOLATED` | Not yet implemented |

---

## Section 2: API Business Logic Prohibition

### INV-API-NO-BUSINESS-LOGIC-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TIBAPI-001 | API route handler calls only workflow/usecase functions | Valid | Not yet implemented |
| TIBAPI-002 | API route handler contains db.query() beyond dependency injection | Rejected: `INV-API-NO-BUSINESS-LOGIC-001-VIOLATED` | Not yet implemented |
| TIBAPI-003 | API route handler performs entity state mutation | Rejected: `INV-API-NO-BUSINESS-LOGIC-001-VIOLATED` | Not yet implemented |

---

## Section 3: Workflow Nesting Depth

### INV-WORKFLOW-FLAT-NESTING-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TIBWF-001 | Workflow calls usecases directly (depth 1) | Valid | Not yet implemented |
| TIBWF-002 | Workflow calls another workflow that calls usecases (depth 2) | Valid | Not yet implemented |
| TIBWF-003 | Workflow calls workflow that calls workflow (depth 3) | Rejected: `INV-WORKFLOW-FLAT-NESTING-001-VIOLATED` | Not yet implemented |

---

## Coverage Notes

These are static-analysis invariants enforced by import-graph inspection. Tests will use AST analysis or module introspection rather than runtime execution.
