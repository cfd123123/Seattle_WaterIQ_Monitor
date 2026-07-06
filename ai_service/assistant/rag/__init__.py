"""RAG indexing and retrieval for ops documentation (MVP-2)."""

from assistant.rag.search import ensure_rag_index, is_rag_index_ready, search_ops_docs

__all__ = ["ensure_rag_index", "is_rag_index_ready", "search_ops_docs"]
