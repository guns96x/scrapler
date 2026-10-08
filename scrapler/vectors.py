"""
Scrapler Vectors: Local Vector Storage (sqlite-vec) and Multilingual FastEmbed with RRF.
"""

import os
import sqlite3
import struct
from typing import List, Dict, Any, Optional, Tuple

EMBEDDING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384
DEFAULT_VEC_DB_PATH = os.path.join(os.path.expanduser("~"), ".scrapler", "vectors.db")

_model_instance = None


def get_embedding_model():
    """
    Lazy-load the FastEmbed multilingual embedding model.

    Pinned to the CPU provider: otherwise onnxruntime probes CUDA on every load and
    fails noisily when the CUDA/cuDNN DLLs are missing. Set SCRAPLER_USE_CUDA=1 to opt in.
    """
    global _model_instance
    if _model_instance is None:
        from fastembed import TextEmbedding
        providers = None if os.environ.get("SCRAPLER_USE_CUDA") == "1" else ["CPUExecutionProvider"]
        _model_instance = TextEmbedding(EMBEDDING_MODEL_NAME, providers=providers)
    return _model_instance


def serialize_vector(vec: List[float]) -> bytes:
    """Serialize a list of floats into binary format for sqlite-vec."""
    return struct.pack(f"{len(vec)}f", *vec)


class VectorStore:
    """Manages sqlite-vec database connection and vector KNN search."""

    def __init__(self, db_path: str = DEFAULT_VEC_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        import sqlite_vec
        con = sqlite3.connect(self.db_path, timeout=15.0)
        con.row_factory = sqlite3.Row
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
        con.execute("PRAGMA busy_timeout = 15000;")
        con.execute("PRAGMA journal_mode = WAL;")
        return con

    def init_db(self) -> None:
        with self.get_connection() as con:
            cur = con.cursor()
            cur.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
                    chunk_id integer primary key,
                    project text partition key,
                    embedding float[{EMBEDDING_DIM}] distance_metric=cosine
                );
            """)
            con.commit()

    def index_texts(self, items: List[Dict[str, Any]]) -> int:
        """
        Index list of dicts: [{"id": int, "project": str, "text": str}]
        """
        valid = [it for it in items if it.get("text", "").strip()]
        if not valid:
            return 0

        model = get_embedding_model()
        texts = [it["text"] for it in valid]
        rows = [
            (it["id"], it.get("project", "default"), serialize_vector(list(emb)))
            for it, emb in zip(valid, model.embed(texts, batch_size=64))
        ]

        with self.get_connection() as con:
            # vec0 has no UPSERT: delete then insert so re-indexing a chunk replaces it.
            con.executemany("DELETE FROM vec_chunks WHERE chunk_id = ?", [(r[0],) for r in rows])
            con.executemany(
                "INSERT INTO vec_chunks(chunk_id, project, embedding) VALUES (?, ?, ?)",
                rows,
            )
            con.commit()
        return len(valid)

    def search_knn(
        self,
        query: str,
        project: str = "default",
        limit: int = 10,
        max_distance: float = 0.70
    ) -> List[Dict[str, Any]]:
        """Search nearest chunks using cosine similarity within project partition."""
        model = get_embedding_model()
        query_emb = list(next(model.embed([query])))
        serialized = serialize_vector(query_emb)

        with self.get_connection() as con:
            cur = con.cursor()
            cur.execute("""
                SELECT chunk_id, distance
                FROM vec_chunks
                WHERE embedding MATCH ? AND project = ? AND k = ?
            """, (serialized, project, limit))
            rows = [dict(r) for r in cur.fetchall()]

        # Filter by distance threshold
        return [r for r in rows if r["distance"] <= max_distance]


class HybridRetriever:
    """Combines BM25 / FTS ranks and Vector KNN ranks via Reciprocal Rank Fusion."""

    @staticmethod
    def compute_rrf(
        fts_ranks: List[int],
        vec_ranks: List[int],
        k: int = 60,
        limit: int = 10
    ) -> List[Tuple[int, float]]:
        """
        Reciprocal Rank Fusion (RRF):
        score(d) = sum(1 / (k + rank_i(d)))
        """
        return HybridRetriever.fuse([fts_ranks, vec_ranks], k=k, limit=limit)

    @staticmethod
    def fuse(
        rankings: List[List[Any]],
        k: int = 60,
        limit: int = 10,
        weights: Optional[List[float]] = None,
    ) -> List[Tuple[Any, float]]:
        """Weighted RRF over any number of ranked id lists."""
        scores: Dict[Any, float] = {}
        for i, ranking in enumerate(rankings):
            w = weights[i] if weights else 1.0
            for rank, cid in enumerate(ranking, 1):
                scores[cid] = scores.get(cid, 0.0) + w / (k + rank)
        return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
