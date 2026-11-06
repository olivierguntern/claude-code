"""Normalisation du français : lemmes, mots vides, phrases.

Lemmatisation par dictionnaire (simplemma) : rapide, sans modèle, sans contexte.
La liste de mots vides est volontairement courte et modifiable.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from simplemma import lemmatize, simple_tokenizer, split_sentences

STOPWORDS = frozenset(
    """
    a ai aient ainsi alors après as au aucun aussi autre autres aux avant avec avoir
    bien car ce ceci cela celle celles celui ces cet cette ceux chaque comme comment
    dans de depuis des dès deux doit donc dont du elle elles en encore entre es est
    et eu eue eues eus eux faire fait fois furent hui ici il ils je la le les leur
    leurs lui ma mais me même mes moi mon ne nos notre nous on ont ou où par pas
    peut plus plusieurs pour pourquoi puis quand que quel quelle quelles quels qui
    quoi sa sans se ses si soit son sont sous sur ta tant te tel telle telles tels
    tes toi ton toujours tous tout toute toutes très trop tu un une vos votre vous y
    ça être étaient était étant été
    avoir pouvoir devoir falloir
    """.split()
)

# Élisions à retirer avant lemmatisation : l'adaptation -> adaptation, qu'il -> il
_ELISION = re.compile(r"^(?:[ldjmnstc]|qu|jusqu|lorsqu|puisqu|quelqu)['’]", re.IGNORECASE)


def normalize(text: str) -> str:
    """NFKC (ligatures, exposants : tCO₂e -> tCO2e), trait d'union conditionnel, espaces."""
    text = unicodedata.normalize("NFKC", text).replace("­", "")
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=200_000)
def _lemma(token: str) -> str:
    return lemmatize(token, lang="fr").lower()


def lemmas(text: str) -> list[str]:
    """Lemmes en minuscules, sans ponctuation ni mots vides (ordre conservé)."""
    out: list[str] = []
    for tok in simple_tokenizer(normalize(text)):
        tok = _ELISION.sub("", tok.lower())
        if not tok or not any(c.isalnum() for c in tok) or tok in STOPWORDS:
            continue
        lem = _lemma(tok).strip("-'’")
        if not lem or lem in STOPWORDS:
            continue
        if len(lem) < 2 and not lem.isdigit():
            continue
        out.append(lem)
    return out


def sentences(text: str) -> list[str]:
    return [s.strip() for s in split_sentences(text, lang="fr") if s.strip()]


def word_count(text: str) -> int:
    return len(text.split())


def best_sentence(text: str, query_lemmas: list[str], max_chars: int = 320) -> str:
    """Phrase du passage partageant le plus de lemmes avec la requête (extrait affiché)."""
    qset = set(query_lemmas)
    sents = sentences(text) or [text]
    best = max(sents, key=lambda s: (len(qset & set(lemmas(s))), -sents.index(s)))
    return best if len(best) <= max_chars else best[: max_chars - 1].rstrip() + "…"
