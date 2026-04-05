# INV-NO-GHOST-METHODS-001

**Domain:** systems

## Plain-language rule

No **production** module may ship methods that are empty stubs, `pass`, or `NotImplementedError` placeholders pretending to be real API.

## Why it exists

Ghost API surface misleads callers and can invoke **silent no-ops** in production—especially dangerous next to single-authority rules.

## What it constrains

- **All** production modules in Core (and the engineering norm extends to the whole repo by policy intent).

## Failure mode if violated

Callers assume behavior exists; production hits no-op paths; incidents look like “logic bugs” but are **missing implementation** disguised as API.
