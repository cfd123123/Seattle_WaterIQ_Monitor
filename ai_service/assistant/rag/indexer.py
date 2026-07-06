"""Build and persist BM25-ready chunk index for ops documentation."""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict
from pathlib import Path

from assistant.config import RagConfig, _ai_service_root, load_rag_config
from assistant.rag.chunker import DocChunk, chunk_markdown_files

logger = logging.getLogger(__name__)

CHUNKS_FILENAME = "chunks.json"
META_FILENAME = "meta.json"


def _chunks_to_json(chunks: list[DocChunk]) -> list[dict]:
    return [asdict(chunk) for chunk in chunks]


def _chunks_from_json(payload: list[dict]) -> list[DocChunk]:
    return [DocChunk(**item) for item in payload]


def build_chunks(config: RagConfig | None = None) -> list[DocChunk]:
    """Chunk configured markdown sources."""
    cfg = config if config is not None else load_rag_config()
    root = _ai_service_root()
    existing_paths = [path for path in cfg.doc_paths if path.exists()]
    missing = [str(path.relative_to(root)) for path in cfg.doc_paths if not path.exists()]
    if missing:
        logger.warning("RAG source files missing (skipped): %s", ", ".join(missing))
    return chunk_markdown_files(existing_paths, service_root=root)


def write_index(chunks: list[DocChunk], config: RagConfig | None = None) -> Path:
    """Persist chunk list and metadata to the configured index directory."""
    cfg = config if config is not None else load_rag_config()
    cfg.index_dir.mkdir(parents=True, exist_ok=True)
    chunks_path = cfg.index_dir / CHUNKS_FILENAME
    meta_path = cfg.index_dir / META_FILENAME
    chunks_path.write_text(json.dumps(_chunks_to_json(chunks), ensure_ascii=False, indent=2), encoding="utf-8")
    meta = {
        "chunk_count": len(chunks),
        "source_files": sorted({chunk.source_path for chunk in chunks}),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote RAG index (%s chunks) to %s", len(chunks), cfg.index_dir)
    return chunks_path


def load_chunks_from_disk(config: RagConfig | None = None) -> list[DocChunk] | None:
    """Load persisted chunks when the index file exists."""
    cfg = config if config is not None else load_rag_config()
    chunks_path = cfg.index_dir / CHUNKS_FILENAME
    if not chunks_path.exists():
        return None
    payload = json.loads(chunks_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Invalid RAG index format: {chunks_path}")
    return _chunks_from_json(payload)


def rebuild_index(config: RagConfig | None = None) -> list[DocChunk]:
    """Rebuild and persist the RAG chunk index."""
    chunks = build_chunks(config)
    write_index(chunks, config)
    return chunks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build ops-doc RAG chunk index (BM25).")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild and overwrite the index.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    if not args.rebuild:
        parser.error("Pass --rebuild to build the index.")
    chunks = rebuild_index()
    print(f"Indexed {len(chunks)} chunks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
