# INV-EPG-NONAUTHORITATIVE-FOR-PLAYOUT-001

**Domain:** playout

## Plain-language rule

**EPG must never decide** what plays, when to switch, which asset path, or offsets. Only the **execution plan / execution window** may drive those decisions. EPG may still be used for labels, logging enrichment, or viewer display **if** contracts allow.

## Why it exists

EPG is **derived** and may be stale or simplified relative to the locked execution stream. Using it as control creates a **second, unaccountable authority** next to ExecutionEntry.

## What it constrains

- **Service:** `channel-manager` playout decision path (and any runtime peer).
- **Entity:** `epg` is display-oriented relative to `execution-entry` / `playlog` (not a control substitute for either).

## Failure mode if violated

Wrong asset at a switch, boundary drift vs locked plan, and defects that **look** like playout bugs but are actually EPG misuse.
