"""Embeddings gelés (aucun entraînement) : multilingual-e5 sur CPU.

Règles propres à E5 : préfixe « passage: » à l'indexation, « query: » à la requête,
vecteurs normalisés L2 (le produit scalaire est alors un cosinus).
Choix du modèle : `intfloat/multilingual-e5-base` par défaut ; `-small` si l'indexation
dépasse le budget temps (environ 5 points de nDCG@10 en moins en recherche française,
selon MTEB-French / Granite Embedding).
"""

from __future__ import annotations

import os
from typing import Protocol

import numpy as np

DEFAULT_E5_MODEL = "intfloat/multilingual-e5-base"


class Embedder(Protocol):
    name: str

    def encode_passages(self, texts: list[str]) -> np.ndarray: ...
    def encode_query(self, text: str) -> np.ndarray: ...


class E5Embedder:
    """multilingual-e5 via sentence-transformers (chargement paresseux)."""

    def __init__(self, model_name: str = DEFAULT_E5_MODEL, batch_size: int = 32, device: str = "cpu"):
        self.model_name = model_name
        self.name = f"e5:{model_name}"
        self.batch_size = batch_size
        self.device = device
        self._model = None

    @property
    def model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("Installer l'extra : pip install 'shifter-search[e5]'") from exc
            model = SentenceTransformer(self.model_name, device=self.device)
            model.max_seq_length = 512
            self._model = model
        return self._model

    def _encode(self, texts: list[str]) -> np.ndarray:
        vecs = self.model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vecs, dtype=np.float32)

    def encode_passages(self, texts: list[str]) -> np.ndarray:
        return self._encode([f"passage: {t}" for t in texts])

    def encode_query(self, text: str) -> np.ndarray:
        return self._encode([f"query: {text}"])[0]


class HashingEmbedder:
    """Embedder LEXICAL de test (hashing trick) : aucune sémantique.

    Sert uniquement à valider la plomberie hors-ligne (indexation, fusion, API) quand
    le modèle e5 n'est pas disponible. Ne pas l'utiliser pour juger la qualité.
    """

    def __init__(self, dim: int = 256):
        self.dim = dim
        self.name = f"hash-{dim}"

    def _encode(self, texts: list[str]) -> np.ndarray:
        from sklearn.feature_extraction.text import HashingVectorizer

        from .text import lemmas

        vec = HashingVectorizer(n_features=self.dim, analyzer=lemmas, alternate_sign=True, norm="l2")
        return vec.transform(texts).toarray().astype(np.float32)

    def encode_passages(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts)

    def encode_query(self, text: str) -> np.ndarray:
        return self._encode([text])[0]


def make_embedder(kind: str | None = None, model: str | None = None) -> Embedder:
    """`kind` : 'e5' (défaut, variable SHIFTER_EMBEDDER) ou 'hash' (test)."""
    kind = (kind or os.environ.get("SHIFTER_EMBEDDER") or "e5").lower()
    if kind == "hash":
        return HashingEmbedder()
    if kind == "e5":
        return E5Embedder(model or os.environ.get("SHIFTER_E5_MODEL") or DEFAULT_E5_MODEL)
    raise ValueError(f"Embedder inconnu : {kind!r} (attendu : 'e5' ou 'hash')")


def vec_to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def blob_to_vec(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def embedding_text(doc_title: str, section: str, text: str) -> str:
    """Texte encodé : titre du document > section > passage (contexte pour l'embedder)."""
    head = " > ".join(p for p in (doc_title, section) if p)
    return f"{head}. {text}" if head else text
