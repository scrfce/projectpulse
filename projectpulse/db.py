"""SQLite-хранилище (схема вручную, см. docs/architecture.md — ER-модель)."""
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS repos(name TEXT PRIMARY KEY, path TEXT, head TEXT);
CREATE TABLE IF NOT EXISTS commits(repo TEXT, hash TEXT, author TEXT, ts INTEGER,
    message TEXT, is_fix INTEGER, PRIMARY KEY(repo, hash));
CREATE TABLE IF NOT EXISTS file_changes(repo TEXT, hash TEXT, path TEXT, added INTEGER, deleted INTEGER);
CREATE INDEX IF NOT EXISTS ix_fc_repo_hash ON file_changes(repo, hash);
CREATE TABLE IF NOT EXISTS files(repo TEXT, path TEXT, blob TEXT, loc INTEGER, cc INTEGER,
    max_cc INTEGER, PRIMARY KEY(repo, path));
CREATE TABLE IF NOT EXISTS blobs(sha TEXT PRIMARY KEY, info TEXT);
CREATE TABLE IF NOT EXISTS graph_versions(id INTEGER PRIMARY KEY AUTOINCREMENT, repo TEXT,
    commit_hash TEXT, ts INTEGER, n_nodes INTEGER, n_edges INTEGER);
CREATE TABLE IF NOT EXISTS graph_nodes(version_id INTEGER, projection TEXT, node TEXT);
CREATE TABLE IF NOT EXISTS graph_edges(version_id INTEGER, projection TEXT, rel TEXT, src TEXT, dst TEXT);
CREATE INDEX IF NOT EXISTS ix_ge ON graph_edges(version_id, projection);
CREATE TABLE IF NOT EXISTS analysis_events(id INTEGER PRIMARY KEY AUTOINCREMENT, repo TEXT,
    kind TEXT, mode TEXT, started REAL, duration REAL, n_commits INTEGER, head TEXT);
CREATE TABLE IF NOT EXISTS metrics(analysis_id INTEGER, name TEXT, scope TEXT, key TEXT, value REAL);
CREATE INDEX IF NOT EXISTS ix_m ON metrics(analysis_id, name);
CREATE TABLE IF NOT EXISTS rule_results(analysis_id INTEGER, rule TEXT, severity TEXT,
    message TEXT, details TEXT);
"""


def open_db(path):
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn
