"""Semantic index and hybrid retrieval (index de recherche sémantique, ERR-006)."""

import pytest

from odoo_config_assistant.assistant import answer
from odoo_config_assistant.knowledge import (
    DEFAULT_INDEX_PATH,
    BM25Retriever,
    Chunk,
    KnowledgeIndex,
    is_covered,
)
from odoo_config_assistant.semantic import (
    HybridRetriever,
    SemanticModel,
    fit,
    load_retriever,
    vectors_path,
)

COMMIT = "c" * 40


def chunk(n, text, text_fr=None, version="18.0"):
    return Chunk(
        id=f"content/applications/finance/p{n}.rst#1",
        version=version,
        commit=COMMIT,
        path=f"content/applications/finance/p{n}.rst",
        page_title=f"Page {n}",
        section_title=f"Section {n}",
        text=text,
        text_fr=text_fr,
    )


CHUNKS = [
    chunk(0, "Vendor bills are recorded from the purchase order and validated by accounting.",
          "Les factures fournisseurs sont enregistrées depuis le bon de commande."),
    chunk(1, "Vendor bills can be digitized and recorded automatically from scanned documents.",
          "Les factures fournisseurs peuvent être numérisées automatiquement."),
    chunk(2, "Bank statements are reconciled with payments and invoices in the bank journal.",
          "Les relevés bancaires sont rapprochés avec les paiements."),
    chunk(3, "Bank synchronization imports statements and transactions from the bank.",
          "La synchronisation bancaire importe les relevés et transactions."),
    chunk(4, "Manufacturing orders consume components listed in the bill of materials.",
          "Les ordres de fabrication consomment les composants de la nomenclature."),
    chunk(5, "Work centers define the capacity and cost of manufacturing operations.",
          "Les postes de travail définissent la capacité de fabrication."),
]


def test_fit_builds_unit_document_vectors_aligned_with_the_index():
    model = fit(CHUNKS, COMMIT, dimensions=4)
    assert model.doc_vectors.shape == (6, 4) and model.matches(CHUNKS)
    norms = (model.doc_vectors**2).sum(axis=1)
    assert norms == pytest.approx([1.0] * 6, abs=1e-5)


def test_semantic_similarity_groups_related_sections_across_languages():
    model = fit(CHUNKS, COMMIT, dimensions=3)
    scores = model.similarities("relevés bancaires")  # question en français
    best = max(range(len(CHUNKS)), key=lambda i: scores[i])
    assert best in (2, 3)


def test_save_and_load_round_trip(tmp_path):
    model = fit(CHUNKS, COMMIT, dimensions=4)
    path = vectors_path(tmp_path / "odoo-18.0.json")
    model.save(path)
    loaded = SemanticModel.load(path)
    assert loaded.chunk_ids == model.chunk_ids and loaded.vocab == model.vocab
    assert loaded.similarities("bank") == pytest.approx(model.similarities("bank"))


def test_hybrid_ranking_keeps_bm25_scores_for_the_rg006_decision():
    retriever = HybridRetriever(BM25Retriever(CHUNKS, min_score=0.1), fit(CHUNKS, COMMIT, 4))
    hits = retriever.search("vendor bills recorded", k=4)
    assert {hits[0].chunk.id, hits[1].chunk.id} == {CHUNKS[0].id, CHUNKS[1].id}
    assert all(h.score >= 0 for h in hits)
    # Un voisin purement sémantique (score BM25 nul) ne rend jamais la question couverte.
    semantic_only = [h for h in hits if h.score == 0]
    assert not is_covered(semantic_only, "vendor bills recorded", min_score=0.1)


def test_hybrid_search_respects_the_project_version_rg007():
    other = chunk(9, "Vendor bills recorded in an older documentation.", version="17.0")
    chunks = [*CHUNKS, other]
    retriever = HybridRetriever(BM25Retriever(chunks, min_score=0.1), fit(chunks, COMMIT, 4))
    assert all(h.chunk.version == "18.0" for h in retriever.search("vendor bills", k=10))


def test_vectors_that_do_not_match_the_index_fall_back_to_bm25(tmp_path):
    index_path = tmp_path / "odoo-18.0.json"
    fit(CHUNKS[:3], COMMIT, 2).save(vectors_path(index_path))
    assert isinstance(load_retriever(CHUNKS, index_path), BM25Retriever)
    fit(CHUNKS, COMMIT, 2).save(vectors_path(index_path))
    assert isinstance(load_retriever(CHUNKS, index_path), HybridRetriever)
    assert isinstance(load_retriever(CHUNKS, tmp_path / "missing.json"), BM25Retriever)
    with pytest.raises(ValueError):
        HybridRetriever(BM25Retriever(CHUNKS), fit(CHUNKS[:2], COMMIT, 1))


def test_empty_index_gives_an_empty_model():
    model = fit([], COMMIT)
    assert model.chunk_ids == [] and model.similarities("taxes") is None


@pytest.mark.skipif(
    not vectors_path(DEFAULT_INDEX_PATH).exists(), reason="index sémantique absent"
)
def test_real_hybrid_index_finds_vendor_bills_from_a_french_question():
    index = KnowledgeIndex.load(DEFAULT_INDEX_PATH)
    retriever = load_retriever(index.chunks, DEFAULT_INDEX_PATH)
    assert isinstance(retriever, HybridRetriever)
    result = answer("Comment enregistrer une facture fournisseur ?", retriever, country="FR")
    assert result.covered
    assert any("fournisseur" in c.title.lower() for c in result.citations)
    # Ce que la documentation ne dit pas reste « non couvert » (RG-006).
    assert not answer("Quel est le taux de la TVQ ?", retriever, country="CA").covered
