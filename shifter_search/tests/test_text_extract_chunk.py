from shifter_search.chunk import build_passages, split_long
from shifter_search.extract import extract
from shifter_search.fusion import rrf
from shifter_search.text import STOPWORDS, best_sentence, lemmas, normalize, word_count


def test_normalize_ligatures_and_exposants():
    assert normalize("ﬁn  des­émissions de tCO₂e") == "fin desémissions de tCO2e"


def test_lemmas_elision_plural_stopwords():
    out = lemmas("Les collectivités s'adaptent aux canicules et à l'atténuation.")
    assert "collectivité" in out and "adapter" in out and "canicule" in out and "atténuation" in out
    assert not set(out) & STOPWORDS
    assert "aux" not in out and "et" not in out


def test_extract_headings_levels_and_running_blocks(demo_pdfs):
    ex = extract(demo_pdfs[0])
    assert ex.title == "Adaptation et atténuation (démo)"
    assert ex.n_pages == 3
    headings = [(b.level, b.text) for b in ex.blocks if b.kind == "heading"]
    assert headings[0] == (1, "Adaptation au changement climatique")
    assert (2, "Canicules et santé des populations") in headings
    texts = " ".join(b.text for b in ex.blocks)
    assert "Edition 2026" not in texts and "Page 1" not in texts  # en-têtes et pieds retirés


def test_passages_follow_sections(demo_pdfs):
    passages = build_passages(extract(demo_pdfs[0]).blocks)
    sections = [p.section for p in passages]
    assert "Adaptation au changement climatique > Canicules et santé des populations" in sections
    assert all(40 <= word_count(p.text) <= 250 for p in passages)
    assert {p.page for p in passages} == {1, 2, 3}


def test_split_long_respects_max_words_with_overlap():
    sentences = [f"Phrase numéro {i} avec quelques mots pour remplir le texte." for i in range(40)]
    text = " ".join(sentences)
    chunks = split_long(text, max_words=60, overlap_sentences=1)
    assert len(chunks) > 1
    assert all(word_count(c) <= 60 for c in chunks)
    # recouvrement : la dernière phrase d'un morceau ouvre le suivant
    assert chunks[0].split(". ")[-1].strip(". ") in chunks[1]


def test_best_sentence_picks_overlapping_sentence():
    text = "Le vélo progresse. Les canicules aggravent la mortalité. Les bus roulent."
    assert best_sentence(text, lemmas("canicule mortalité")) == "Les canicules aggravent la mortalité."


def test_rrf_scores_and_order():
    fused = rrf([["a", "b", "c"], ["c", "a", "d"]], k=60)
    ids = [i for i, _ in fused]
    assert ids[:2] == ["a", "c"]  # a : 1/61+1/62 ; c : 1/63+1/61
    assert abs(fused[0][1] - (1 / 61 + 1 / 62)) < 1e-12
    assert set(ids) == {"a", "b", "c", "d"}
    weighted = rrf([["a"], ["b"]], weights=[1.0, 2.0])
    assert weighted[0][0] == "b"
