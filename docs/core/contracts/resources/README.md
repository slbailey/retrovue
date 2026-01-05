# Retrovue Contracts

This directory defines operator-facing **contracts** — the binding legal interface between Retrovue’s CLI, tests, and data systems.  
Contracts define _what must be true_ before any code exists, ensuring consistency, safety, and predictability across the stack.

---

## Core Principles

1. **Contract-First Development** — Every command’s behavior is defined here _before_ implementation or testing begins.
2. **Two-Test Enforcement** — Each command has **exactly two test files**: one for CLI behavior and one for data behavior.
3. **Immutable Authority** — Code must conform to the contract. Contracts are never rewritten to justify code.
4. **Breaking Change = Breach of Contract** — Any CLI or data behavior change without contract updates is a breaking change.
5. **Traceability** — Every behavior (CLI or data) must map directly to an explicit rule (B-# or D-#).

---

## Contract Naming Convention

All contract documents MUST follow the `{Noun}{Verb}Contract.md` naming pattern:

- **Source contracts**: `SourceAddContract.md`, `SourceDiscoverContract.md`, `SourceIngestContract.md`
- **Collection contracts**: `CollectionIngestContract.md`, `CollectionWipeContract.md`
- **Enricher contracts**: `EnricherAddContract.md`, `EnricherListContract.md`
- **Asset contracts**: `AssetContract.md` (overview), `AssetShowContract.md`, `AssetListContract.md`, `AssetUpdateContract.md`, `AssetsDeleteContract.md`, `AssetsSelectContract.md`

This naming convention:

- **Distinguishes contracts from domain docs**: Domain docs use `{Domain}.md` (e.g., `Source.md`), contracts use `{Noun}{Verb}Contract.md`
- **Prevents confusion**: Clear separation between conceptual domain documentation and behavioral contracts
- **Enables systematic discovery**: Easy to identify all contract files with `*Contract.md` pattern
- **Supports tooling**: Automated tools can reliably identify contract files vs domain files

---

## Contract Structure

| Component              | Purpose                                            | Path Pattern                                          |
| ---------------------- | -------------------------------------------------- | ----------------------------------------------------- |
| **Contract Document**  | Defines full behavior, inputs, and guarantees      | `docs/contracts/resources/{Noun}{Verb}Contract.md`    |
| **CLI Contract Test**  | Validates user-facing CLI interaction              | `tests/contracts/test_{noun}_{verb}_contract.py`      |
| **Data Contract Test** | Validates persistence, integrity, and side effects | `tests/contracts/test_{noun}_{verb}_data_contract.py` |

---

## Contract Types: Domain Entities vs Runtime Infrastructure

Contracts fall into two categories based on what they govern:

### Domain Entity Contracts

**When to create**: For persisted domain entities that operators manage through CRUD operations.

**Pattern**: `{Entity}{Verb}Contract.md` where `{Entity}` is a domain entity (Channel, Source, Collection, Asset, etc.)

**Examples**:

- `ChannelAddContract.md` - Create a new channel
- `ChannelUpdateContract.md` - Update channel configuration
- `ChannelListContract.md` - List channels
- `SourceAddContract.md` - Register a new source
- `CollectionIngestContract.md` - Ingest content from a collection

**Characteristics**:

- Entity has persistent state in the database
- Operators perform CRUD operations (add, list, update, delete, show)
- Commands mutate or query domain entity state
- Contracts include Data Rules (D-#) for persistence guarantees
- Usually have both CLI and Data contract tests

### Runtime Infrastructure Contracts

**When to create**: For runtime system components that operators diagnose and validate, but do not manage through CRUD operations.

**Pattern**: `{Component}Contract.md` where `{Component}` is a runtime infrastructure component (MasterClock, ScheduleService, etc.)

**Examples**:

- `MasterClockContract.md` - Runtime time source validation and diagnostics
- `CLIRouterContract.md` - CLI command dispatch and registration architecture
- Future: `ScheduleServiceContract.md`, `ChannelManagerContract.md`, etc.

**Characteristics**:

- Component is a runtime service, not a persisted entity
- Operators validate and diagnose, not configure
- Commands are non-mutating validation/diagnostic operations
- Contracts focus on Behavior Rules (B-#) for validation guarantees
- Usually have CLI contract tests only (no data persistence to test)

**Why this distinction matters**:

- **Domain entities** are business concepts that operators actively manage and configure
- **Runtime infrastructure** are system services that execute the broadcast—operators diagnose them, not configure them
- Different contract patterns reflect these different use cases

---

## Documentation Split: CLI Reference vs Contracts

Retrovue separates **command syntax** from **behavioral specifications**:

### `docs/cli/` - Command Syntax Reference

**Purpose**: How to type commands, what flags are available, usage examples

**Contains**:
- Command syntax and grammar
- Available flags and arguments
- Usage examples
- Command discovery and navigation

**Use when**: You need to know "how to type the command" or "what flags are available"

**See**: [CLI Reference](../../cli/README.md)

### `docs/contracts/resources/` - Behavioral Specifications

**Purpose**: What the command guarantees, what rules it follows, exit codes, data effects

**Contains**:
- Behavior Rules (B-#) - CLI behavior requirements
- Data Rules (D-#) - Persistence and integrity guarantees
- Exit code specifications
- Safety and confirmation requirements
- Output format schemas

**Use when**: You need to know "what the command guarantees" or "what rules it must follow"

## CLI Contract Overview

All Retrovue CLI commands follow a single consistent grammar:

```
retrovue <noun> <verb> [options]
```

**Global Flags**

| Flag        | Description                                    |
| ----------- | ---------------------------------------------- |
| `--dry-run` | Preview what would be done without executing   |
| `--force`   | Bypass confirmation prompts (use with caution) |
| `--json`    | Output result in structured JSON format        |
| `--test-db` | Execute against an isolated test database      |

**Exit Codes**

| Code | Meaning                                     |
| ---- | ------------------------------------------- |
| `0`  | Success                                     |
| `1`  | Validation or runtime failure               |
| `2`  | Partial success (some recoverable failures) |
| `3`  | External dependency unreachable             |

**Safety Rules**

- Destructive verbs always require confirmation unless `--force` is provided.
- `--dry-run` must be supported by every operation.
- Test DB mode must guarantee no production side effects.

---

## Contract Document Format

Each `{Noun}{Verb}Contract.md` contract must include the following sections:

1. **Command Shape** — Syntax, verbs, flags, and usage examples
2. **Safety Expectations** — Prompts, confirmation, dry-run behavior
3. **Output Format** — Both human-readable and JSON schemas
4. **Exit Codes** — Success and error semantics
5. **Data Effects** — Database, filesystem, or transaction boundaries
6. **Behavior Rules (B-#)** — Operator-facing requirements
7. **Data Rules (D-#)** — Persistence and integrity guarantees
8. **Test Coverage Mapping** — Which test enforces which rules

Example rule notation:

```
B-1: Command MUST require --confirm for destructive operations.
D-2: Ingest operations MUST be atomic in --test-db mode.
```

---

## Behavior Contract Rules (B-#)

Behavioral guarantees for the CLI interface. Must use RFC 2119 terminology.

**Examples:**

- **B-1:** The command MUST refuse to run in production without `--confirm`.
- **B-2:** When `--json` is supplied, output MUST include `"status"`.
- **B-3:** On validation error, exit code MUST equal `1`.
- **B-4:** The `--dry-run` flag MUST preview all changes without committing.
- **B-5:** Interactive prompts MUST require typing “yes” exactly.

---

## Data Contract Rules (D-#)

Guarantees governing persistence, transactions, and cleanup.

**Examples:**

- **D-1:** Newly discovered collections MUST be created with `enabled=false`.
- **D-2:** Discovery MUST NOT toggle existing collections to `enabled=true`.
- **D-3:** Ingest operations MUST run atomically in `--test-db` mode.
- **D-4:** Sources referenced by PlaylogEvents MUST NOT be deleted.
- **D-5:** All data operations MUST occur within a single transaction.

---

## Test Coverage Mapping

Each rule (B-# or D-#) must be explicitly covered by one of the two test files.

| Rule Range | Enforced By                        |
| ---------- | ---------------------------------- |
| `B-1..B-5` | `test_source_add_contract.py`      |
| `D-1..D-6` | `test_source_add_data_contract.py` |

**Requirements**

- No rule may be untested.
- No test may assert behavior not defined in a rule.
- Each test must document the rule IDs it covers.

---

## Command Reference

### Sources

- `retrovue source list-types` — Show available source types.
- `retrovue source add --type <type>` — Register a new source.
- `retrovue source list` — Show configured sources.
- `retrovue source update <id>` — Update connection details.
- `retrovue source delete <id>` — Remove a source.
- `retrovue source discover <id>` — Discover collections for a source.
- `retrovue source ingest <id>` — Ingest content from a source.
- `retrovue source attach-enricher <source_id> <enricher_id>` — Attach ingest enrichers.
- `retrovue source detach-enricher <source_id> <enricher_id>` — Remove ingest enrichers.

### Collections

- `retrovue collection list [--source <id>]` — List all collections, optionally filtered by source.
- `retrovue collection show <id>` — Display detailed collection information.
- `retrovue collection update <id>` — Enable or configure collection ingest, manage enrichers, and path mappings.
- `retrovue collection wipe <id>` — Wipe all assets in a collection (**destructive**).
- `retrovue collection ingest <id>` — Ingest specific titles, seasons, or episodes.

### Enrichers

- `retrovue enricher list-types` — Show all enricher types.
- `retrovue enricher add --type <type>` — Create an enricher instance.
- `retrovue enricher list` — List all configured enrichers.
- `retrovue enricher remove <id>` — Delete an enricher instance.

### Producers & Channels

- `retrovue producer add --type <type>` — Add a producer instance.
- `retrovue producer list` — List all producers.
- `retrovue producer remove <id>` — Remove a producer.
- `retrovue channel list` — Show all channels with enrichers and producers.
- `retrovue channel attach-enricher <channel_id> <enricher_id>` — Attach a playout enricher.

---

## Enforcement Rules for AI Tools

Automated tools (Cursor, Copilot, etc.) must obey the same laws as humans.

1. **Source of Truth** — Contracts are the canonical definition of behavior.
2. **No Inference** — AI tools must not invent new flags, data fields, or flows.
3. **Naming Discipline** — Must use exact `test_{noun}_{verb}_contract.py` patterns.
4. **Bidirectional Linkage** — Contract ↔ tests mapping required in both directions.
5. **Change Control** — CLI or data logic changes require a contract update first.

---

## Governance Model

- All CLI verbs must have an active contract before merging into `main`.
- Contract updates require reviewer approval.
- Every pull request touching CLI or persistence layers must include:
  - Updated contract sections (if applicable)
  - Updated tests referencing rule IDs

**If it isn’t in the contract, it doesn’t exist.**

---

## Summary

Retrovue contracts are the backbone of trust between operators, developers, and automation.  
They define intent, guarantee safety, and enforce consistency across CLI, data, and AI-generated code.

Write the contract first. Test the contract second. Implement last.

---

## See Also

- [CLI Change Policy](CLI_CHANGE_POLICY.md) - Governance rules for enforced interfaces
- [Contract Test Guidelines](CONTRACT_TEST_GUIDELINES.md) - Testing standards
- [Architecture Overview](../../architecture/ArchitectureOverview.md)
- [Domain: Source](../../domain/Source.md)
- [Domain: Enricher](../../domain/Enricher.md)
- [Runtime: Channel Manager](../../runtime/channel_manager.md)
- [Developer: Plugin Authoring](../../developer/PluginAuthoring.md)
