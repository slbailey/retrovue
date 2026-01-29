## Channel Validate Contract

## Purpose

Non‑mutating validation of Channel rows. Operators use this as a quick sanity check before making changes (e.g., grid/offset/anchor updates) or doing schedule rebuilds. Single pass over channels; no pagination; no cross‑entity checks.

---

## Invocation

```
retrovue channel validate [<uuid-or-slug>] [--id <uuid-or-slug>] [--json] [--strict] [--test-db]
```

- No identifier ⇒ validate all channels.
- If multiple identifiers are supplied, precedence is: `--id` over positional.
- On not found, exit 1 with a clear message; in `--json`, return `{"status":"error","violations":[],"warnings":[]}` plus an error string.

---

## Behavior

- Non‑mutating; read‑only; single pass over Channel rows.
- Validates per row only; independent of schedules/templates.
- `--strict` upgrades warnings to errors for exit code purposes.

---

## Rules (CHN codes)

- CHN-003 (error): `grid_block_minutes ∈ {15,30,60}`.
- CHN-004 (error): `block_start_offsets_minutes` is a JSON array, non‑empty, integers in 0–59, sorted, unique.
- CHN-005 (error): Every offset divisible by grid (`offset % grid_block_minutes == 0`).
- CHN-006 (error): `programming_day_start.seconds == 00` and `programming_day_start.minute ∈ block_start_offsets_minutes`.
- CHN-001 (error): `slug` is lowercase kebab, non‑empty, unique (case‑insensitive); `title` non‑empty.
- CHN-014 (warning): `grid_block_minutes == 60` with non‑zero offsets.
- CHN-015 (warning): Sparse/nonstandard offsets (e.g., singleton non‑zero).

Warnings do not fail unless `--strict`.

---

## Output

### Human (terse)

- Single target: `OK` or short lines like `CHN-005: alignment fail`.
- All‑mode: one line per channel; final `Violations: X, Warnings: Y`.
- Use `--json` for tooling—human output is for operators.

### JSON (authoritative)

```json
{
  "status": "ok",
  "channels": [ { "id": "422de...", "status": "ok" } ],
  "violations": [
    { "code": "CHN-006", "field": "programming_day_start", "message": "Minute must be in allowed offsets", "id": "422de..." }
  ],
  "warnings": [
    { "code": "CHN-015", "field": "block_start_offsets_minutes", "message": "Singleton non-zero offset is unusual", "id": "422de..." }
  ],
  "totals": { "violations": 0, "warnings": 1 }
}
```

JSON is authoritative for machine consumption; human output is brief and not stable for parsing.

---

## Exit Codes

- `0`: OK (or warnings only unless `--strict`).
- `2`: Violations present (or warnings with `--strict`).
- `1`: Not‑found or infrastructure error (DB/session).

---

## Examples

```bash
# Validate all channels (human)
retrovue channel validate

# Validate single by slug (JSON)
retrovue channel validate hbo --json

# Validate with strict mode (warnings become errors)
retrovue channel validate --strict
```

---

## See also

- [Channel Contract](ChannelContract.md)
- [Channel Add](ChannelAddContract.md)
- [Channel Update](ChannelUpdateContract.md)
- [Channel List](ChannelListContract.md)
- [Channel Show](ChannelShowContract.md)
- [Channel Delete](ChannelDeleteContract.md)

