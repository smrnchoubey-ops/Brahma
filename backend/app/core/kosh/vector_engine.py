"""
KOSH Vector Search & Similarity Engine
Strictly conforms to BRAHMA COS Whitesheet §9.1, §9.4, §9.5 & §9.6.

Implements cosine similarity matching, dynamic similarity thresholds, Top-K ranking,
strict multi-tenant isolation, and tombstone exclusion.
"""
from typing import Dict, Any, Optional, List, Tuple
import math
import hashlib
import threading

from app.core.kosh.memory_tiers import KoshChunk, MemoryTier


def compute_cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """
    Computes cosine similarity between two dense float vectors:
    sim(u, v) = (u . v) / (||u|| * ||v||)
    """
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm_a = math.sqrt(sum(a * a for a in vec1))
    norm_b = math.sqrt(sum(b * b for b in vec2))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    sim = dot_product / (norm_a * norm_b)
    return max(-1.0, min(1.0, sim))


def generate_deterministic_test_embedding(text: str, dim: int = 768) -> List[float]:
    """
    Generates deterministic, normalized pseudo-semantic embeddings for testing.
    Ensures identical text produces identical unit-length 768-dim vectors.
    """
    text_clean = text.lower().strip()
    words = text_clean.split()
    
    vec = [0.0] * dim
    for word in words:
        h = int(hashlib.sha256(word.encode("utf-8")).hexdigest(), 16)
        for i in range(dim):
            # Seed pseudo-random components deterministically
            component = ((h >> (i % 64)) & 0xFF) / 255.0 - 0.5
            vec[i] += component

    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    else:
        vec[0] = 1.0

    return vec


class KoshVectorStore:
    """
    Thread-safe, multi-tenant vector store partitioning knowledge chunks by tenant_id.
    Matches Whitesheet §9.1, §9.4 & §9.6.
    """
    def __init__(self):
        self._chunks: Dict[str, KoshChunk] = {}
        self._lock = threading.Lock()

    def add_chunk(self, chunk: KoshChunk) -> None:
        """Stores or updates a knowledge chunk."""
        with self._lock:
            self._chunks[chunk.chunk_id] = chunk

    def get_chunk(self, chunk_id: str) -> Optional[KoshChunk]:
        """Retrieves a chunk by ID."""
        with self._lock:
            return self._chunks.get(chunk_id)

    def tombstone_chunk(self, chunk_id: str, tenant_id: str) -> bool:
        """
        Marks a chunk as tombstoned (soft-deleted) under §9.6.
        Enforces tenant ownership.
        """
        with self._lock:
            chunk = self._chunks.get(chunk_id)
            if chunk and chunk.tenant_id == tenant_id:
                chunk.is_tombstoned = True
                return True
            return False

    def query(
        self,
        query_vector: List[float],
        tenant_id: str,
        top_k: int = 5,
        min_similarity: float = 0.70,
        tier_filter: Optional[List[MemoryTier]] = None
    ) -> List[Tuple[KoshChunk, float]]:
        """
        Performs semantic vector search with tenant isolation, thresholding, and Top-K ranking.
        Strictly excludes tombstoned records.
        """
        with self._lock:
            candidates: List[Tuple[KoshChunk, float]] = []

            for chunk in self._chunks.values():
                # 1. Multi-Tenant Scoping Check (§9.4)
                # Chunks with tenant_id "global" or matching authenticated tenant
                if chunk.tenant_id != tenant_id and chunk.tenant_id != "global":
                    continue

                # 2. Tombstone Exclusion (§9.6)
                if chunk.is_tombstoned:
                    continue

                # 3. Tier Filtering (§9.2)
                if tier_filter and chunk.tier not in tier_filter:
                    continue

                if not chunk.embedding:
                    continue

                # 4. Cosine Similarity Computation (§9.1)
                sim = compute_cosine_similarity(query_vector, chunk.embedding)

                # 5. Dynamic Similarity Threshold (§9.5)
                if sim >= min_similarity:
                    candidates.append((chunk, sim))

            # 6. Top-K Ranking (§9.5)
            candidates.sort(key=lambda item: item[1], reverse=True)
            return candidates[:top_k]

    def clear(self) -> None:
        """Clears all stored chunks (for test teardown)."""
        with self._lock:
            self._chunks.clear()
