import numpy as np
import pytest

from examples.demo_corpus import build_demo_pdfs
from shifter_search.db import connect
from shifter_search.index import index_paths
from shifter_search.text import lemmas
from shifter_search.themes import TaxonomyTagger, load_taxonomy

# Concepts : chaque groupe de lemmes pointe vers le même axe. Embedder SYNTHÉTIQUE de test :
# il simule un modèle sémantique pour vérifier la fusion, pas la qualité d'un vrai modèle.
CONCEPTS = [
    {"chaud", "chaleur", "canicule", "température", "rafraîchissement", "îlot", "ombrage", "été"},
    {"habitant", "population", "personne", "santé", "enfant", "travailleur"},
    {"émission", "carbone", "décarbonation", "rénovation", "gaz", "énergie", "isolation"},
    {"transport", "vélo", "ferroviaire", "véhicule", "mobilité", "bus", "voiture"},
    {"sécheresse", "argile", "sol", "fissurer", "maison", "bâtiment"},
]
LEMMA_TO_AXIS = {lem: i for i, group in enumerate(CONCEPTS) for lem in group}


class ConceptEmbedder:
    name = "concept-test"

    def _enc(self, text):
        v = np.zeros(len(CONCEPTS), dtype=np.float32)
        for lem in lemmas(text):
            if lem in LEMMA_TO_AXIS:
                v[LEMMA_TO_AXIS[lem]] += 1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def encode_passages(self, texts):
        return np.vstack([self._enc(t) for t in texts])

    def encode_query(self, text):
        return self._enc(text)


@pytest.fixture(scope="session")
def demo_pdfs(tmp_path_factory):
    return build_demo_pdfs(tmp_path_factory.mktemp("pdfs"))


@pytest.fixture(scope="session")
def taxonomy():
    return TaxonomyTagger(load_taxonomy("data/taxonomy.example.yaml"))


@pytest.fixture(scope="session")
def embedder():
    return ConceptEmbedder()


@pytest.fixture(scope="session")
def db_path(tmp_path_factory, demo_pdfs, taxonomy, embedder):
    path = tmp_path_factory.mktemp("db") / "shifter.db"
    conn = connect(path)
    stats = index_paths(conn, demo_pdfs, embedder, taxonomy)
    conn.close()
    assert not stats["failed"], stats
    return path
