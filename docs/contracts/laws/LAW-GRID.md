# LAW-GRID

## Constitutional Principle

All scheduling boundaries snap to the channel grid.

No content may start or end at an off-grid time unless it is a carry-in from a prior broadcast day or a longform extension consuming whole additional grid blocks.

## Implications

- Zone boundaries must align to grid block boundaries defined by the channel (`grid_block_minutes`, `block_start_offsets_minutes`, `programming_day_start`).
- ScheduleDay slot times must be grid-aligned.
- PlaylogEvent fences must be grid-aligned.
- Carry-in content begins at the grid boundary of the receiving broadcast day; its origin time is not grid-constrained.
- Longform extension is permitted only by consuming one or more whole additional grid blocks.

## Violation

Any scheduling artifact whose content placement starts or ends at a time not coinciding with a valid grid boundary, excluding carry-in origins and declared longform extension blocks.
