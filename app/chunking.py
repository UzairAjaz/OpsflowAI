from __future__ import annotations

from app.config import settings

def chunk_text(
    text: str,
    max_chars: int | None = None,
    overlap: int | None = None,
) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []

    max_chars = max_chars or settings.embedding_chunk_size
    overlap = overlap if overlap is not None else settings.embedding_chunk_overlap
    max_chars = max(100, max_chars)
    overlap = max(0, min(overlap, max_chars // 2))

    words = text.split()
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for word in words:
        extra = len(word) + (1 if current else 0)
        if current and current_len + extra > max_chars:
            chunks.append(" ".join(current))

            overlap_words: list[str] = []
            overlap_len = 0
            for previous in reversed(current):
                add = len(previous) + (1 if overlap_words else 0)
                if overlap_len + add > overlap:
                    break
                overlap_words.insert(0, previous)
                overlap_len += add
            current = overlap_words
            current_len = overlap_len

        current.append(word)
        current_len += len(word) + (1 if len(current) > 1 else 0)

    if current:
        chunks.append(" ".join(current))

    return chunks

__all__ = ["chunk_text"]
