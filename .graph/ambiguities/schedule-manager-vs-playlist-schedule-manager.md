# Ambiguity: ScheduleManager vs PlaylistScheduleManager

**Domain:** systems (disambiguation)

## Architectural role vs concrete service

| Concept | What it is | Graph target |
|---------|------------|--------------|
| **Schedule Manager / traffic (role)** | The planning-side component that **must** ground out in **Schedule → execution plan → playlog/events**; may emit **playlist-shaped** interchange where contracts lock that shape—**not** a second editorial root. | **Role name in contracts**; future or composite; **not** a single class by requirement. |
| **PlaylistScheduleManager** | **Concrete** Core service today: deterministic playlist producer for burn-in / contract locking. | `service:playlist-schedule-manager` |

## Resolution rule

- If the question is **“who implements playlist output now?”** → `playlist-schedule-manager`.
- If the question is **“who builds playlog / playlog plan?”** → **not** a single graph service: persisted plan is **scheduling-side** (horizon materialization from schedule/execution); **runtime** executable sequence is **`channel-manager`**’s path from that plan—see `entities/playout/playlog.md` and RetroVue glossary (Playlog Plan vs runtime playlog).
- If the question is **“who may talk to AIR?”** → **neither** the role nor the concrete service—only `channel-manager` (see `INV-SCHEDULEMANAGER-NO-AIR-ACCESS-001`).

## Relationships

See `relationships/cross-domain.yaml` (`ambiguity:schedule-manager-vs-playlist-schedule-manager`).
