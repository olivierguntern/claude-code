"""Extraction PDF -> blocs de texte typés (titre / corps) avec page et position.

Heuristiques, sans modèle :
- corps de texte = taille de police dominante (pondérée par le nombre de caractères) ;
- titre = bloc court nettement plus grand que le corps, ou court et entièrement en gras ;
- en-têtes / pieds de page = blocs de marge répétés sur au moins la moitié des pages
  (chiffres normalisés), plus numéros de page isolés.

Limites connues : colonnes multiples et tableaux complexes (ordre de lecture approximatif),
césures sur mots composés (« retrait-\\ngonflement » est recollé). Si les PDF ont des signets,
`doc.get_toc()` donne une hiérarchie plus fiable (voir README, pistes d'amélioration).

PyMuPDF est sous licence AGPL v3 (licence commerciale chez Artifex) : voir README.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from .text import normalize

MARGIN = 0.09  # fraction de la hauteur de page considérée comme marge haute / basse
_PAGE_NUM = re.compile(r"^(?:page\s*)?\d{1,4}(?:\s*(?:/|sur)\s*\d{1,4})?$", re.IGNORECASE)


@dataclass
class Block:
    page: int  # 1-based
    text: str
    size: float
    bold: bool
    y0: float
    y1: float
    page_height: float
    kind: str = "body"  # "body" | "heading"
    level: int = 0  # 1 = titre le plus grand


@dataclass
class Extraction:
    blocks: list[Block]
    title: str
    n_pages: int


def _join_lines(lines: list[str]) -> str:
    """Assemble les lignes d'un bloc ; recolle les césures « mot-\\nsuite »."""
    out = ""
    for line in (ln.strip() for ln in lines):
        if not line:
            continue
        if out.endswith("-") and line[:1].islower():
            out = out[:-1] + line
        else:
            out = f"{out} {line}" if out else line
    return out


def _read_blocks(doc: pymupdf.Document) -> list[Block]:
    blocks: list[Block] = []
    for pno, page in enumerate(doc, start=1):
        height = page.rect.height
        for b in page.get_text("dict", sort=True)["blocks"]:
            if b.get("type") != 0:
                continue
            lines, weighted, chars, bold_chars = [], 0.0, 0, 0
            for ln in b["lines"]:
                parts = []
                for sp in ln["spans"]:
                    parts.append(sp["text"])
                    n = len(sp["text"].strip())
                    if n:
                        chars += n
                        weighted += sp["size"] * n
                        if (sp["flags"] & 16) or "bold" in sp["font"].lower():
                            bold_chars += n
                lines.append("".join(parts))
            text = normalize(_join_lines(lines))
            if not text or not chars:
                continue
            blocks.append(
                Block(
                    page=pno,
                    text=text,
                    size=round(weighted / chars, 1),
                    bold=bold_chars >= 0.9 * chars,
                    y0=b["bbox"][1],
                    y1=b["bbox"][3],
                    page_height=height,
                )
            )
    return blocks


def _drop_running_blocks(blocks: list[Block], n_pages: int) -> list[Block]:
    """Supprime en-têtes, pieds de page et numéros de page."""

    def zone(b: Block) -> str | None:
        if b.y1 <= b.page_height * MARGIN * 1.5 or b.y0 < b.page_height * MARGIN * 0.8:
            return "top"
        if b.y0 >= b.page_height * (1 - MARGIN * 1.5) or b.y1 > b.page_height * (1 - MARGIN * 0.8):
            return "bottom"
        return None

    def key(b: Block) -> tuple[str, str] | None:
        z = zone(b)
        return (re.sub(r"\d+", "#", b.text.lower()), z) if z else None

    pages_by_key: dict[tuple[str, str], set[int]] = {}
    for b in blocks:
        k = key(b)
        if k:
            pages_by_key.setdefault(k, set()).add(b.page)
    threshold = max(2, math.ceil(0.5 * n_pages))
    repeated = {k for k, pages in pages_by_key.items() if len(pages) >= threshold}

    kept = []
    for b in blocks:
        k = key(b)
        if k and (k in repeated or _PAGE_NUM.match(b.text)):
            continue
        kept.append(b)
    return kept


def _classify(blocks: list[Block]) -> None:
    """Renseigne `kind` et `level` en place."""
    if not blocks:
        return
    sizes = Counter()
    for b in blocks:
        sizes[b.size] += len(b.text)
    body = sizes.most_common(1)[0][0]

    def short(b: Block) -> bool:
        return len(b.text) <= 160 and len(b.text.split()) <= 25

    heading_sizes = sorted({b.size for b in blocks if b.size >= body * 1.15 and short(b)}, reverse=True)
    for b in blocks:
        if b.size >= body * 1.15 and short(b):
            b.kind, b.level = "heading", heading_sizes.index(b.size) + 1
        elif b.bold and short(b) and b.size >= body * 0.98 and not b.text.rstrip().endswith((".", ";", ":")):
            b.kind, b.level = "heading", len(heading_sizes) + 1


def extract(path: str | Path) -> Extraction:
    path = Path(path)
    with pymupdf.open(path) as doc:
        n_pages = doc.page_count
        meta_title = ((doc.metadata or {}).get("title") or "").strip()
        blocks = _drop_running_blocks(_read_blocks(doc), n_pages)
    _classify(blocks)
    first_h1 = next((b.text for b in blocks if b.kind == "heading" and b.level == 1), "")
    return Extraction(blocks=blocks, title=meta_title or first_h1 or path.stem, n_pages=n_pages)
