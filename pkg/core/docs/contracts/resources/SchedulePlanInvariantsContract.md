# Schedule Plan Invariants Contract

**Key Invariant:** All SchedulePlans must satisfy **INV_PLAN_MUST_HAVE_FULL_COVERAGE**, requiring full 24-hour coverage (00:00–24:00) with no gaps. Plans are automatically initialized with a default test filler zone (SyntheticAsset, 00:00–24:00) if no zones are provided. Plans must contain one or more Zones whose combined coverage spans 00:00–24:00 with no gaps.

See [Domain: SchedulePlan](../../domain/SchedulePlan.md) for detailed domain documentation.