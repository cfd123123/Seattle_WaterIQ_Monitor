"""BM25 retrieval over ops-doc chunks."""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from assistant.config import RagConfig, load_rag_config
from assistant.rag.chunker import DocChunk
from assistant.rag.indexer import load_chunks_from_disk, rebuild_index

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class SearchHit:
    """A retrieved chunk with BM25 score."""

    chunk: DocChunk
    score: float

    def to_source(self) -> dict[str, str]:
        return {
            "type": "doc",
            "ref": f"{self.chunk.source_path}#{self.chunk.anchor}",
            "heading": self.chunk.heading,
        }


class RagIndex:
    """In-memory BM25 index over document chunks."""

    def __init__(self, chunks: list[DocChunk]) -> None:
        self.chunks = chunks
        tokenized = [_tokenize(chunk.text) for chunk in chunks]
        self._bm25 = BM25Okapi(tokenized) if tokenized else None

    @property
    def ready(self) -> bool:
        return bool(self.chunks)

    def search(self, query: str, *, top_k: int = 5) -> list[SearchHit]:
        if not self.chunks or self._bm25 is None:
            return []
        tokens = _tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)
        hits: list[SearchHit] = []
        for index, score in ranked[:top_k]:
            if score <= 0:
                continue
            hits.append(SearchHit(chunk=self.chunks[index], score=float(score)))
        return hits


_index_lock = threading.Lock()
_index: RagIndex | None = None


def _load_or_build_index(config: RagConfig | None = None) -> RagIndex:
    cfg = config if config is not None else load_rag_config()
    chunks = load_chunks_from_disk(cfg)
    if chunks is None:
        logger.info("RAG index not found on disk; building lazily at %s", cfg.index_dir)
        chunks = rebuild_index(cfg)
    return RagIndex(chunks)


def ensure_rag_index(config: RagConfig | None = None) -> RagIndex:
    """Load or lazily build the in-memory BM25 index."""
    global _index
    with _index_lock:
        if _index is None or not _index.ready:
            _index = _load_or_build_index(config)
        return _index


def invalidate_rag_index() -> None:
    """Drop the cached in-memory index (used after rebuild)."""
    global _index
    with _index_lock:
        _index = None


def is_rag_index_ready(config: RagConfig | None = None) -> bool:
    """True when persisted or in-memory index has at least one chunk."""
    global _index
    if _index is not None and _index.ready:
        return True
    cfg = config if config is not None else load_rag_config()
    chunks = load_chunks_from_disk(cfg)
    return bool(chunks)


def search_ops_docs(query: str, *, top_k: int | None = None, config: RagConfig | None = None) -> list[SearchHit]:
    """Retrieve top-k ops-doc chunks for a natural-language question."""
    cfg = config if config is not None else load_rag_config()
    k = top_k if top_k is not None else cfg.top_k
    index = ensure_rag_index(cfg)
    return index.search(query, top_k=k)
