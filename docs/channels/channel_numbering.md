# Channel Numbering Guidelines

RetroVue recommends grouping channels into number ranges to make navigation intuitive for viewers and stable for guide consumers (e.g. Plex Live TV).

## Requirements

- Each channel **MUST** define a `number` (or legacy `channel_number`) in its YAML configuration.
- `number` MUST be a **positive integer**.
- `number` MUST be **unique** across all channels.
- The same value is used as the **Plex GuideNumber** and for XMLTV `<channel id>`.

Channel numbers are configuration metadata and do **not** replace the canonical channel ID (e.g. `cheers-24-7`, `hbo`), which remains used for schedules, playlog, and internal APIs.

## Recommended segmentation

| Range     | Use case                    |
|----------|-----------------------------|
| 100–199  | 24/7 themed channels        |
| 200–299  | Movies / premium channels   |
| 300–399  | Cartoons / animation        |
| 400–499  | Sitcom / comedy             |
| 500–599  | Drama / scripted TV         |
| 600–699  | Reality / lifestyle         |
| 700–799  | Music channels              |
| 800–899  | News / talk                 |
| 900–949  | Special event channels      |
| 950–999  | Experimental / testing     |

Most RetroVue channels will initially fall into the **100–199 (24/7 themed)** range. Single-theme 24/7 channels (e.g. a channel that runs one show or franchise around the clock) should use numbers in this band so viewers can find them in a consistent block.

## Example configuration

```yaml
channels:
  - id: cheers-24-7
    number: 101
    name: "Cheers 24/7"

  - id: twilight-zone
    number: 110
    name: "The Twilight Zone 24/7"

  - id: night-court
    number: 120
    name: "Night Court 24/7"

  - id: hbo-movies
    number: 201
    name: "HBO Movies"
```

In the standard per-file format (one YAML file per channel), each file includes a top-level `number` (or `channel_number`). 24/7 themed channels use numbers in the 100–199 range:

```yaml
# config/channels/cheers-24-7.yaml
channel: cheers-24-7
number: 101
name: "Cheers 24/7"
# ...
```

```yaml
# config/channels/twilight-zone.yaml
channel: twilight-zone
number: 110
name: "The Twilight Zone 24/7"
# ...
```

```yaml
# config/channels/hbo-movies.yaml (movies / premium → 200–299)
channel: hbo-movies
number: 201
name: "HBO Movies"
# ...
```

## Stability

Channel numbers should remain **stable** once deployed. Changing a channel's number can cause guide remapping or duplicate-tuner behavior in clients like Plex. If you must renumber, plan for a config change and client re-scan.
