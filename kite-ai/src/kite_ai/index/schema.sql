-- kite-ai/src/kite_ai/index/schema.sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA temp_store = MEMORY;

CREATE TABLE IF NOT EXISTS files_meta (
    file_id INTEGER PRIMARY KEY,
    abs_path TEXT UNIQUE NOT NULL,
    file_name TEXT NOT NULL DEFAULT '',
    headings TEXT NOT NULL DEFAULT '',
    inode INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL,
    platform_badge TEXT NOT NULL, -- '[Doc]', '[Code]', '[Win]', '[Android]', '[macOS]'
    simhash64 INTEGER NOT NULL,
    canonical_file_id INTEGER,    -- Points to newest file in duplicate cluster
    fingerprint_25w TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    file_name,
    headings,
    fingerprint_25w,
    content='files_meta',
    content_rowid='file_id',
    tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS files_meta_ai AFTER INSERT ON files_meta BEGIN
    INSERT INTO files_fts(rowid, file_name, headings, fingerprint_25w)
    VALUES (new.file_id, new.file_name, new.headings, new.fingerprint_25w);
END;

CREATE TRIGGER IF NOT EXISTS files_meta_ad AFTER DELETE ON files_meta BEGIN
    INSERT INTO files_fts(files_fts, rowid, file_name, headings, fingerprint_25w)
    VALUES ('delete', old.file_id, old.file_name, old.headings, old.fingerprint_25w);
END;

CREATE TRIGGER IF NOT EXISTS files_meta_au AFTER UPDATE ON files_meta BEGIN
    INSERT INTO files_fts(files_fts, rowid, file_name, headings, fingerprint_25w)
    VALUES ('delete', old.file_id, old.file_name, old.headings, old.fingerprint_25w);
    INSERT INTO files_fts(rowid, file_name, headings, fingerprint_25w)
    VALUES (new.file_id, new.file_name, new.headings, new.fingerprint_25w);
END;

CREATE TABLE IF NOT EXISTS query_cache (
    query_hash TEXT PRIMARY KEY,
    max_mtime_ns INTEGER NOT NULL,
    response_json TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
