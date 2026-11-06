"""Recherche : BM25 (FTS5 sur lemmes) + similarité vectorielle exacte, fusion RRF.

Trois modes : `lexical`, `dense`, `hybrid` (défaut). Chaque résultat est un passage
existant (document, page, section) avec le rang obtenu dans chaque classement, ce qui
rend le résultat explicable et comparable entre modes.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .db import connect
from .embed import Embedder, blob_to_vec
from .fusion import rrf
from .text import best_sentence, lemmas

MODES = ("lexical", "dense", "hybrid")


@dataclass
class Hit:
    passage_id: str
    doc_id: str
    doc_title: str
    page: int
    section: str
    text: str
    snippet: str
    score: float
    lexical_rank: int | None = None
    dense_rank: int | None = None
    themes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class DenseIndex:
    """Matrice (n, d) en mémoire, recherche exacte par produit scalaire (vecteurs normalisés).

    100 000 passages x 768 dimensions float32 ~ 307 Mo ; la requête reste de l'ordre de la
    dizaine de millisecondes. Au-delà, passer à un index approximatif (pgvector, Qdrant).
    """

    def __init__(self, ids: np.ndarray, mat: np.ndarray):
        self.ids, self.mat = ids, mat

    @classmethod
    def load(cls, conn: sqlite3.Connection, model: str) -> "DenseIndex":
        rows = conn.execute(
            "SELECT passage_id, vec FROM embeddings WHERE model = ? ORDER BY passage_id", (model,)
        ).fetchall()
        if not rows:
            return cls(np.empty(0, dtype=np.int64), np.empty((0, 0), dtype=np.float32))
        ids = np.fromiter((r[0] for r in rows), dtype=np.int64, count=len(rows))
        return cls(ids, np.vstack([blob_to_vec(r[1]) for r in rows]))

    def search(self, qvec: np.ndarray, limit: int, allowed: set[int] | None = None) -> list[tuple[int, float]]:
        if not len(self.ids) or not np.any(qvec):
            return []
        scores = self.mat @ qvec
        if allowed is not None:
            scores = np.where(np.isin(self.ids, np.fromiter(allowed, dtype=np.int64)), scores, -np.inf)
        n = min(limit, len(scores))
        top = np.argpartition(-scores, n - 1)[:n]
        top = top[np.argsort(-scores[top])]
        return [(int(self.ids[i]), float(scores[i])) for i in top if np.isfinite(scores[i])]


def fts_query(lemma_tokens: list[str]) -> str:
    """Requête FTS5 : lemmes distincts entre guillemets, reliés par OR (le BM25 fait le tri)."""
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in dict.fromkeys(lemma_tokens))


class Searcher:
    def __init__(self, db_path: str | Path, embedder: Embedder | None = None, rrf_k: int = 60):
        self.db_path = Path(db_path)
        self.embedder = embedder
        self.rrf_k = rrf_k
        self._dense: DenseIndex | None = None

    def reload(self) -> None:
        """À appeler après une nouvelle indexation (recharge la matrice de vecteurs)."""
        self._dense = None

    # -- classements ---------------------------------------------------------------

    def _lexical(self, conn, qlem: list[str], limit: int, theme: str | None) -> list[tuple[int, float]]:
        if not qlem:
            return []
        sql = "SELECT rowid, bm25(passages_fts, 1.0, 3.0) AS s FROM passages_fts WHERE passages_fts MATCH ?"
        params: list = [fts_query(qlem)]
        if theme:
            sql += " AND rowid IN (SELECT passage_id FROM passage_themes WHERE theme = ?)"
            params.append(theme)
        sql += " ORDER BY s LIMIT ?"
        params.append(limit)
        return [(r[0], -r[1]) for r in conn.execute(sql, params)]  # bm25() : plus petit = meilleur

    def _dense_search(self, conn, query: str, limit: int, theme: str | None) -> list[tuple[int, float]]:
        if self.embedder is None:
            raise RuntimeError("Un embedder est requis pour les modes 'dense' et 'hybrid'.")
        if self._dense is None:
            self._dense = DenseIndex.load(conn, self.embedder.name)
        allowed = None
        if theme:
            allowed = {r[0] for r in conn.execute("SELECT passage_id FROM passage_themes WHERE theme = ?", (theme,))}
        return self._dense.search(self.embedder.encode_query(query), limit, allowed)

    # -- API publique --------------------------------------------------------------

    def search(
        self, query: str, k: int = 10, mode: str = "hybrid", theme: str | None = None, candidates: int = 50
    ) -> list[Hit]:
        if mode not in MODES:
            raise ValueError(f"mode inconnu : {mode!r} (attendu : {', '.join(MODES)})")
        conn = connect(self.db_path)
        try:
            qlem = lemmas(query)
            lex = self._lexical(conn, qlem, candidates, theme) if mode in ("lexical", "hybrid") else []
            den = self._dense_search(conn, query, candidates, theme) if mode in ("dense", "hybrid") else []
            lex_rank = {pid: r for r, (pid, _) in enumerate(lex, start=1)}
            den_rank = {pid: r for r, (pid, _) in enumerate(den, start=1)}
            if mode == "lexical":
                fused = lex
            elif mode == "dense":
                fused = den
            else:
                fused = rrf([[p for p, _ in lex], [p for p, _ in den]], k=self.rrf_k)
            top = fused[:k]
            return self._hydrate(conn, top, lex_rank, den_rank, qlem)
        finally:
            conn.close()

    def _hydrate(self, conn, top, lex_rank, den_rank, qlem) -> list[Hit]:
        if not top:
            return []
        ids = [int(p) for p, _ in top]
        marks = ",".join("?" * len(ids))
        rows = {
            r["id"]: r
            for r in conn.execute(
                f"""SELECT p.id, p.passage_id, p.doc_id, d.title, p.page, p.section, p.text
                    FROM passages p JOIN docs d ON d.doc_id = p.doc_id WHERE p.id IN ({marks})""",
                ids,
            )
        }
        themes: dict[int, list[str]] = {}
        for r in conn.execute(
            f"SELECT passage_id, theme FROM passage_themes WHERE passage_id IN ({marks}) ORDER BY score DESC", ids
        ):
            if r["theme"] not in themes.setdefault(r["passage_id"], []):
                themes[r["passage_id"]].append(r["theme"])
        hits = []
        for pid, score in top:
            r = rows[int(pid)]
            hits.append(
                Hit(
                    passage_id=r["passage_id"],
                    doc_id=r["doc_id"],
                    doc_title=r["title"],
                    page=r["page"],
                    section=r["section"],
                    text=r["text"],
                    snippet=best_sentence(r["text"], qlem),
                    score=float(score),
                    lexical_rank=lex_rank.get(pid),
                    dense_rank=den_rank.get(pid),
                    themes=themes.get(int(pid), []),
                )
            )
        return hits
