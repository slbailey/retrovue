# Scheduling Domain Contracts

This module provides validation contracts for the scheduling domain, enforcing structural integrity and playout safety.

## Overview

The scheduling contracts validate:
- **ScheduleDayContract**: Ensures generated schedule days are consistent
- **PlaylogEventContract**: Guarantees playout events are valid and correctly timed

> **Note:** SchedulePlanInvariantsContract and ProgramContract were retired per RETA-88 Option B. The DSL + ScheduleRevision/ScheduleItem path is the sole scheduling authority.

## Exceptions

- `ScheduleValidationError`: Base exception for all scheduling validation errors
- `ScheduleDayValidationError`: Raised when schedule day validation fails
- `PlaylogEventValidationError`: Raised when playlog event validation fails
