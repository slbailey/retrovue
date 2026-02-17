# Phase 02 – Ads, Promos, and Movie Packaging

**Status:** In Flight

## Objective
Automatically fill commercial breaks, promos, and movie-channel packaging elements (rating cards, intros, outros) based on audience metadata and compiled schedules.

## What Exists Today

### Traffic Manager v1 (DELIVERED)
- `pkg/core/src/retrovue/runtime/traffic_manager.py`
- Fills empty filler placeholders with a single filler asset
- Each break plays filler from offset 0 for exactly the break duration
- No looping, no rotation, no inventory tracking
- Pure function — deterministic, no side effects

### Playout Log Expander (DELIVERED)
- `pkg/core/src/retrovue/runtime/playout_log_expander.py`
- Two breakpoint classes:
  - **First-class:** From chapter markers in media files (deliberate, well-placed)
  - **Second-class:** Computed by dividing episode evenly (arbitrary, mid-scene)
- Ad block duration = (slot_duration - episode_duration) / num_breaks

### Segment Transitions (IN PROGRESS — Feb 2026)
- Configurable fade-out/fade-in for second-class breakpoints
- Linear video+audio fade to reduce jarring mid-scene cuts
- `TransitionType` enum + `transition_duration_ms` parameter
- Contract: `docs/contracts/coordination/SegmentTransitionContract.md`

## Remaining Deliverables
1. **Ad & promo metadata contract** (`docs/contracts/core/ads_metadata.md`) — NOT STARTED
2. **AdAssembler service** — selection engine for break slots — NOT STARTED
3. **Traffic Manager v2** — pool partitioning (bumper/promo/ad), rotation, frequency caps — NOT STARTED
4. **Movie block packaging** — rating cards, intros, outros as first-class segments — NOT STARTED
5. **Break template system** — duration, slot type, adjacency constraints — NOT STARTED

## Key Invariants
- Break templates describe duration, slot type, and adjacency constraints.
- Ads/promos carry structured metadata (audience tags, categories, embargo dates).
- Packaging assets (rating cards/intros) are treated as first-class SchedulableAssets.
- First-class breakpoints (chapter markers) get clean cuts; second-class get configurable fades.

## Open Tasks
- [x] Traffic Manager v1 (filler filling)
- [x] Playout log expander (two-class breakpoints)
- [ ] Segment transitions (fade for second-class breakpoints) — IN PROGRESS
- [ ] Finalize ad metadata schema + contract
- [ ] Implement AdAssembler selection engine + tests
- [ ] Traffic Manager v2 (pool partitioning, rotation, frequency caps)
- [ ] Movie block packaging (rating cards, intros, outros)
- [ ] Break template system
- [ ] CLI/preview output showing filled breaks for operator review

## Next Up
Complete segment transitions, then Traffic Manager v2 with pool partitioning.
