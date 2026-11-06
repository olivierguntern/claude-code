"""Thèmes : taxonomie contrôlée (appariement exact sur lemmes) + classifieur sur embeddings.

1. `TaxonomyTagger` : Aho-Corasick sur les séquences de lemmes. Explicable, traçable,
   limité aux termes de la liste. Le fichier YAML est validé par les Shifters.
2. `train_classifier` : régression logistique par thème sur les embeddings gelés, à partir
   de passages annotés (CSV `passage_id,theme`). Les passages annotés mais sans le thème
   servent de négatifs. Rappel : sans annotation, ne rien inférer.
"""

from __future__ import annotations

import csv
import sqlite3
from collections import defaultdict
from pathlib import Path

import ahocorasick
import joblib
import numpy as np
import yaml

from .embed import blob_to_vec
from .text import lemmas


def load_taxonomy(path: str | Path) -> dict[str, dict]:
    """YAML : `theme: {label: ..., terms: [...]}`."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    for theme, spec in data.items():
        if not isinstance(spec, dict) or not spec.get("terms"):
            raise ValueError(f"Thème {theme!r} : clé 'terms' (liste non vide) requise")
    return data


class TaxonomyTagger:
    def __init__(self, taxonomy: dict[str, dict]):
        self.labels = {t: spec.get("label", t) for t, spec in taxonomy.items()}
        self._automaton = ahocorasick.Automaton()
        for theme, spec in taxonomy.items():
            for term in spec["terms"]:
                lem = lemmas(term)
                if not lem:
                    continue
                key = " " + " ".join(lem) + " "
                _, themes = self._automaton.get(key, (key, set()))
                themes.add(theme)
                self._automaton.add_word(key, (key, themes))
        self._ready = len(self._automaton) > 0
        if self._ready:
            self._automaton.make_automaton()

    def tag(self, lemma_tokens: list[str]) -> dict[str, int]:
        """Nombre de termes distincts de la taxonomie trouvés, par thème."""
        if not self._ready:
            return {}
        haystack = " " + " ".join(lemma_tokens) + " "
        found: dict[str, set[str]] = defaultdict(set)
        for _, (key, themes) in self._automaton.iter(haystack):
            for theme in themes:
                found[theme].add(key.strip())
        return {theme: len(terms) for theme, terms in found.items()}


# --------------------------------------------------------------------------- annotation


def export_candidates(conn: sqlite3.Connection, out_csv: str | Path, limit_per_theme: int = 50) -> int:
    """Passages étiquetés par la taxonomie, à faire valider par des humains (colonne `valide`)."""
    rows = conn.execute(
        """SELECT p.passage_id, t.theme, t.score, d.title, p.page, p.section, p.text
           FROM passage_themes t JOIN passages p ON p.id = t.passage_id
           JOIN docs d ON d.doc_id = p.doc_id
           WHERE t.source = 'taxonomy' ORDER BY t.theme, t.score DESC"""
    ).fetchall()
    per_theme: dict[str, int] = defaultdict(int)
    n = 0
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["passage_id", "theme", "score", "document", "page", "section", "texte", "valide"])
        for r in rows:
            if per_theme[r["theme"]] >= limit_per_theme:
                continue
            per_theme[r["theme"]] += 1
            w.writerow([r["passage_id"], r["theme"], r["score"], r["title"], r["page"], r["section"], r["text"], ""])
            n += 1
    return n


def load_labels(csv_path: str | Path) -> dict[str, set[str]]:
    """Annotations `passage_id,theme[,valide]` -> {passage_id: {thèmes validés}}.

    Sans colonne `valide`, chaque ligne est un positif. Avec la colonne (fichier issu de
    `themes-export`) : 1/oui/true = positif ; 0/non/false = thème rejeté (le passage reste
    annoté, donc négatif pour ce thème) ; case vide = pas encore validé, ligne ignorée.
    """
    yes, no = {"1", "oui", "yes", "true", "vrai", "x"}, {"0", "non", "no", "false", "faux"}
    labels: dict[str, set[str]] = {}
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        has_valid_col = "valide" in (reader.fieldnames or [])
        for row in reader:
            pid, theme = row["passage_id"].strip(), row["theme"].strip()
            if not has_valid_col:
                labels.setdefault(pid, set()).add(theme)
                continue
            valid = (row.get("valide") or "").strip().lower()
            if valid in yes:
                labels.setdefault(pid, set()).add(theme)
            elif valid in no:
                labels.setdefault(pid, set())
            # sinon : non validé, ignoré
    return labels


# --------------------------------------------------------------------------- classifieur


def _load_vectors(conn: sqlite3.Connection, model: str, passage_ids: list[str] | None = None):
    rows = conn.execute(
        """SELECT p.id, p.passage_id, e.vec FROM embeddings e JOIN passages p ON p.id = e.passage_id
           WHERE e.model = ? ORDER BY p.id""",
        (model,),
    ).fetchall()
    if passage_ids is not None:
        wanted = set(passage_ids)
        rows = [r for r in rows if r["passage_id"] in wanted]
    ids = [r["id"] for r in rows]
    pids = [r["passage_id"] for r in rows]
    X = np.vstack([blob_to_vec(r["vec"]) for r in rows]) if rows else np.empty((0, 0), np.float32)
    return ids, pids, X


def train_classifier(
    conn: sqlite3.Connection,
    labels: dict[str, set[str]],
    embedder_name: str,
    model_path: str | Path,
    *,
    min_positives: int = 3,
    seed: int = 0,
) -> dict:
    """Entraîne un classifieur par thème ; retourne un rapport (effectifs, F1 en validation croisée)."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import f1_score
    from sklearn.model_selection import StratifiedKFold, cross_val_predict

    if not labels:
        raise ValueError("Aucune ligne validée dans le fichier d'annotation (colonne 'valide' vide ?).")
    _, pids, X = _load_vectors(conn, embedder_name, list(labels))
    if len(pids) == 0:
        raise ValueError("Aucun passage annoté n'a d'embedding pour ce modèle (indexer d'abord).")
    themes = sorted({t for ts in labels.values() for t in ts})
    models, report = {}, {"n_annotated": len(pids), "themes": {}}
    for theme in themes:
        y = np.array([theme in labels[p] for p in pids], dtype=int)
        n_pos, n_neg = int(y.sum()), int((1 - y).sum())
        info = {"positives": n_pos, "negatives": n_neg, "f1_cv": None}
        if n_pos < min_positives or n_neg < min_positives:
            info["skipped"] = f"moins de {min_positives} exemples d'une classe"
            report["themes"][theme] = info
            continue
        clf = LogisticRegression(C=4.0, class_weight="balanced", max_iter=2000)
        n_splits = min(5, n_pos, n_neg)
        if n_splits >= 2:
            cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
            pred = cross_val_predict(clf, X, y, cv=cv)
            info["f1_cv"] = round(float(f1_score(y, pred, zero_division=0)), 3)
        models[theme] = clf.fit(X, y)
        report["themes"][theme] = info
    scored = [i["f1_cv"] for i in report["themes"].values() if i["f1_cv"] is not None]
    report["f1_macro_cv"] = round(float(np.mean(scored)), 3) if scored else None
    joblib.dump({"models": models, "embedder": embedder_name}, model_path)
    return report


def apply_classifier(conn: sqlite3.Connection, model_path: str | Path, threshold: float = 0.6) -> int:
    """Étiquette tous les passages (source 'clf') avec une probabilité >= seuil."""
    bundle = joblib.load(model_path)
    ids, _, X = _load_vectors(conn, bundle["embedder"])
    if not ids:
        return 0
    n = 0
    with conn:
        conn.execute("DELETE FROM passage_themes WHERE source = 'clf'")
        for theme, clf in bundle["models"].items():
            proba = clf.predict_proba(X)[:, list(clf.classes_).index(1)]
            for pid, p in zip(ids, proba):
                if p >= threshold:
                    conn.execute(
                        "INSERT OR REPLACE INTO passage_themes(passage_id, theme, score, source) VALUES (?,?,?, 'clf')",
                        (pid, theme, float(p)),
                    )
                    n += 1
    return n
