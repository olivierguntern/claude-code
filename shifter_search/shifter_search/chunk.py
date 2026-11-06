"""Découpage en passages citables : section, page, texte de 40 à 250 mots environ."""

from __future__ import annotations

from dataclasses import dataclass

from .extract import Block
from .text import sentences, word_count

SECTION_SEP = " > "


@dataclass
class Passage:
    page: int
    section: str
    text: str


def split_long(text: str, max_words: int, overlap_sentences: int = 1) -> list[str]:
    """Coupe un texte long aux frontières de phrases, avec recouvrement."""
    if word_count(text) <= max_words:
        return [text]
    chunks: list[list[str]] = []
    current: list[str] = []
    for sent in sentences(text):
        words = sent.split()
        if len(words) > max_words:  # phrase unique trop longue : coupe dure
            if current:
                chunks.append(current)
                current = []
            for i in range(0, len(words), max_words):
                chunks.append([" ".join(words[i : i + max_words])])
            continue
        if current and word_count(" ".join(current + [sent])) > max_words:
            chunks.append(current)
            current = current[-overlap_sentences:] if overlap_sentences else []
            if current and word_count(" ".join(current + [sent])) > max_words:
                current = []
        current.append(sent)
    if current:
        chunks.append(current)
    return [" ".join(c) for c in chunks]


def build_passages(
    blocks: list[Block],
    *,
    min_words: int = 40,
    max_words: int = 250,
    overlap_sentences: int = 1,
) -> list[Passage]:
    """Regroupe les blocs de corps par section.

    Un paragraphe de moins de `min_words` est fusionné avec les suivants de la même
    section ; au-delà de `max_words`, il est coupé aux phrases. Un reste très court en
    fin de section est rattaché au passage précédent de la même section.
    """
    passages: list[Passage] = []
    stack: list[str] = []
    buf: list[str] = []
    buf_page: int | None = None

    def flush() -> None:
        nonlocal buf, buf_page
        if not buf:
            return
        section = SECTION_SEP.join(stack)
        text = " ".join(buf)
        short = word_count(text) < min_words // 2
        if short and passages and passages[-1].section == section:
            passages[-1].text += " " + text
        else:
            for chunk in split_long(text, max_words, overlap_sentences):
                passages.append(Passage(page=buf_page or 1, section=section, text=chunk))
        buf, buf_page = [], None

    for b in blocks:
        if b.kind == "heading":
            flush()
            stack = stack[: b.level - 1] + [b.text]
            continue
        if buf_page is None:
            buf_page = b.page
        buf.append(b.text)
        if word_count(" ".join(buf)) >= min_words:
            flush()
    flush()
    return passages
