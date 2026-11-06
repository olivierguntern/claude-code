"""Ligne de commande : index, search, themes-export, themes-train, pool, eval, serve."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .db import connect
from .embed import make_embedder
from .evaluate import evaluate, format_report, load_qrels, pool_candidates
from .index import index_paths
from .search import MODES, Searcher
from .themes import (
    TaxonomyTagger,
    apply_classifier,
    export_candidates,
    load_labels,
    load_taxonomy,
    train_classifier,
)


def _common() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--db", default=os.environ.get("SHIFTER_DB", "shifter.db"), help="fichier SQLite")
    p.add_argument("--embedder", choices=["e5", "hash"], default=None, help="'hash' = test hors-ligne, sans sémantique")
    p.add_argument("--e5-model", default=None, help="ex. intfloat/multilingual-e5-small")
    return p


def build_parser() -> argparse.ArgumentParser:
    common = _common()
    parser = argparse.ArgumentParser(prog="shifter-search", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("index", parents=[common], help="indexer des PDF (fichiers ou dossiers)")
    p.add_argument("paths", nargs="+")
    p.add_argument("--taxonomy", help="fichier YAML de thèmes")
    p.add_argument("--no-embed", action="store_true", help="index lexical uniquement")

    p = sub.add_parser("search", parents=[common], help="rechercher")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=10)
    p.add_argument("--mode", choices=MODES, default="hybrid")
    p.add_argument("--theme")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("themes-export", parents=[common], help="exporter les thèmes de la taxonomie à valider")
    p.add_argument("--out", default="themes_a_valider.csv")
    p.add_argument("--limit", type=int, default=50, help="passages par thème")

    p = sub.add_parser("themes-train", parents=[common], help="entraîner le classifieur sur les annotations")
    p.add_argument("--labels", required=True, help="CSV passage_id,theme[,valide]")
    p.add_argument("--model-out", default=None)
    p.add_argument("--threshold", type=float, default=0.6)

    p = sub.add_parser("pool", parents=[common], help="CSV de candidats à annoter (pooling)")
    p.add_argument("--queries", required=True, help="fichier texte, une requête par ligne")
    p.add_argument("--out", default="a_annoter.csv")
    p.add_argument("--depth", type=int, default=20)

    p = sub.add_parser("eval", parents=[common], help="comparer lexical / dense / hybride")
    p.add_argument("--qrels", required=True, help="CSV query,passage_id,grade")
    p.add_argument("-k", type=int, default=10)

    p = sub.add_parser("serve", parents=[common], help="lancer l'API HTTP")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    return parser


def _print_hits(hits) -> None:
    if not hits:
        print("Aucun résultat.")
    for i, h in enumerate(hits, start=1):
        ranks = f"BM25 #{h.lexical_rank or '-'} | vecteurs #{h.dense_rank or '-'}"
        print(f"{i:>2}. {h.doc_title}, p. {h.page}  [{h.section or 'sans section'}]  (score {h.score:.4f} ; {ranks})")
        if h.themes:
            print(f"    thèmes : {', '.join(h.themes)}")
        print(f"    {h.snippet}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2


def _run(args: argparse.Namespace) -> int:
    embedder = make_embedder(args.embedder, args.e5_model)

    if args.cmd == "index":
        conn = connect(args.db)
        tagger = TaxonomyTagger(load_taxonomy(args.taxonomy)) if args.taxonomy else None
        stats = index_paths(conn, args.paths, None if args.no_embed else embedder, tagger)
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 1 if stats["failed"] else 0

    if args.cmd == "search":
        hits = Searcher(args.db, embedder).search(args.query, k=args.k, mode=args.mode, theme=args.theme)
        if args.json:
            print(json.dumps([h.to_dict() for h in hits], ensure_ascii=False, indent=2))
        else:
            _print_hits(hits)
        return 0

    if args.cmd == "themes-export":
        n = export_candidates(connect(args.db), args.out, args.limit)
        print(f"{n} lignes écrites dans {args.out} (remplir la colonne 'valide' : 1 / 0).")
        return 0

    if args.cmd == "themes-train":
        conn = connect(args.db)
        model_out = args.model_out or f"{args.db}.themes.joblib"
        report = train_classifier(conn, load_labels(args.labels), embedder.name, model_out)
        n = apply_classifier(conn, model_out, args.threshold)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"{n} étiquettes 'clf' écrites (seuil {args.threshold}).")
        return 0

    if args.cmd == "pool":
        queries = [q.strip() for q in Path(args.queries).read_text(encoding="utf-8").splitlines() if q.strip()]
        n = pool_candidates(Searcher(args.db, embedder), queries, args.out, args.depth)
        print(f"{n} candidats écrits dans {args.out} (remplir 'grade' : 0 / 1 / 2).")
        return 0

    if args.cmd == "eval":
        result = evaluate(Searcher(args.db, embedder), load_qrels(args.qrels), k=args.k)
        print(format_report(result))
        return 0

    if args.cmd == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(args.db, embedder), host=args.host, port=args.port)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
