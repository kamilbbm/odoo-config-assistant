"""Semantic index (SFD 1.1, "Index de recherche sémantique") and hybrid retrieval.

The vectorization service of the SFD is provided locally: latent semantic analysis (LSA) of the
indexed sections, computed at each synchronization (step 4). Each section holds its English
text and its French recomposition, so the latent space also links French and English terms:
a French question finds an English-only section and vice versa. No API key is needed; another
service can replace it behind the same two functions (``fit`` and ``SemanticModel.search``).

The vectors are stored next to the active index (``<index>.vectors.npz``) with the ids of the
sections they describe; if they do not match the index, the search falls back to BM25 alone.

``HybridRetriever`` fuses the BM25 and semantic rankings (reciprocal rank fusion). The RG-006
coverage decision stays lexical: a semantic neighbour alone never makes a question "covered".
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from odoo_config_assistant import DOC_VERSION, ERP
from odoo_config_assistant.knowledge import BM25Retriever, Chunk, Hit, expand_query, tokenize

DIMENSIONS = 128
MAX_TERMS = 12000
RRF_K = 60


def vectors_path(index_path: Path) -> Path:
    return index_path.with_suffix(".vectors.npz")


def _chunk_tokens(chunk: Chunk) -> list[str]:
    return tokenize(
        f"{chunk.page_title} {chunk.section_title} {chunk.text} "
        f"{chunk.page_title_fr or ''} {chunk.section_title_fr or ''} {chunk.text_fr or ''}"
    )


@dataclass
class SemanticModel:
    commit: str
    chunk_ids: list[str]
    vocab: dict[str, int]
    idf: np.ndarray  # (terms,)
    term_vectors: np.ndarray  # (terms, k): projection of a TF-IDF vector into the latent space
    doc_vectors: np.ndarray  # (chunks, k), unit length

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        terms = sorted(self.vocab, key=self.vocab.__getitem__)
        with path.open("wb") as handle:
            np.savez_compressed(
                handle,
                commit=np.array(self.commit),
                chunk_ids=np.array(self.chunk_ids),
                terms=np.array(terms),
                idf=self.idf,
                term_vectors=self.term_vectors,
                doc_vectors=self.doc_vectors,
            )

    @classmethod
    def load(cls, path: Path) -> SemanticModel:
        with np.load(path, allow_pickle=False) as data:
            terms = [str(t) for t in data["terms"]]
            return cls(
                commit=str(data["commit"]),
                chunk_ids=[str(c) for c in data["chunk_ids"]],
                vocab={t: i for i, t in enumerate(terms)},
                idf=data["idf"],
                term_vectors=data["term_vectors"],
                doc_vectors=data["doc_vectors"],
            )

    def matches(self, chunks: list[Chunk]) -> bool:
        return self.chunk_ids == [c.id for c in chunks]

    def query_vector(self, query: str) -> np.ndarray | None:
        counts = Counter(t for t in expand_query(query) if t in self.vocab)
        if not counts:
            return None
        vector = np.zeros(self.term_vectors.shape[1], dtype=np.float32)
        for term, tf in counts.items():
            i = self.vocab[term]
            vector += (1 + math.log(tf)) * self.idf[i] * self.term_vectors[i]
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else None

    def similarities(self, query: str) -> np.ndarray | None:
        vector = self.query_vector(query)
        return None if vector is None else self.doc_vectors @ vector


def fit(
    chunks: list[Chunk],
    commit: str,
    dimensions: int = DIMENSIONS,
    max_terms: int = MAX_TERMS,
    seed: int = 0,
) -> SemanticModel:
    """Latent semantic analysis by randomized SVD of the TF-IDF matrix (sections x terms)."""
    if not chunks:  # index vide : rien à vectoriser, la recherche reste vide
        return SemanticModel(
            commit=commit,
            chunk_ids=[],
            vocab={},
            idf=np.zeros(0, dtype=np.float32),
            term_vectors=np.zeros((0, 1), dtype=np.float32),
            doc_vectors=np.zeros((0, 1), dtype=np.float32),
        )
    docs = [Counter(_chunk_tokens(c)) for c in chunks]
    df: Counter[str] = Counter()
    for doc in docs:
        df.update(doc.keys())
    n = len(docs)
    candidates = [t for t, f in df.items() if f >= 2 and f <= 0.5 * n]
    if not candidates:  # très petit corpus : tous les termes
        candidates = list(df)
    candidates.sort(key=lambda t: (-df[t], t))
    terms = sorted(candidates[:max_terms])
    vocab = {t: i for i, t in enumerate(terms)}
    if not vocab:
        raise ValueError("vocabulaire vide")
    idf = np.array([math.log(n / df[t]) for t in terms], dtype=np.float32)
    matrix = np.zeros((n, len(terms)), dtype=np.float32)
    for row, doc in enumerate(docs):
        for term, tf in doc.items():
            col = vocab.get(term)
            if col is not None:
                matrix[row, col] = (1 + math.log(tf)) * idf[col]
        norm = np.linalg.norm(matrix[row])
        if norm:
            matrix[row] /= norm
    k = max(1, min(dimensions, n - 1, len(terms) - 1))
    rng = np.random.default_rng(seed)
    sample = matrix @ rng.standard_normal((len(terms), k + 10)).astype(np.float32)
    for _ in range(2):  # power iterations for a sharper spectrum
        sample = matrix @ (matrix.T @ sample)
    basis, _ = np.linalg.qr(sample)
    small = basis.T @ matrix
    u_small, sigma, vt = np.linalg.svd(small, full_matrices=False)
    u = (basis @ u_small)[:, :k]
    sigma, vt = sigma[:k], vt[:k]
    doc_vectors = u * sigma
    doc_vectors /= np.maximum(np.linalg.norm(doc_vectors, axis=1, keepdims=True), 1e-12)
    return SemanticModel(
        commit=commit,
        chunk_ids=[c.id for c in chunks],
        vocab=vocab,
        idf=idf,
        term_vectors=vt.T.astype(np.float32),
        doc_vectors=doc_vectors.astype(np.float32),
    )


class HybridRetriever:
    """BM25 + semantic ranking, fused by reciprocal rank (k=60). Same interface as BM25."""

    def __init__(self, bm25: BM25Retriever, model: SemanticModel, depth: int = 50):
        if not model.matches(bm25.chunks):
            raise ValueError("vecteurs sans rapport avec l'index actif")
        self.bm25 = bm25
        self.model = model
        self.depth = depth
        self.chunks = bm25.chunks
        self.min_score = bm25.min_score

    def search(
        self,
        query: str,
        *,
        erp: str = ERP,
        version: str = DOC_VERSION,
        k: int = 5,
        boost_paths: Iterable[str] = (),
        country: str | None = None,
    ) -> list[Hit]:
        lexical = self.bm25.search(
            query,
            erp=erp,
            version=version,
            k=self.depth,
            boost_paths=boost_paths,
            country=country,
        )
        fused: dict[str, float] = {}
        by_id: dict[str, Hit] = {}
        for rank, hit in enumerate(lexical):
            fused[hit.chunk.id] = 1 / (RRF_K + rank + 1)
            by_id[hit.chunk.id] = hit
        similarities = self.model.similarities(query)
        if similarities is not None:
            order = np.argsort(-similarities)
            rank = 0
            for i in order:
                chunk = self.chunks[int(i)]
                if chunk.erp != erp or chunk.version != version:  # RG-007
                    continue
                fused[chunk.id] = fused.get(chunk.id, 0.0) + 1 / (RRF_K + rank + 1)
                semantic = float(similarities[int(i)])
                if chunk.id in by_id:
                    hit = by_id[chunk.id]
                    by_id[chunk.id] = Hit(hit.chunk, hit.score, hit.matched_terms, semantic)
                else:
                    by_id[chunk.id] = Hit(chunk, 0.0, frozenset(), semantic)
                rank += 1
                if rank >= self.depth:
                    break
        ranked = sorted(fused, key=fused.__getitem__, reverse=True)[:k]
        return [by_id[i] for i in ranked]


def load_retriever(index_chunks: list[Chunk], index_path: Path) -> BM25Retriever | HybridRetriever:
    """Hybrid retriever when the vectors match the index, BM25 alone otherwise."""
    bm25 = BM25Retriever(index_chunks)
    path = vectors_path(index_path)
    if not path.exists():
        return bm25
    try:
        return HybridRetriever(bm25, SemanticModel.load(path))
    except (OSError, ValueError, KeyError):
        return bm25
