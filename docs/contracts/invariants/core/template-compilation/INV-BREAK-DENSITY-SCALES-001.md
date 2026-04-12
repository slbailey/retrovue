# INV-BREAK-DENSITY-SCALES-001 — Break density scales with content runtime

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring a single template handles all content runtimes without template proliferation. Break count is derived from content runtime and `target_segment_minutes`, not hardcoded per template.

## Guarantee

Break density MUST scale with content runtime via `target_segment_minutes`. The compiler derives `floor(content_duration_minutes / target_segment_minutes)` as the initial break count, subject to chapter marker positions when available.

## Preconditions

Template has `target_segment_minutes` set and `strategy` is `chapter_markers_preferred` or `synthetic`.

## Observability

The compiler logs the derived break count alongside content runtime and `target_segment_minutes`. The ratio `content_duration / break_count` stays within the range defined by the template's segment minute parameters.

## Deterministic Testability

Apply a template with `target_segment_minutes: 11` to content of 22, 44, and 85 minutes. Verify break counts of approximately 2, 4, and 5 respectively. The same template produces proportionally correct break counts for any runtime.

## Failure Semantics

**Planning fault.** Fixed break count produces inappropriate break density — too many breaks in short content, too few in long content.

## Required Tests

- `server/tests/contracts/test_timeline_compilation_templates.py`

## Enforcement Evidence

TODO
