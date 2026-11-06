# shifter-search

Exemple exécutable du pipeline « B léger » pour l’initiative COMM20260922173451 (outil de recherche documentaire pour les publications du Shift). La chaîne ne comporte aucun modèle génératif : chaque résultat est un passage existant, avec son document, sa page et sa section.

## Principe

```
PDF ── extraction (PyMuPDF) ── paragraphes + sections ── lemmes (simplemma)
                                      │                        │
                                      │                 index BM25 (SQLite FTS5)
                                      └── embeddings gelés (multilingual-e5) ── matrice numpy

requête ── BM25 ──┐
                  ├── fusion RRF (k = 60) ── top k ── passages citables
requête ── e5 ────┘

thèmes : taxonomie YAML (Aho-Corasick sur lemmes) + régression logistique sur les embeddings
```

Un seul fichier SQLite contient les documents, les passages, l’index plein texte, les vecteurs et les thèmes.

## Installation

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[e5,api,dev]"
```

Le modèle `intfloat/multilingual-e5-base` (278 M de paramètres) se télécharge au premier usage ; `--e5-model intfloat/multilingual-e5-small` réduit le temps d’indexation.

## Démarrage rapide

```bash
python -m examples.demo_corpus demo_pdfs          # deux rapports PDF fictifs
export SHIFTER_DB=demo.db
shifter-search index demo_pdfs --taxonomy data/taxonomy.example.yaml
shifter-search search "protéger les habitants quand il fait très chaud"
shifter-search search "chaleur" --mode lexical --theme adaptation
shifter-search search "vélo" --json
```

Sans accès au modèle, `--embedder hash` (ou `SHIFTER_EMBEDDER=hash`) valide la chaîne hors ligne. Cet embedder est lexical : il ne dit rien de la qualité sémantique.

## Modules

| Module | Rôle |
|---|---|
| `extract.py` | blocs PDF, détection des titres par taille de police, retrait des en-têtes, pieds de page et numéros |
| `chunk.py` | passages de 40 à 250 mots par section, coupe aux phrases avec une phrase de recouvrement |
| `text.py` | normalisation NFKC, lemmes (simplemma), mots vides, phrases |
| `index.py` | indexation idempotente (sha256), identifiants de passage stables, embeddings en lot |
| `search.py` | modes `lexical`, `dense`, `hybrid` ; filtre par thème ; rang obtenu dans chaque classement |
| `fusion.py` | Reciprocal Rank Fusion |
| `themes.py` | taxonomie, export des candidats à valider, classifieur par thème |
| `evaluate.py` | nDCG@k, recall@k, MRR@k, intervalle bootstrap apparié, constitution du pool d’annotation |
| `api.py`, `cli.py` | FastAPI et ligne de commande |

## Thèmes

```bash
shifter-search themes-export --out a_valider.csv     # passages étiquetés par la taxonomie
# les Shifters remplissent la colonne « valide » (1 ou 0) ; une case vide est ignorée
shifter-search themes-train --labels a_valider.csv   # classifieur + F1 en validation croisée
```

Les passages annotés sans un thème servent de négatifs pour ce thème. Un thème avec moins de 3 exemples d’une classe est ignoré et signalé dans le rapport.

## Évaluation

```bash
shifter-search pool --queries requetes.txt --out a_annoter.csv   # union des top 20 des trois modes
# annotation : colonne « grade » à 0, 1 ou 2 (le mode d’origine n’est pas indiqué)
shifter-search eval --qrels a_annoter.csv -k 10
```

Le rapport compare lexical, dense et hybride, avec l’écart hybride moins lexical et son intervalle à 95 %. Avec 30 à 50 requêtes, l’intervalle compte autant que la moyenne.

## API

```bash
shifter-search serve --port 8000
curl "localhost:8000/search?q=canicule&k=5&theme=adaptation"
```

Points d’accès : `/search`, `/themes`, `/health`.

## Paramètres

| Paramètre | Où | Valeur |
|---|---|---|
| taille des passages | `chunk.build_passages` | 40 à 250 mots, 1 phrase de recouvrement |
| poids du titre de section | `search.Searcher._lexical` | 3,0 contre 1,0 pour le texte |
| constante RRF | `Searcher(rrf_k=...)` | 60 |
| candidats par classement | `Searcher.search(candidates=...)` | 50 |
| modèle e5 | `--e5-model`, `SHIFTER_E5_MODEL` | `intfloat/multilingual-e5-base` |

## Limites connues

- L’extraction repose sur des heuristiques de taille de police. L’ordre de lecture sur plusieurs colonnes, les tableaux complexes et les PDF scannés (pas d’OCR) ne sont pas traités.
- La lemmatisation par dictionnaire ne désambiguïse pas selon le contexte.
- PyMuPDF est sous licence AGPL v3, avec licence commerciale proposée par Artifex. `pypdfium2` ou `pdfplumber` peuvent le remplacer dans `extract.py`.
- La recherche vectorielle est exacte et en mémoire : 13 ms par requête mesurées pour 100 000 vecteurs de 768 dimensions (307 Mo). Au-delà, un index approximatif devient utile.
- Le titre de section compte pour la taxonomie et pour le BM25.
- Le corpus de démonstration est fictif et la taxonomie d’exemple est à remplacer.
- Le chemin e5 est testé avec un modèle factice (préfixes `query: ` et `passage: `, normalisation). Il n’a pas été exécuté avec les poids réels dans l’environnement de développement, où le téléchargement depuis Hugging Face était bloqué.
- Les mesures de qualité n’ont de valeur que sur des requêtes annotées issues du corpus réel.

## Pistes d’évolution

- Signets PDF (`doc.get_toc()`) pour la hiérarchie des sections.
- Reranker (`bge-reranker-v2-m3`) si le nDCG@10 est insuffisant sur les requêtes paraphrasées.
- SetFit ou ajustement contrastif si le F1 macro des thèmes est insuffisant avec embeddings gelés.
- SEO et GEO : URL stable par rapport, données structurées schema.org, sitemap.
- Meilisearch ou OpenSearch si l’hébergement le permet (facettes, tolérance aux fautes).

## Tests

```bash
pytest        # 23 tests, environ 2 s
```
