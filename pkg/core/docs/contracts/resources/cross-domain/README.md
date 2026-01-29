# Cross-Domain Guarantees

> This standard extends the global contract methodology defined in [docs/contracts/resources/README.md](../README.md), ensuring consistent governance across all domain interactions.

## 📜 House Standard: Cross-Domain Guarantees

### Purpose

All domain interactions that cross a boundary (e.g. Source ↔ Enricher, Importer ↔ Collection) must have an explicit Cross-Domain Guarantee document and test suite.

This ensures that multi-domain operations remain deterministic, reversible, and observable under failure conditions.

### Scope

- **Applies to every pair (or trio) of domains** that share state or behavior
- **Includes CLI ↔ domain interactions** if they touch persistent data or external services
- **Must be treated as first-class contracts**, versioned and tested like domain-local ones

### File Placement

```
docs/contracts/resources/cross-domain/<DomainA>_<DomainB>_Guarantees.md
tests/contracts/cross-domain/test_<domain_a>_<domain_b>_guarantees.py
```

### Naming Conventions

- **Filenames** use PascalCase for domains, joined with underscores
- **Guarantee identifiers** use the format `G-#` (e.g., G-1, G-2)
- **Cross-domain test functions** must include the guarantee ID in the name (e.g., `test_g1_validates_enricher_metadata()`)
- **Domain names** in filenames match the actual domain names (Source, Enricher, Importer, Collection, CLI, Data)

### Required Sections

Each cross-domain guarantee document must include:

1. **Overview** – Describe the context and intent of collaboration
2. **Participating Domains** – Link to each domain's local contract
3. **Cross-Domain Guarantees (G-#)** – List all invariants that must remain true across both domains
4. **Failure & Rollback Policy** – Define rollback semantics and compensating behavior
5. **Enforcement** – Link to the test file(s) that verify each guarantee
6. **Versioning** – State coordination rules for minor/major changes

✅ **If any of these sections are missing, the document is non-compliant.**

### Test Enforcement

Each guarantee (G-#) must map to one or more tests that:

- Validate normal operation
- Simulate partial failure / rollback
- Assert integrity of shared data or events
- Confirm error propagation and message consistency

**CI must fail if any test in `tests/contracts/cross-domain/` fails.**

### Audit & Linting (Optional Future)

- A `validate_cross_domain_docs.py` script may be added to CI
- It enforces structure, required sections, and naming consistency

See also:

- [Contract migration guide](../../../../tests/CONTRACT_MIGRATION.md)
- Violations cause CI failure before test execution

### Governance Rules

- **New domains** must register their dependencies in the cross-domain index
- **PRs that modify an interface** used by another domain must include updated guarantees
- **Breaking changes** cannot merge without explicit sign-off from all affected domain owners
- **The README in `cross-domain/`** acts as the canonical map of all enforced relationships

### Version Control Guidance

To keep docs + tests + CI in sync:

- **Changes to cross-domain guarantees** must use semantic commits:
  - `docs(cross-domain):` for documentation-only changes
  - `test(cross-domain):` for test additions
  - `feat(cross-domain):` for new domain interactions
- **All affected domains** must bump their contract patch or minor version
- **Cross-domain changes** require coordination between participating domains
- **Breaking changes** must be coordinated across all affected domain contracts

### Benefits

✅ **Eliminates hidden coupling** - Forces explicit definition of domain interactions  
✅ **Provides testable, auditable domain boundaries** - Clear separation of concerns  
✅ **Enables confident refactors and future API extraction** - Microservices, API boundaries, etc.  
✅ **Aligns contract governance across the entire architecture** - Coordinated change management

---

## Current Cross-Domain Guarantees

### Source ↔ Enricher Guarantees

- **Document:** `Source_Enricher_Guarantees.md`
- **Tests:** `test_source_enricher_guarantees.py`
- **Status:** CROSS-DOMAIN (tests created, G-1 through G-4 enforced, G-5 planned)

### Source ↔ Importer Guarantees

- **Document:** `Source_Importer_Guarantees.md`
- **Tests:** `test_source_importer_guarantees.py`
- **Status:** CROSS-DOMAIN (tests created, G-1 through G-6 enforced)

### Source ↔ Collection Guarantees

- **Document:** `Source_Collection_Guarantees.md`
- **Tests:** `test_source_collection_guarantees.py`
- **Status:** CROSS-DOMAIN (tests created, G-1 through G-6 enforced)

### CLI ↔ Data Guarantees

- **Document:** `CLI_Data_Guarantees.md`
- **Tests:** `test_cli_data_guarantees.py`
- **Status:** CROSS-DOMAIN (tests created, G-1 through G-6 enforced)

## Compliance Checklist

When creating or updating cross-domain guarantees, verify:

- [ ] Document follows required sections (Overview, Participating Domains, Guarantees, Failure Policy, Enforcement, Versioning)
- [ ] Each guarantee (G-#) maps to specific tests
- [ ] Tests cover normal operation, failure scenarios, and error handling
- [ ] CI integration is configured
- [ ] Cross-references to participating domain contracts are accurate
- [ ] Status is updated in `CONTRACT_MIGRATION.md`
- [ ] Naming conventions are followed (PascalCase domains, G-# identifiers, test function naming)
- [ ] Semantic commit conventions are used for changes
- [ ] All affected domain contracts are version-bumped

## See Also

- [CONTRACT_MIGRATION.md](../../../../tests/CONTRACT_MIGRATION.md) - Cross-domain status tracking
- [CLI_CHANGE_POLICY.md](../CLI_CHANGE_POLICY.md) - Governance policy
- [CONTRACT_TEST_GUIDELINES.md](../CONTRACT_TEST_GUIDELINES.md) - Test guidelines
