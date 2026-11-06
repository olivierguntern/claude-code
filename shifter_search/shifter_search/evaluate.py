"""Évaluation : nDCG@k, recall@k, MRR@k par mode, intervalle bootstrap apparié.

Protocole prévu :
1. `pool` : pour chaque requête, réunit le top-N des trois modes dans un CSV ;
2. des annotateurs remplissent `grade` (0 = hors sujet, 1 = pertinent, 2 = très pertinent) ;
3. `eval` compare lexical / dense / hybride sur ces jugements.
Avec 30 à 50 requêtes la puissance statistique est limitée : lire l'intervalle, pas seulement la moyenne.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

from .search import MODES, Searcher

Qrels = dict[str, dict[str, int]]


def ndcg_at_k(ranked: list[str], rels: dict[str, int], k: int = 10) -> float:
    dcg = sum(rels.get(pid, 0) / math.log2(i + 2) for i, pid in enumerate(ranked[:k]))
    ideal = sorted(rels.values(), reverse=True)[:k]
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0


def recall_at_k(ranked: list[str], rels: dict[str, int], k: int = 10) -> float:
    relevant = {p for p, g in rels.items() if g > 0}
    return len(relevant & set(ranked[:k])) / len(relevant) if relevant else 0.0


def mrr_at_k(ranked: list[str], rels: dict[str, int], k: int = 10) -> float:
    for i, pid in enumerate(ranked[:k], start=1):
        if rels.get(pid, 0) > 0:
            return 1.0 / i
    return 0.0


def load_qrels(path: str | Path) -> Qrels:
    qrels: Qrels = defaultdict(dict)
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            grade = (row.get("grade") or "").strip()
            if grade == "":
                continue  # ligne non annotée
            qrels[row["query"].strip()][row["passage_id"].strip()] = int(grade)
    return dict(qrels)


def evaluate(searcher: Searcher, qrels: Qrels, modes=MODES, k: int = 10) -> dict:
    per_query: dict[str, dict[str, dict[str, float]]] = {m: {} for m in modes}
    for mode in modes:
        for query, rels in qrels.items():
            ranked = [h.passage_id for h in searcher.search(query, k=k, mode=mode)]
            per_query[mode][query] = {
                "ndcg": ndcg_at_k(ranked, rels, k),
                "recall": recall_at_k(ranked, rels, k),
                "mrr": mrr_at_k(ranked, rels, k),
            }
    mean = {
        m: {metric: float(np.mean([q[metric] for q in per_query[m].values()])) for metric in ("ndcg", "recall", "mrr")}
        for m in modes
    }
    return {"k": k, "n_queries": len(qrels), "per_query": per_query, "mean": mean}


def paired_bootstrap(a: list[float], b: list[float], n: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """Différence moyenne (b - a) et intervalle à 95 % par rééchantillonnage apparié des requêtes."""
    a_, b_ = np.asarray(a), np.asarray(b)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(a_), size=(n, len(a_)))
    diffs = (b_[idx] - a_[idx]).mean(axis=1)
    return float((b_ - a_).mean()), float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def format_report(result: dict) -> str:
    k = result["k"]
    lines = [f"{result['n_queries']} requêtes, k = {k}", f"{'mode':<10} {'nDCG@'+str(k):>9} {'recall@'+str(k):>10} {'MRR@'+str(k):>8}"]
    for mode, m in result["mean"].items():
        lines.append(f"{mode:<10} {m['ndcg']:>9.3f} {m['recall']:>10.3f} {m['mrr']:>8.3f}")
    modes = list(result["per_query"])
    if "lexical" in modes and "hybrid" in modes and result["n_queries"] >= 2:
        qs = list(result["per_query"]["lexical"])
        a = [result["per_query"]["lexical"][q]["ndcg"] for q in qs]
        b = [result["per_query"]["hybrid"][q]["ndcg"] for q in qs]
        diff, lo, hi = paired_bootstrap(a, b)
        lines.append(f"hybride - lexical (nDCG@{k}) : {diff:+.3f}  IC95 % [{lo:+.3f} ; {hi:+.3f}]")
    return "\n".join(lines)


def pool_candidates(searcher: Searcher, queries: list[str], out_csv: str | Path, depth: int = 20) -> int:
    """CSV à annoter : union des top-`depth` des trois modes, sans indiquer quel mode l'a retourné."""
    n = 0
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["query", "passage_id", "document", "page", "section", "texte", "grade"])
        for query in queries:
            seen: dict[str, object] = {}
            for mode in MODES:
                for hit in searcher.search(query, k=depth, mode=mode):
                    seen.setdefault(hit.passage_id, hit)
            for pid in sorted(seen):  # ordre neutre : le mode d'origine n'est pas révélé
                h = seen[pid]
                w.writerow([query, pid, h.doc_title, h.page, h.section, h.text, ""])
                n += 1
    return n
