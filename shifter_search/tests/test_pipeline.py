import shutil
import sys
import types

import numpy as np
import pytest

from shifter_search.db import connect
from shifter_search.embed import E5Embedder, HashingEmbedder
from shifter_search.evaluate import (
    evaluate,
    format_report,
    load_qrels,
    mrr_at_k,
    ndcg_at_k,
    paired_bootstrap,
    pool_candidates,
    recall_at_k,
)
from shifter_search.index import index_paths
from shifter_search.search import Searcher
from shifter_search.themes import apply_classifier, export_candidates, load_labels, train_classifier

PARAPHRASE = "protéger les habitants quand il fait très chaud"


def test_index_is_idempotent_and_replaces_changed_pdf(tmp_path, demo_pdfs, embedder):
    db = tmp_path / "t.db"
    conn = connect(db)
    first = index_paths(conn, demo_pdfs, embedder)
    again = index_paths(conn, demo_pdfs, embedder)
    assert first["documents"] == 2 and first["passages"] == 8 and first["embedded"] == 8
    assert again["unchanged"] == 2 and again["passages"] == 0 and again["embedded"] == 0
    # PDF modifié -> remplacé, pas dupliqué
    copy = tmp_path / "rapport-mobilite.pdf"
    shutil.copy(demo_pdfs[1], copy)
    import pymupdf

    with pymupdf.open(copy) as d:
        d.set_metadata({"title": "Autre titre"})
        d.saveIncr()
    third = index_paths(connect(db), [copy], embedder)
    assert third["documents"] == 1
    n_docs = conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    n_pass = conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
    n_fts = conn.execute("SELECT COUNT(*) FROM passages_fts").fetchone()[0]
    assert (n_docs, n_pass, n_fts) == (2, 8, 8)


def test_homonymous_pdfs_in_one_batch_are_reported_not_overwritten(tmp_path, demo_pdfs):
    for sub, src in (("a", demo_pdfs[0]), ("b", demo_pdfs[1])):
        (tmp_path / sub).mkdir()
        shutil.copy(src, tmp_path / sub / "synthese.pdf")
    conn = connect(tmp_path / "t.db")
    stats = index_paths(conn, [tmp_path])
    assert stats["documents"] == 1 and len(stats["failed"]) == 1
    assert "déjà pris" in stats["failed"][0]
    (path,) = [r[0] for r in conn.execute("SELECT path FROM docs")]
    assert path.endswith("a/synthese.pdf")
    assert conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0] == stats["passages"]


def test_passage_ids_are_stable_across_databases(tmp_path, demo_pdfs):
    ids = []
    for name in ("a.db", "b.db"):
        conn = connect(tmp_path / name)
        index_paths(conn, demo_pdfs)
        ids.append({r[0] for r in conn.execute("SELECT passage_id FROM passages")})
    assert ids[0] == ids[1] and len(ids[0]) == 8


def test_lexical_finds_exact_terms_with_section_and_page(db_path, embedder):
    hits = Searcher(db_path, embedder).search("retrait-gonflement des argiles", k=3, mode="lexical")
    assert hits[0].section.endswith("Sécheresses et bâtiments")
    assert hits[0].page == 1 and hits[0].doc_id == "rapport-adaptation"
    assert "argiles" in hits[0].snippet
    assert hits[0].lexical_rank == 1 and hits[0].dense_rank is None


def test_hybrid_recovers_paraphrase_without_shared_words(db_path, embedder):
    searcher = Searcher(db_path, embedder)
    lexical = searcher.search(PARAPHRASE, k=10, mode="lexical")
    hybrid = searcher.search(PARAPHRASE, k=3, mode="hybrid")
    target = "Canicules et santé des populations"
    assert not any(h.section.endswith(target) for h in lexical)  # BM25 seul : aucun mot commun
    assert hybrid[0].section.endswith(target)
    assert hybrid[0].dense_rank == 1 and hybrid[0].lexical_rank is None


def test_dense_only_and_unknown_mode(db_path, embedder):
    assert Searcher(db_path, embedder).search(PARAPHRASE, k=1, mode="dense")[0].dense_rank == 1
    with pytest.raises(ValueError):
        Searcher(db_path, embedder).search("x", mode="inconnu")
    with pytest.raises(RuntimeError):
        Searcher(db_path, None).search("vélo", mode="hybrid")
    assert Searcher(db_path, None).search("vélo", mode="lexical")  # lexical sans embedder


def test_taxonomy_themes_and_facet_filter(db_path, embedder):
    searcher = Searcher(db_path, embedder)
    hits = searcher.search("chaleur", k=10, mode="hybrid")
    heat = next(h for h in hits if h.section.endswith("Canicules et santé des populations"))
    assert "adaptation" in heat.themes
    only_attenuation = searcher.search("chaleur", k=10, mode="hybrid", theme="attenuation")
    assert only_attenuation and all("attenuation" in h.themes for h in only_attenuation)
    assert not any("Canicules" in h.section for h in only_attenuation)


def test_query_of_stopwords_only_returns_nothing_lexical(db_path, embedder):
    assert Searcher(db_path, embedder).search("de la et le", mode="lexical") == []


def test_metrics_known_values():
    rels = {"a": 2, "b": 1}
    assert ndcg_at_k(["a", "b"], rels) == pytest.approx(1.0)
    assert ndcg_at_k(["x", "b", "a"], rels) == pytest.approx((1 / 1.5849625 + 2 / 2) / (2 + 1 / 1.5849625), rel=1e-6)
    assert recall_at_k(["a", "x"], rels, k=2) == 0.5
    assert mrr_at_k(["x", "y", "b"], rels) == pytest.approx(1 / 3)
    assert ndcg_at_k(["a"], {}) == 0.0
    diff, lo, hi = paired_bootstrap([0.1, 0.2, 0.3, 0.4], [0.2, 0.3, 0.4, 0.5])
    assert diff == pytest.approx(0.1) and lo <= diff <= hi


