-- Retrovue Database Schema v1.2.2
-- Changes from v1.2.1:
-- - Added sync_enabled, last_full_sync_epoch, last_incremental_sync_epoch to libraries table
PRAGMA foreign_keys = ON;
BEGIN TRANSACTION;
-- ============ CORE ============
CREATE TABLE plex_servers (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  base_url TEXT NOT NULL,
  token TEXT NOT NULL,
  -- NEW in v1.2.1
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE libraries (
  id INTEGER PRIMARY KEY,
  server_id INTEGER NOT NULL REFERENCES plex_servers(id) ON DELETE CASCADE,
  plex_library_key TEXT NOT NULL,
  title TEXT NOT NULL,
  library_type TEXT NOT NULL,
  sync_enabled INTEGER NOT NULL DEFAULT 1,
  -- NEW in v1.2.2
  last_full_sync_epoch INTEGER,
  -- NEW in v1.2.2
  last_incremental_sync_epoch INTEGER,
  -- NEW in v1.2.2
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX uidx_libraries_server_key ON libraries(server_id, plex_library_key);
CREATE TABLE path_mappings (
  id INTEGER PRIMARY KEY,
  server_id INTEGER NOT NULL REFERENCES plex_servers(id) ON DELETE CASCADE,
  library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
  plex_path TEXT NOT NULL,
  local_path TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX uidx_pathmap_unique ON path_mappings(server_id, library_id, plex_path);
-- ============ SYSTEM CONFIG ============
CREATE TABLE system_config (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  description TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
-- ============ TV scaffolding (optional) ============
CREATE TABLE shows (
  id INTEGER PRIMARY KEY,
  server_id INTEGER NOT NULL REFERENCES plex_servers(id) ON DELETE CASCADE,
  library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
  plex_rating_key TEXT NOT NULL,
  title TEXT NOT NULL,
  year INTEGER,
  originally_available_at TEXT,
  summary TEXT,
  studio TEXT,
  artwork_url TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX uidx_shows_identity ON shows(server_id, library_id, plex_rating_key);
CREATE INDEX idx_shows_title_year ON shows(title, year);
CREATE TABLE seasons (
  id INTEGER PRIMARY KEY,
  show_id INTEGER NOT NULL REFERENCES shows(id) ON DELETE CASCADE,
  season_number INTEGER NOT NULL,
  plex_rating_key TEXT,
  title TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX uidx_seasons_show_season ON seasons(show_id, season_number);
-- ============ CONTENT (logical/editorial) ============
CREATE TABLE content_items (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (
    kind IN (
      'movie',
      'episode',
      'interstitial',
      'intro',
      'outro',
      'promo',
      'bumper',
      'clip',
      'ad',
      'unknown'
    )
  ),
  title TEXT,
  synopsis TEXT,
  duration_ms INTEGER,
  rating_system TEXT,
  rating_code TEXT,
  is_kids_friendly INTEGER DEFAULT 0 CHECK (is_kids_friendly IN (0, 1)),
  artwork_url TEXT,
  guid_primary TEXT,
  external_ids_json TEXT,
  metadata_updated_at INTEGER,
  -- EPOCH SECONDS (editorial freshness)
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),
  show_id INTEGER REFERENCES shows(id) ON DELETE
  SET NULL,
    season_id INTEGER REFERENCES seasons(id) ON DELETE
  SET NULL,
    season_number INTEGER,
    episode_number INTEGER
);
CREATE UNIQUE INDEX uidx_content_episode ON content_items(show_id, season_number, episode_number)
WHERE kind = 'episode'
  AND show_id IS NOT NULL;
CREATE TABLE content_tags (
  content_item_id INTEGER NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  namespace TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT,
  PRIMARY KEY (content_item_id, namespace, key)
);
CREATE INDEX idx_tags_ns_key ON content_tags(namespace, key);
CREATE TABLE content_editorial (
  content_item_id INTEGER PRIMARY KEY REFERENCES content_items(id) ON DELETE CASCADE,
  source_name TEXT,
  -- 'plex','tmm','manual'
  source_payload_json TEXT,
  original_title TEXT,
  original_synopsis TEXT,
  override_title TEXT,
  override_synopsis TEXT,
  override_updated_at INTEGER -- EPOCH SECONDS
);
-- ============ MEDIA (physical/technical) ============
CREATE TABLE media_files (
  id INTEGER PRIMARY KEY,
  server_id INTEGER NOT NULL REFERENCES plex_servers(id) ON DELETE CASCADE,
  library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
  content_item_id INTEGER REFERENCES content_items(id) ON DELETE
  SET NULL,
    plex_rating_key TEXT NOT NULL,
    file_path TEXT NOT NULL,
    size_bytes INTEGER,
    container TEXT,
    video_codec TEXT,
    audio_codec TEXT,
    width INTEGER,
    height INTEGER,
    bitrate INTEGER,
    frame_rate REAL,
    channels INTEGER,
    updated_at_plex INTEGER,
    -- EPOCH SECONDS from Plex
    first_seen_at INTEGER,
    -- EPOCH SECONDS
    last_seen_at INTEGER,
    -- EPOCH SECONDS
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX uidx_media_file_path ON media_files(server_id, file_path);
CREATE INDEX idx_media_updated_at_plex ON media_files(updated_at_plex);
CREATE TABLE content_item_files (
  content_item_id INTEGER NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  media_file_id INTEGER NOT NULL REFERENCES media_files(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'primary',
  PRIMARY KEY (content_item_id, media_file_id, role)
);
-- ============ MARKERS & AD BREAKS ============
CREATE TABLE media_markers (
  id INTEGER PRIMARY KEY,
  media_file_id INTEGER NOT NULL REFERENCES media_files(id) ON DELETE CASCADE,
  marker_kind TEXT NOT NULL CHECK (marker_kind IN ('chapter', 'ad_break', 'cue')),
  start_ms INTEGER NOT NULL,
  end_ms INTEGER,
  label TEXT,
  source TEXT NOT NULL CHECK (source IN ('file', 'manual', 'detected')),
  confidence REAL,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_markers_media_kind ON media_markers(media_file_id, marker_kind);
-- ============ SCHEDULING ============
CREATE TABLE channels (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  number TEXT,
  callsign TEXT,
  is_active INTEGER DEFAULT 1 CHECK (is_active IN (0, 1)),
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE schedule_blocks (
  id INTEGER PRIMARY KEY,
  channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  day_of_week INTEGER NOT NULL CHECK (
    day_of_week BETWEEN 0 AND 6
  ),
  -- 0=Sun..6=Sat
  start_time TEXT NOT NULL,
  -- 'HH:MM:SS'
  end_time TEXT NOT NULL,
  -- 'HH:MM:SS'
  strategy TEXT NOT NULL CHECK (
    strategy IN ('auto', 'series', 'specific', 'collection')
  ),
  constraints_json TEXT,
  ad_policy_id INTEGER,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_blocks_channel_dow ON schedule_blocks(channel_id, day_of_week, start_time);
CREATE TABLE schedule_instances (
  id INTEGER PRIMARY KEY,
  channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
  block_id INTEGER REFERENCES schedule_blocks(id) ON DELETE
  SET NULL,
    air_date TEXT NOT NULL,
    -- 'YYYY-MM-DD'
    start_time TEXT NOT NULL,
    -- 'HH:MM:SS'
    end_time TEXT NOT NULL,
    -- 'HH:MM:SS'
    content_item_id INTEGER REFERENCES content_items(id) ON DELETE
  SET NULL,
    show_id INTEGER REFERENCES shows(id) ON DELETE
  SET NULL,
    pick_strategy TEXT NOT NULL CHECK (
      pick_strategy IN ('auto', 'specific', 'series_next')
    ),
    status TEXT NOT NULL DEFAULT 'planned' CHECK (
      status IN ('planned', 'approved', 'played', 'canceled')
    ),
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_sched_instances_date ON schedule_instances(air_date, start_time);
-- ============ AD POLICIES ============
CREATE TABLE ad_policies (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  rules_json TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
-- ============ PLAY LOG ============
CREATE TABLE play_log (
  id INTEGER PRIMARY KEY,
  channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
  ts_start TEXT NOT NULL,
  -- ISO8601 TEXT
  ts_end TEXT,
  -- ISO8601 TEXT
  item_kind TEXT NOT NULL CHECK (
    item_kind IN (
      'program',
      'ad',
      'promo',
      'bumper',
      'clip',
      'unknown'
    )
  ),
  content_item_id INTEGER REFERENCES content_items(id) ON DELETE
  SET NULL,
    media_file_id INTEGER REFERENCES media_files(id) ON DELETE
  SET NULL,
    schedule_instance_id INTEGER REFERENCES schedule_instances(id) ON DELETE
  SET NULL,
    ad_block_seq INTEGER,
    notes TEXT
);
CREATE INDEX idx_playlog_time ON play_log(ts_start);
-- ============ DEFAULT CONFIG ============
INSERT INTO system_config(key, value, description)
VALUES (
    'default_plex_server_name',
    '',
    'Optional default server name'
  ) ON CONFLICT(key) DO NOTHING;
COMMIT;