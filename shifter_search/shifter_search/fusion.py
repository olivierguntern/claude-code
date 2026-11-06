"""Fusion de classements par Reciprocal Rank Fusion (RRF)."""

from __future__ import annotations

from collections.abc import Hashable, Sequence


def rrf(
    rankings: Sequence[Sequence[Hashable]],
    k: int = 60,
    weights: Sequence[float] | None = None,
) -> list[tuple[Hashable, float]]:
    """Score RRF : somme de poids / (k + rang), rang à partir de 1.

    Ne dépend que des rangs : pas de normalisation entre scores BM25 et cosinus.
    Retourne [(identifiant, score)] trié par score décroissant (égalités : ordre d'apparition).
    """
    weights = weights or [1.0] * len(rankings)
    scores: dict[Hashable, float] = {}
    for w, ranking in zip(weights, rankings):
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + w / (k + rank)
    order = {item: i for i, item in enumerate(scores)}
    return sorted(scores.items(), key=lambda kv: (-kv[1], order[kv[0]]))
