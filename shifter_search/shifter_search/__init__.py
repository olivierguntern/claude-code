"""Recherche documentaire hybride pour les publications du Shift.

Chaîne : PDF -> paragraphes -> lemmes -> index BM25 (SQLite FTS5)
                             -> embeddings gelés (multilingual-e5)
         requête -> BM25 + vecteurs -> fusion RRF -> passages citables.

Aucun modèle génératif : les résultats sont toujours des passages existants.
"""

__version__ = "0.1.0"
