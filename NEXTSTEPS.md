# RetroVue Phase 0 Playout Rules

> **Grid + Filler Model**

---

### 🌐 Core Principles

- **Time is the boss.**
- The channel operates in fixed grid blocks (e.g., **30 minutes**).
- **Programs must fit the clock**—never drift.
- All content **snaps to the grid**.

---

#### Example

- **Show:** *Cheers* episode  
  **Duration:** 24:17
- **Grid Block:** 30:00
- **Padding:** 5:43 (mandatory)

Any remainder in a block is always filled with **filler**—which, in the future, can be ad pods, bumpers, or promos.

---

### 🎞️ Filler as a Continuous Virtual Stream

- Use a **1-hour filler MP4** as a "virtual channel".
- **Filler offset calculation:**
  ```
  filler_offset = (master_clock - filler_epoch) % filler_duration
  ```
- **When filler is needed:**
  1. Seek into the filler file at `filler_offset`
  2. Play **exactly** for the padding duration
  3. **Hard stop** at the next grid boundary
- **Never restart** filler from 00:00 each time
- **Never let filler overrun** the grid

*This guarantees variety and preserves the linear illusion.*

---

### 📋 Playlog Construction (Per Block)

For **every grid block**:
```
block_start = HH:00 or HH:30
block_len   = 1800 seconds

program_len = media.duration
pad_len     = block_len - program_len

emit(program_segment)
emit(filler_segment(duration=pad_len))
```

---

### 🚦 Channel Startup (Join In Progress)

When a user tunes in:
```
now         = master_clock
block_start = floor_to_grid(now)
elapsed     = now - block_start
```
- **If** `elapsed < program_len` → seek into program at `elapsed`
- **Else** → seek into filler at `elapsed - program_len`

---

### Phase 0 Scope

- 1 channel
- Fixed 30-minute grid
- Sequential episodes
- 1 filler reel (1 hour)
- No chapter markers
- No ads (yet!)
- Hard grid alignment **always**

---

### 🚫 Non-Negotiable Rules

- **Never chain episodes** back-to-back.
- **Never let content** drift off the grid.
- **Always cut at grid boundaries.**

---

#### 🌱 Philosophy

> **Time is continuous. Content is replaceable.  
> The grid is sacred.**