# Contracts — authoritative index

**Contracts are normative.** They define what the system must do and guarantee. If code disagrees with a contract, **the code is wrong**. Fix the code or change the contract explicitly; do not treat the contract as advisory.

---

## Index

### Operational policies (_ops/)

| Document | Purpose |
|----------|---------|
| [_ops/UnitOfWorkContract.md](_ops/UnitOfWorkContract.md) | Observable guarantees for all DB-modifying operations: atomicity, consistency, isolation. |
| [_ops/ProductionSafety.md](_ops/ProductionSafety.md) | Protections for production environments during destructive operations. |
| [_ops/DestructiveOperationConfirmation.md](_ops/DestructiveOperationConfirmation.md) | Standardized confirmation and authorization for destructive CLI commands (`--force`, `--confirm`). |
| [_ops/SyncIdempotencyContract.md](_ops/SyncIdempotencyContract.md) | Sync commands produce the same final state when run repeatedly; no duplicates or corruption. |

### Root-level

| Document | Purpose |
|----------|---------|
| [ALIGNMENT_VERIFICATION.md](ALIGNMENT_VERIFICATION.md) | Verifies SchedulePlan alignment between domain model, entity, contracts, implementation, and tests. |
| [ZonesPatterns.md](ZonesPatterns.md) | Testable behavioral contracts for the Zones + SchedulableAssets scheduling model (grid, EPG, schedule generation). |

### Resources (CLI/usecase contracts)

| Document | Purpose |
|----------|---------|
| [resources/README.md](resources/README.md) | Contract system principles, naming, structure, and index of resource contracts. |
| [resources/CLI_CHANGE_POLICY.md](resources/CLI_CHANGE_POLICY.md) | Governance for CLI changes; contract-first process; no direct changes to governed interfaces. |
| [resources/CLIRouterContract.md](resources/CLIRouterContract.md) | CLI router/dispatcher behavior and registration. |
| [resources/AssetAttentionContract.md](resources/AssetAttentionContract.md) | Asset “attention” behavior contract. |
| [resources/AssetConfidenceContract.md](resources/AssetConfidenceContract.md) | Asset “confidence” behavior contract. |
| [resources/AssetContract.md](resources/AssetContract.md) | Asset domain overview and behavioral contract. |
| [resources/AssetListContract.md](resources/AssetListContract.md) | Asset list command: behavior, exit codes, output. |
| [resources/AssetResolveContract.md](resources/AssetResolveContract.md) | Asset resolve behavior contract. |
| [resources/AssetsDeleteContract.md](resources/AssetsDeleteContract.md) | Assets delete command: behavior, confirmation, data effects. |
| [resources/AssetShowContract.md](resources/AssetShowContract.md) | Asset show command: behavior, output shape. |
| [resources/AssetsSelectContract.md](resources/AssetsSelectContract.md) | Assets select command: behavior, filters, output. |
| [resources/AssetTaggingContract.md](resources/AssetTaggingContract.md) | Asset tagging behavior contract. |
| [resources/AssetUpdateContract.md](resources/AssetUpdateContract.md) | Asset update command: behavior, allowed updates, data effects. |
| [resources/ChannelAddContract.md](resources/ChannelAddContract.md) | Channel add command: behavior, validation, persistence. |
| [resources/ChannelContract.md](resources/ChannelContract.md) | Channel domain and behavioral contract. |
| [resources/ChannelDeleteContract.md](resources/ChannelDeleteContract.md) | Channel delete command: behavior, confirmation, cascade. |
| [resources/ChannelListContract.md](resources/ChannelListContract.md) | Channel list command: behavior, output shape. |
| [resources/ChannelManagerContract.md](resources/ChannelManagerContract.md) | ChannelManager runtime contract: discovery playlist, MPEG-TS stream. |
| [resources/ChannelShowContract.md](resources/ChannelShowContract.md) | Channel show command: behavior, output shape. |
| [resources/ChannelUpdateContract.md](resources/ChannelUpdateContract.md) | Channel update command: behavior, allowed updates. |
| [resources/ChannelValidateContract.md](resources/ChannelValidateContract.md) | Channel validate command: behavior, validation rules. |
| [resources/CollectionContract.md](resources/CollectionContract.md) | Collection domain and behavioral contract. |
| [resources/CollectionIngestContract.md](resources/CollectionIngestContract.md) | Collection ingest command: behavior, scope, data effects. |
| [resources/CollectionListContract.md](resources/CollectionListContract.md) | Collection list command: behavior, filters, output. |
| [resources/CollectionShowContract.md](resources/CollectionShowContract.md) | Collection show command: behavior, output shape. |
| [resources/CollectionUpdateContract.md](resources/CollectionUpdateContract.md) | Collection update command: sync, enrichers, path mapping. |
| [resources/CollectionWipeContract.md](resources/CollectionWipeContract.md) | Collection wipe command: behavior, confirmation, data effects. |
| [resources/EnricherAddContract.md](resources/EnricherAddContract.md) | Enricher add command: behavior, validation, persistence. |
| [resources/EnricherContract.md](resources/EnricherContract.md) | Enricher domain and behavioral contract. |
| [resources/EnricherListContract.md](resources/EnricherListContract.md) | Enricher list command: behavior, output shape. |
| [resources/EnricherListTypesContract.md](resources/EnricherListTypesContract.md) | Enricher list-types command: behavior, output shape. |
| [resources/EnricherRemoveContract.md](resources/EnricherRemoveContract.md) | Enricher remove command: behavior, confirmation, data effects. |
| [resources/EnricherUpdateContract.md](resources/EnricherUpdateContract.md) | Enricher update command: behavior, allowed updates. |
| [resources/MasterClockContract.md](resources/MasterClockContract.md) | MasterClock time authority: guarantees and diagnostic contract. |
| [resources/MetadataHandlerContract.md](resources/MetadataHandlerContract.md) | Metadata handler contract. |
| [resources/PlaylogEventContract.md](resources/PlaylogEventContract.md) | PlaylogEvent contract: persistence, query, validation. |
| [resources/ProgramAddContract.md](resources/ProgramAddContract.md) | Program add command: behavior, validation, persistence. |
| [resources/ProgramContract.md](resources/ProgramContract.md) | Program domain and behavioral contract. |
| [resources/ProgramDeleteContract.md](resources/ProgramDeleteContract.md) | Program delete command: behavior, confirmation, data effects. |
| [resources/ProgramListContract.md](resources/ProgramListContract.md) | Program list command: behavior, output shape. |
| [resources/ScheduleDayContract.md](resources/ScheduleDayContract.md) | ScheduleDay contract: generate, override, validate, persistence. |
| [resources/SchedulePlanAddContract.md](resources/SchedulePlanAddContract.md) | Schedule plan add command: behavior, validation, default zone. |
| [resources/SchedulePlanBuildContract.md](resources/SchedulePlanBuildContract.md) | Schedule plan build command: behavior, coverage guarantee. |
| [resources/SchedulePlanDeleteContract.md](resources/SchedulePlanDeleteContract.md) | Schedule plan delete command: behavior, blocking by schedule days. |
| [resources/SchedulePlanInvariantsContract.md](resources/SchedulePlanInvariantsContract.md) | Schedule plan invariants: coverage and consistency rules. |
| [resources/SchedulePlanListContract.md](resources/SchedulePlanListContract.md) | Schedule plan list command: behavior, output shape. |
| [resources/SchedulePlanShowContract.md](resources/SchedulePlanShowContract.md) | Schedule plan show command: behavior, output shape. |
| [resources/SchedulePlanUpdateContract.md](resources/SchedulePlanUpdateContract.md) | Schedule plan update command: behavior, allowed updates. |
| [resources/SourceAddContract.md](resources/SourceAddContract.md) | Source add command: behavior, validation, discovery option. |
| [resources/SourceContract.md](resources/SourceContract.md) | Source domain and behavioral contract. |
| [resources/SourceDeleteContract.md](resources/SourceDeleteContract.md) | Source delete command: behavior, confirmation, data effects. |
| [resources/SourceDiscoverContract.md](resources/SourceDiscoverContract.md) | Source discover command: behavior, collection discovery. |
| [resources/SourceIngestContract.md](resources/SourceIngestContract.md) | Source ingest command: behavior, scope (all enabled collections). |
| [resources/SourceListContract.md](resources/SourceListContract.md) | Source list command: behavior, filters, output shape. |
| [resources/SourceListTypesContract.md](resources/SourceListTypesContract.md) | Source list-types command: behavior, output shape. |
| [resources/SourceUpdateContract.md](resources/SourceUpdateContract.md) | Source update command: behavior, allowed updates. |

