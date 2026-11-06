"""Indexation : PDF -> passages -> SQLite (FTS5 + thèmes), puis embeddings en lot.

Idempotent : un PDF dont le sha256 n'a pas changé n'est pas retraité ; un PDF modifié
remplace entièrement l'ancienne version. Les identifiants de passage sont des hash stables.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import unicodedata
from pathlib import Path

from .chunk import build_passages
from .db import delete_doc
from .embed import Embedder, embedding_text, vec_to_blob
from .extract import extract
from .text import lemmas, normalize
from .themes import TaxonomyTagger


def slugify(stem: str) -> str:
    s = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "doc"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def make_passage_id(doc_id: str, section: str, text: str) -> str:
    return hashlib.sha1(f"{doc_id}|{section}|{normalize(text)}".encode()).hexdigest()[:16]


def index_pdf(conn: sqlite3.Connection, path: str | Path, tagger: TaxonomyTagger | None = None) -> tuple[str, int, str]:
    """Retourne (doc_id, nombre de passages ajoutés, 'indexed' | 'unchanged')."""
    path = Path(path)
    sha = sha256_file(path)
    doc_id = slugify(path.stem)
    row = conn.execute("SELECT sha256 FROM docs WHERE doc_id = ?", (doc_id,)).fetchone()
    if row and row["sha256"] == sha:
        return doc_id, 0, "unchanged"
    if row:
        delete_doc(conn, doc_id)

    ex = extract(path)
    passages = build_passages(ex.blocks)
    added = 0
    with conn:
        conn.execute(
            "INSERT INTO docs(doc_id, path, title, sha256, n_pages) VALUES (?,?,?,?,?)",
            (doc_id, str(path), ex.title, sha, ex.n_pages),
        )
        for ordinal, p in enumerate(passages):
            lem, sec_lem = lemmas(p.text), lemmas(p.section)
            cur = conn.execute(
                """INSERT OR IGNORE INTO passages(passage_id, doc_id, ordinal, page, section, text, lemmas)
                   VALUES (?,?,?,?,?,?,?)""",
                (make_passage_id(doc_id, p.section, p.text), doc_id, ordinal, p.page, p.section, p.text, " ".join(lem)),
            )
            if cur.rowcount == 0:  # passage identique déjà présent dans ce document
                continue
            pid = cur.lastrowid
            conn.execute(
                "INSERT INTO passages_fts(rowid, lemmas, section_lemmas) VALUES (?,?,?)",
                (pid, " ".join(lem), " ".join(sec_lem)),
            )
            if tagger:
                for theme, n_terms in tagger.tag(lem + sec_lem).items():
                    conn.execute(
                        "INSERT INTO passage_themes(passage_id, theme, score, source) VALUES (?,?,?, 'taxonomy')",
                        (pid, theme, float(n_terms)),
                    )
            added += 1
    return doc_id, added, "indexed"


def embed_pending(conn: sqlite3.Connection, embedder: Embedder, batch_size: int = 64) -> int:
    """Calcule les embeddings manquants pour ce modèle (une seule fois par passage)."""
    rows = conn.execute(
        """SELECT p.id, p.section, p.text, d.title FROM passages p JOIN docs d ON d.doc_id = p.doc_id
           WHERE p.id NOT IN (SELECT passage_id FROM embeddings WHERE model = ?) ORDER BY p.id""",
        (embedder.name,),
    ).fetchall()
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        vecs = embedder.encode_passages([embedding_text(r["title"], r["section"], r["text"]) for r in batch])
        with conn:
            for r, v in zip(batch, vecs):
                conn.execute(
                    "INSERT OR REPLACE INTO embeddings(passage_id, model, dim, vec) VALUES (?,?,?,?)",
                    (r["id"], embedder.name, int(v.shape[0]), vec_to_blob(v)),
                )
    return len(rows)


def collect_pdfs(paths: list[str | Path]) -> list[Path]:
    out: list[Path] = []
    for p in map(Path, paths):
        out.extend(sorted(p.rglob("*.pdf")) if p.is_dir() else [p])
    return out


def index_paths(
    conn: sqlite3.Connection,
    paths: list[str | Path],
    embedder: Embedder | None = None,
    tagger: TaxonomyTagger | None = None,
) -> dict:
    stats = {"documents": 0, "unchanged": 0, "passages": 0, "embedded": 0, "failed": []}
    seen: dict[str, Path] = {}
    for pdf in collect_pdfs(paths):
        # doc_id = nom de fichier : deux PDF homonymes du même lot se remplaceraient l'un l'autre
        doc_id = slugify(pdf.stem)
        if doc_id in seen and seen[doc_id].resolve() != pdf.resolve():
            stats["failed"].append(f"{pdf}: identifiant {doc_id!r} déjà pris par {seen[doc_id]} (renommer l'un des fichiers)")
            continue
        seen[doc_id] = pdf
        try:
            _, added, status = index_pdf(conn, pdf, tagger)
        except Exception as exc:  # un PDF corrompu ne doit pas bloquer le lot
            stats["failed"].append(f"{pdf}: {exc}")
            continue
        stats["unchanged" if status == "unchanged" else "documents"] += 1
        stats["passages"] += added
    if embedder is not None:
        stats["embedded"] = embed_pending(conn, embedder)
    return stats
