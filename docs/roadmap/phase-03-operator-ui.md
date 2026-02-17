# Phase 03 – Operator Workflows & UI

**Status:** In Flight (partial delivery)

## Objective
Provide an approachable operator experience (CLI + web) for editing schedules, viewing compiled days, and previewing ad/packaging decisions.

## What Exists Today

### EPG Web UI (DELIVERED)
- `pkg/core/templates/epg/guide.html` — full channel guide with grid layout
- Channels listed with current/upcoming program blocks
- Click-to-watch: modal video player with HLS.js
- Splash screen with logo + "Please wait — buffering..." during cold start
- Smart buffer detection: splash hides only after 8s of buffered content
- Responsive layout with channel cards

### HLS Player (DELIVERED)
- `pkg/core/templates/player/watch.html` — standalone player page
- HLS.js with tuned buffer settings (liveSyncDurationCount: 4)
- Retry logic for manifest/level/fragment loading
- On-demand channel spinup (no background encoding when no viewers)

### FastAPI Server (DELIVERED)
- `pkg/core/src/retrovue/web/server.py` — serves EPG + API
- `/api/epg?date=YYYY-MM-DD` — returns compiled schedule data
- `/hls/<channel>/live.m3u8` — HLS stream endpoint
- Static asset serving (logo, CSS)

### CLI (DELIVERED)
- `retrovue start` — starts the full runtime (ProgramDirector + web server)
- Schedule compilation happens automatically on startup
- Channel configs loaded from `config/channels.json`
- DSL configs from `config/dsl/*.yaml`

## Remaining Deliverables
1. **Schedule editing UI** — web-based calendar/grid editor — NOT STARTED
2. **Preview/simulation tool** — renders a "day of air" timeline — NOT STARTED
3. **CLI enhancements** — `programming edit/apply/history` commands — NOT STARTED
4. **Operator permissions model** — role-based access — NOT STARTED

## Dependencies
- Phase 01 compiler: ✅ COMPLETE
- Phase 02 ad/packaging logic: IN PROGRESS

## Open Tasks
- [x] EPG web UI with channel guide
- [x] HLS player with splash + buffer management
- [x] FastAPI server + API endpoints
- [x] CLI `retrovue start` command
- [ ] Schedule editing web UI
- [ ] Day-of-air preview/simulation tool
- [ ] CLI edit/apply/history commands
- [ ] Operator permissions + roles

## Next Up
Schedule editing UI once Phase 02 traffic manager is more mature.
