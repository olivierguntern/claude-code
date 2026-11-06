"""Schéma SQLite : documents, passages, index plein texte FTS5, embeddings, thèmes."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    doc_id     TEXT PRIMARY KEY,
    path       TEXT NOT NULL,
    title      TEXT NOT NULL,
    sha256     TEXT NOT NULL,
    n_pages    INTEGER NOT NULL,
    indexed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS passages (
    id         INTEGER PRIMARY KEY,
    passage_id TEXT NOT NULL UNIQUE,      -- hash stable (document, section, texte)
    doc_id     TEXT NOT NULL REFERENCES docs(doc_id),
    ordinal    INTEGER NOT NULL,
    page       INTEGER NOT NULL,
    section    TEXT NOT NULL,
    text       TEXT NOT NULL,
    lemmas     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_passages_doc ON passages(doc_id);

-- Index BM25 : rowid = passages.id ; le titre de section est pondéré plus fort à la requête.
CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
    lemmas, section_lemmas, tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS embeddings (
    passage_id INTEGER NOT NULL REFERENCES passages(id),
    model      TEXT NOT NULL,
    dim        INTEGER NOT NULL,
    vec        BLOB NOT NULL,             -- float32 normalisé L2
    PRIMARY KEY (passage_id, model)
);

CREATE TABLE IF NOT EXISTS passage_themes (
    passage_id INTEGER NOT NULL REFERENCES passages(id),
    theme      TEXT NOT NULL,
    score      REAL NOT NULL,
    source     TEXT NOT NULL,             -- 'taxonomy' | 'clf'
    PRIMARY KEY (passage_id, theme, source)
);
CREATE INDEX IF NOT EXISTS idx_themes_theme ON passage_themes(theme);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def delete_doc(conn: sqlite3.Connection, doc_id: str) -> None:
    """Supprime un document et tout ce qui en dépend (réindexation après modification)."""
    ids = [r["id"] for r in conn.execute("SELECT id FROM passages WHERE doc_id = ?", (doc_id,))]
    with conn:
        for i in ids:
            conn.execute("DELETE FROM passages_fts WHERE rowid = ?", (i,))
            conn.execute("DELETE FROM embeddings WHERE passage_id = ?", (i,))
            conn.execute("DELETE FROM passage_themes WHERE passage_id = ?", (i,))
        conn.execute("DELETE FROM passages WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM docs WHERE doc_id = ?", (doc_id,))
