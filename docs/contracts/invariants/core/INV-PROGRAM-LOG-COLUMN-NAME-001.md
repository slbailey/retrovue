# INV-PROGRAM-LOG-COLUMN-NAME-001 — Tier 1 Canonical Storage Column Name

## Status: ACTIVE

## Rule

1. The Tier 1 JSONB storage column on `program_log_days` is named `program_log_json`.
2. The retired name `compiled_json` MUST NOT appear in the ORM model or any
   non-migration code path.
3. This is a naming-only change. The column type (JSONB), nullability (`NOT NULL`),
   and contents are unchanged.
4. Historical Alembic migrations that reference the old column name are
   exempt — they describe the schema at the time they were written.

## Rationale

`compiled_json` was inherited from the pre-rename `CompiledProgramLog` entity.
After the Tier 1 entity became `ProgramLogDay`, the column name should reflect
the entity's domain semantics: it stores a **program log** in JSON form.

## Verification

- `ProgramLogDay.__table__.columns` contains `"program_log_json"`.
- `ProgramLogDay.__table__.columns` does NOT contain `"compiled_json"`.
- All attribute accesses use `row.program_log_json`.

## See Also

- `pkg/core/src/retrovue/domain/entities.py` — ORM definition
- `pkg/core/alembic/versions/20260303_rename_column_program_log_json.py` — migration
