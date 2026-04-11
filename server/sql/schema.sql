-- Retrovue Database Schema (Stable)
-- This is a stable reference to the current schema
-- For version-specific changes, see retrovue_schema_vX.Y.Z.sql files
PRAGMA foreign_keys = ON;
BEGIN TRANSACTION;
-- ============ CORE ============
CREATE TABLE plex_servers (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  base_url TEXT NOT NULL,
  token TEXT NOT NULL,
  is_default INTEGER NOT NULL DEFAULT 0,
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
  last_full_sync_epoch INTEGER,
  last_incremental_sync_epoch INTEGER,
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
-- ============ CONTENT TABLES ============
CREATE TABLE movies (
  id INTEGER PRIMARY KEY,
  plex_rating_key TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  year INTEGER,
  summary TEXT,
  duration_ms INTEGER,
  content_rating TEXT,
  rating REAL,
  imdb_id TEXT,
  tmdb_id TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE episodes (
  id INTEGER PRIMARY KEY,
  plex_rating_key TEXT NOT NULL UNIQUE,
  show_title TEXT NOT NULL,
  season_number INTEGER NOT NULL,
  episode_number INTEGER NOT NULL,
  title TEXT NOT NULL,
  year INTEGER,
  summary TEXT,
  duration_ms INTEGER,
  content_rating TEXT,
  rating REAL,
  imdb_id TEXT,
  tmdb_id TEXT,
  tvdb_id TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
-- MEDIA FILES (polymorphic via two FKs; exactly one must be set)
CREATE TABLE media_files (
  id INTEGER PRIMARY KEY,
  movie_id INTEGER,
  episode_id INTEGER,
  plex_file_path TEXT NOT NULL,
  local_file_path TEXT,
  file_size_bytes INTEGER,
  video_codec TEXT,
  audio_codec TEXT,
  width INTEGER,
  height INTEGER,
  duration_ms INTEGER,
  container TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),
  CHECK (
    (movie_id IS NOT NULL) <> (episode_id IS NOT NULL)
  ),
  FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE,
  FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE
);
CREATE INDEX idx_media_files_movie_id ON media_files(movie_id);
CREATE INDEX idx_media_files_episode_id ON media_files(episode_id);
CREATE INDEX idx_media_files_plex_path ON media_files(plex_file_path);
CREATE INDEX idx_media_files_local_path ON media_files(local_file_path);
-- Prevent duplicate file-paths per movie/episode
CREATE UNIQUE INDEX IF NOT EXISTS uidx_media_movie_path ON media_files(movie_id, plex_file_path)
WHERE movie_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uidx_media_episode_path ON media_files(episode_id, plex_file_path)
WHERE episode_id IS NOT NULL;
-- ============ SYNC TRACKING ============
CREATE TABLE sync_log (
  id INTEGER PRIMARY KEY,
  library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
  sync_type TEXT NOT NULL CHECK (sync_type IN ('full', 'incremental')),
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  completed_at TEXT,
  items_scanned INTEGER DEFAULT 0,
  items_mapped INTEGER DEFAULT 0,
  items_inserted INTEGER DEFAULT 0,
  items_updated INTEGER DEFAULT 0,
  items_unchanged INTEGER DEFAULT 0,
  errors_count INTEGER DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
  error_message TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_sync_log_library ON sync_log(library_id);
CREATE INDEX idx_sync_log_started ON sync_log(started_at);
-- ============ VIEWS ============
CREATE VIEW library_sync_status AS
SELECT l.id,
  l.plex_library_key,
  l.title,
  l.library_type,
  l.sync_enabled,
  l.last_full_sync_epoch,
  l.last_incremental_sync_epoch,
  ps.name as server_name,
  ps.base_url as server_url,
  CASE
    WHEN l.last_full_sync_epoch IS NULL THEN 'Never'
    ELSE datetime(l.last_full_sync_epoch, 'unixepoch')
  END as last_full_sync_display,
  CASE
    WHEN l.last_incremental_sync_epoch IS NULL THEN 'Never'
    ELSE datetime(l.last_incremental_sync_epoch, 'unixepoch')
  END as last_incremental_sync_display
FROM libraries l
  JOIN plex_servers ps ON l.server_id = ps.id;
-- ============ TRIGGERS ============
CREATE TRIGGER update_plex_servers_timestamp
AFTER
UPDATE ON plex_servers FOR EACH ROW BEGIN
UPDATE plex_servers
SET updated_at = datetime('now')
WHERE id = NEW.id;
END;
CREATE TRIGGER update_libraries_timestamp
AFTER
UPDATE ON libraries FOR EACH ROW BEGIN
UPDATE libraries
SET updated_at = datetime('now')
WHERE id = NEW.id;
END;
CREATE TRIGGER update_path_mappings_timestamp
AFTER
UPDATE ON path_mappings FOR EACH ROW BEGIN
UPDATE path_mappings
SET updated_at = datetime('now')
WHERE id = NEW.id;
END;
CREATE TRIGGER update_movies_timestamp
AFTER
UPDATE ON movies FOR EACH ROW BEGIN
UPDATE movies
SET updated_at = datetime('now')
WHERE id = NEW.id;
END;
CREATE TRIGGER update_episodes_timestamp
AFTER
UPDATE ON episodes FOR EACH ROW BEGIN
UPDATE episodes
SET updated_at = datetime('now')
WHERE id = NEW.id;
END;
CREATE TRIGGER update_media_files_timestamp
AFTER
UPDATE ON media_files FOR EACH ROW BEGIN
UPDATE media_files
SET updated_at = datetime('now')
WHERE id = NEW.id;
END;
-- ============ INITIAL DATA ============
INSERT INTO system_config (key, value, description)
VALUES (
    'schema_version',
    '1.2.3',
    'Current database schema version'
  ),
  (
    'app_version',
    '0.1.0',
    'Current application version'
  );
COMMIT;