### Cross-domain guarantees (resources/cross-domain/)

| Document | Purpose |
|----------|---------|
| [resources/cross-domain/README.md](resources/cross-domain/README.md) | Index for cross-domain guarantee documents. |
| [resources/cross-domain/CLI_Data_Guarantees.md](resources/cross-domain/CLI_Data_Guarantees.md) | Guarantees between CLI behavior and data operations (validation, rollback, partial success). |
| [resources/cross-domain/Source_Collection_Guarantees.md](resources/cross-domain/Source_Collection_Guarantees.md) | Guarantees between Source and Collection (discovery, ingestibility, partial ingest). |
| [resources/cross-domain/Source_Enricher_Guarantees.md](resources/cross-domain/Source_Enricher_Guarantees.md) | Guarantees between Source and Enricher (compatibility, attachment). |
| [resources/cross-domain/Source_Importer_Guarantees.md](resources/cross-domain/Source_Importer_Guarantees.md) | Guarantees between Source and Importer (type validation, discovery, interface compliance). |

### CLI command reference (cli/)

| Document | Purpose |
|----------|---------|
| [cli/README.md](cli/README.md) | CLI command reference index: syntax, routing, command groups. |
| [cli/source.md](cli/source.md) | Source command group: syntax, arguments, usage. |
| [cli/channel.md](cli/channel.md) | Channel command group: syntax, arguments, usage. |
| [cli/collection.md](cli/collection.md) | Collection command group: syntax, arguments, usage. |
| [cli/asset.md](cli/asset.md) | Asset command group: syntax, arguments, usage. |
| [cli/enricher.md](cli/enricher.md) | Enricher command group: syntax, arguments, usage. |
| [cli/producer.md](cli/producer.md) | Producer command group: syntax, arguments, usage. |
| [cli/runtime.md](cli/runtime.md) | Runtime command group: syntax, arguments, usage. |

---

For contract-first principles, naming, and test pairing, see [resources/README.md](resources/README.md).
