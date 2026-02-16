# Phase 02 – Ads, Promos, and Movie Packaging

**Status:** Planned

## Objective
Automatically fill commercial breaks, promos, and movie-channel packaging elements (rating cards, intros, outros) based on audience metadata and compiled schedules.

## Deliverables
1. **Ad & promo metadata contract** (`docs/contracts/core/ads_metadata.md`).
2. **AdAssembler service/module** that selects creatives for break slots given context.
3. **Movie block compiler extensions** that expand `movie_block` DSL entries into Playlog sequences (rating card → intro → feature → outro).
4. **Unit + property tests** validating slot fill rules, adjacency constraints, and packaging order.

## Key Invariants
- Break templates describe duration, slot type, and adjacency constraints.
- Ads/promos carry structured metadata (audience tags, categories, embargo dates).
- Packaging assets (rating cards/intros) are treated as first-class SchedulableAssets.

## Open Tasks (after Phase 01 is live)
- [ ] Finalize metadata schema + contract.
- [ ] Implement AdAssembler selection engine + tests.
- [ ] Extend DSL compiler to insert break slots & packaging instructions.
- [ ] Add CLI/preview output showing filled breaks for operator review.

## Next Up
Driven once Phase 01 code is merged; see `overview.md` for current status.
