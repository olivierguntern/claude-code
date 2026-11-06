"""Corpus de démonstration : deux rapports PDF synthétiques (texte fictif, sans lien avec les
publications réelles du Shift), avec titres, en-têtes et numéros de page.

    python -m examples.demo_corpus demo_pdfs
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pymupdf

PAGE_W, PAGE_H = 595, 842
LEFT, RIGHT, TOP, BOTTOM = 72, 523, 130, 715


class _Writer:
    def __init__(self, running_title: str):
        self.doc = pymupdf.open()
        self.running_title = running_title
        self.n = 0
        self._new_page()

    def _new_page(self) -> None:
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.n += 1
        self.y = TOP
        self.page.insert_text((LEFT, 40), f"{self.running_title} - Edition 2026", fontsize=9, fontname="helv")
        self.page.insert_text((280, 810), f"Page {self.n}", fontsize=9, fontname="helv")

    def heading(self, text: str, level: int) -> None:
        size, gap = (18, 30) if level == 1 else (13.5, 24)
        if level == 1 and self.y > TOP:
            self._new_page()
        if self.y + size + 60 > BOTTOM:
            self._new_page()
        self.page.insert_text((LEFT, self.y + size), text, fontsize=size, fontname="hebo")
        self.y += size + gap

    def paragraph(self, text: str) -> None:
        height = (math.ceil(len(text) / 82) + 1) * 13.5
        if self.y + height > BOTTOM:
            self._new_page()
        rc = self.page.insert_textbox(
            pymupdf.Rect(LEFT, self.y, RIGHT, self.y + height), text, fontsize=10.5, fontname="helv"
        )
        assert rc >= 0, "texte trop long pour le rectangle"
        self.y += height + 14

    def save(self, path: Path, title: str) -> None:
        self.doc.set_metadata({"title": title})
        self.doc.save(path)
        self.doc.close()


ADAPTATION = [
    (1, "Adaptation au changement climatique", []),
    (2, "Canicules et santé des populations", [
        "Les canicules deviennent plus longues et plus intenses dans les villes françaises. Les personnes âgées, "
        "les enfants et les travailleurs en extérieur y sont les plus exposés. Les îlots de chaleur urbains "
        "aggravent la surmortalité estivale, car le béton et l'asphalte stockent la chaleur durant la nuit. "
        "Un plan de rafraîchissement doit combiner végétalisation, ombrage des rues, points d'eau et alertes "
        "précoces pour la population."]),
    (2, "Sécheresses et bâtiments", [
        "Le retrait-gonflement des argiles fissure chaque année des milliers de maisons individuelles. La "
        "sécheresse assèche les sols argileux, qui se rétractent, puis se gonflent à nouveau lors des pluies. "
        "Les propriétaires supportent des réparations coûteuses, et les assureurs revoient leurs tarifs. La "
        "cartographie des zones exposées et des normes de construction adaptées réduiraient fortement ces dommages."]),
    (1, "Atténuation des émissions", [
        "La réduction des émissions de gaz à effet de serre passe d'abord par la rénovation énergétique des "
        "logements, premier poste de consommation d'énergie des ménages. Isolation des murs et des toitures, "
        "remplacement des chaudières au fioul et pompes à chaleur permettent de diviser par trois les besoins "
        "de chauffage. Un rythme de plusieurs centaines de milliers de rénovations complètes par an reste "
        "nécessaire pour atteindre la neutralité carbone.",
        "La décarbonation de l'industrie repose sur l'efficacité énergétique, l'électrification des procédés et "
        "la substitution des combustibles fossiles. Les sites les plus émetteurs concentrent les enjeux : "
        "sidérurgie, ciment, chimie et raffinage. Les investissements sont élevés, et la sobriété des produits "
        "finaux contribue à limiter les besoins en matière."]),
    (1, "Gouvernance territoriale", [
        "Les collectivités pilotent les plans climat-air-énergie territoriaux, qui articulent atténuation et "
        "adaptation. Les services de l'État fournissent des données et des outils, mais les moyens d'ingénierie "
        "restent inégaux entre métropoles et petites communes. Un suivi annuel d'indicateurs partagés permet de "
        "comparer les trajectoires et d'identifier les territoires en retard."]),
]

MOBILITE = [
    (1, "Mobilité du quotidien", []),
    (2, "Transports en commun et vélo", [
        "Les transports en commun et le vélo remplacent progressivement la voiture individuelle sur les trajets "
        "courts. Des lignes de bus à haut niveau de service, des pistes cyclables continues et des parkings à "
        "vélos sécurisés augmentent la part modale des déplacements actifs. Le report modal dépend aussi de la "
        "tarification et de la fiabilité des horaires."]),
    (2, "Véhicule électrique", [
        "Le véhicule électrique réduit les émissions à l'usage, à condition que l'électricité soit décarbonée et "
        "que les batteries soient produites et recyclées avec des filières sobres. Les bornes de recharge doivent "
        "être déployées en priorité dans les copropriétés et les zones rurales. Les véhicules légers et peu "
        "puissants limitent la demande en métaux."]),
    (1, "Infrastructures face au climat", [
        "Le réseau ferroviaire subit déjà des ralentissements liés aux fortes chaleurs, aux inondations et aux "
        "glissements de terrain. Renforcer la résilience des voies, des ponts et des postes électriques suppose "
        "un diagnostic de vulnérabilité par ligne et des travaux programmés avant les épisodes extrêmes. Le coût "
        "de l'inaction dépasse celui de l'entretien préventif."]),
]


def _build(path: Path, running_title: str, title: str, content: list) -> Path:
    w = _Writer(running_title)
    for level, heading, paragraphs in content:
        w.heading(heading, level)
        for p in paragraphs:
            w.paragraph(p)
    w.save(path, title)
    return path


def build_demo_pdfs(out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    return [
        _build(out / "rapport-adaptation.pdf", "Rapport adaptation", "Adaptation et atténuation (démo)", ADAPTATION),
        _build(out / "rapport-mobilite.pdf", "Rapport mobilite", "Mobilité du quotidien (démo)", MOBILITE),
    ]


if __name__ == "__main__":
    for p in build_demo_pdfs(sys.argv[1] if len(sys.argv) > 1 else "demo_pdfs"):
        print(p)