def test_pool_and_eval_roundtrip(tmp_path, db_path, embedder):
    searcher = Searcher(db_path, embedder)
    pool_csv = tmp_path / "pool.csv"
    n = pool_candidates(searcher, [PARAPHRASE], pool_csv, depth=5)
    assert n >= 1
    # annotation simulée : la section « Canicules » est pertinente
    import csv

    rows = list(csv.DictReader(open(pool_csv, encoding="utf-8")))
    with open(tmp_path / "qrels.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["query", "passage_id", "grade"])
        for r in rows:
            w.writerow([r["query"], r["passage_id"], 2 if "Canicules" in r["section"] else 0])
    result = evaluate(searcher, load_qrels(tmp_path / "qrels.csv"), k=5)
    assert result["mean"]["hybrid"]["ndcg"] == pytest.approx(1.0)
    assert result["mean"]["lexical"]["ndcg"] == 0.0
    assert "hybride - lexical" not in format_report(result)  # une seule requête : pas d'IC
    assert "hybrid" in format_report(result)


def test_theme_export_train_apply(tmp_path, db_path, embedder):
    work = tmp_path / "themes.db"
    shutil.copy(db_path, work)
    conn = connect(work)
    out = tmp_path / "a_valider.csv"
    assert export_candidates(conn, out) >= 6
    # validation simulée : toutes les lignes exportées sont jugées correctes
    import csv

    rows = list(csv.DictReader(open(out, encoding="utf-8")))
    labels_csv = tmp_path / "labels.csv"
    with open(labels_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["passage_id", "theme", "valide"])
        for r in rows:
            w.writerow([r["passage_id"], r["theme"], "1"])
    labels = load_labels(labels_csv)
    report = train_classifier(conn, labels, embedder.name, tmp_path / "clf.joblib", min_positives=2)
    assert report["n_annotated"] == len(labels)
    assert any("skipped" not in info for info in report["themes"].values())
    n = apply_classifier(conn, tmp_path / "clf.joblib", threshold=0.5)
    assert n > 0
    assert conn.execute("SELECT COUNT(*) FROM passage_themes WHERE source='clf'").fetchone()[0] == n


def test_load_labels_blank_rejected_and_validated(tmp_path):
    path = tmp_path / "l.csv"
    path.write_text(
        "passage_id,theme,valide\n"
        "p1,adaptation,1\n"       # positif
        "p1,mobilite,0\n"         # rejeté : p1 reste annoté
        "p2,adaptation,0\n"       # rejeté
        "p3,adaptation,\n",       # non validé : ignoré
        encoding="utf-8",
    )
    assert load_labels(path) == {"p1": {"adaptation"}, "p2": set()}
    bare = tmp_path / "bare.csv"
    bare.write_text("passage_id,theme\np1,adaptation\np1,mobilite\n", encoding="utf-8")
    assert load_labels(bare) == {"p1": {"adaptation", "mobilite"}}


def test_cli_reports_clean_error_on_unvalidated_labels(tmp_path, db_path, demo_pdfs, capsys):
    from shifter_search.cli import main

    export = tmp_path / "e.csv"
    assert main(["themes-export", "--db", str(db_path), "--out", str(export), "--embedder", "hash"]) == 0
    assert main(["themes-train", "--db", str(db_path), "--labels", str(export), "--embedder", "hash"]) == 2
    assert "Aucune ligne validée" in capsys.readouterr().err


def test_e5_wrapper_applies_prefixes_and_normalizes(monkeypatch):
    calls = []

    class FakeModel:
        max_seq_length = 0

        def __init__(self, name, device=None):
            calls.append(("init", name, device))

        def encode(self, texts, batch_size, normalize_embeddings, show_progress_bar):
            calls.append(("encode", list(texts), normalize_embeddings))
            return np.ones((len(texts), 4), dtype=np.float32)

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=FakeModel))
    emb = E5Embedder("intfloat/multilingual-e5-small")
    emb.encode_passages(["un texte"])
    emb.encode_query("une requête")
    assert calls[0] == ("init", "intfloat/multilingual-e5-small", "cpu")
    assert calls[1][1] == ["passage: un texte"] and calls[1][2] is True
    assert calls[2][1] == ["query: une requête"]
    assert emb.name == "e5:intfloat/multilingual-e5-small"


def test_hashing_embedder_is_unit_norm_and_deterministic():
    emb = HashingEmbedder(64)
    a, b = emb.encode_query("canicule en ville"), emb.encode_query("canicule en ville")
    assert np.allclose(a, b) and np.linalg.norm(a) == pytest.approx(1.0)
    assert not np.any(emb.encode_query("de la et"))


def test_api_endpoints(db_path, embedder):
    from fastapi.testclient import TestClient

    from shifter_search.api import create_app

    client = TestClient(create_app(db_path, embedder))
    assert client.get("/health").json() == {"status": "ok", "passages": 8, "embedder": "concept-test"}
    r = client.get("/search", params={"q": PARAPHRASE, "k": 2})
    assert r.status_code == 200 and r.json()["results"][0]["section"].endswith("Canicules et santé des populations")
    assert client.get("/search", params={"q": "vélo", "mode": "bidon"}).status_code == 422
    themes = {t["theme"] for t in client.get("/themes").json()}
    assert {"adaptation", "attenuation", "mobilite"} <= themes
