"""API HTTP (FastAPI) : /search, /themes, /health.

    uvicorn "shifter_search.api:create_app" --factory     (variables SHIFTER_DB, SHIFTER_EMBEDDER)
"""

from __future__ import annotations

import os
from pathlib import Path

from . import __version__
from .db import connect
from .embed import Embedder, make_embedder
from .search import Searcher


def create_app(db_path: str | Path | None = None, embedder: Embedder | None = None):
    from fastapi import FastAPI, HTTPException, Query

    db_path = db_path or os.environ.get("SHIFTER_DB", "shifter.db")
    embedder = embedder or make_embedder()
    searcher = Searcher(db_path, embedder)
    app = FastAPI(title="Recherche dans les publications du Shift", version=__version__)

    @app.get("/health")
    def health():
        conn = connect(db_path)
        try:
            n = conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
        finally:
            conn.close()
        return {"status": "ok", "passages": n, "embedder": embedder.name}

    @app.get("/search")
    def search(
        q: str = Query(..., min_length=2, description="Requête en langage naturel"),
        k: int = Query(10, ge=1, le=50),
        mode: str = Query("hybrid", pattern="^(lexical|dense|hybrid)$"),
        theme: str | None = Query(None, description="Identifiant de thème (facette)"),
    ):
        try:
            hits = searcher.search(q, k=k, mode=mode, theme=theme)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"query": q, "mode": mode, "theme": theme, "results": [h.to_dict() for h in hits]}

    @app.get("/themes")
    def themes():
        conn = connect(db_path)
        try:
            rows = conn.execute(
                "SELECT theme, source, COUNT(*) AS n FROM passage_themes GROUP BY theme, source ORDER BY theme"
            ).fetchall()
        finally:
            conn.close()
        return [{"theme": r["theme"], "source": r["source"], "passages": r["n"]} for r in rows]

    return app
