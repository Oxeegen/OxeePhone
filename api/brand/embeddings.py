"""Embeddings from a self-hosted OpenAI-compatible server (provider "speaches").

The knowledge-base vector column is fixed at ``Vector(1536)``. Vectors with
fewer dimensions are zero-padded to 1536: padding with zeros leaves every dot
product and norm unchanged, so cosine similarity (the index metric) is
preserved exactly and no migration is needed. Larger vectors are rejected with
an actionable error.
"""

from api.db.db_client import DBClient
from api.services.gen_ai.embedding.openai_service import (
    EMBEDDING_DIMENSION,
    OpenAIEmbeddingService,
)


class EmbeddingDimensionTooLargeError(ValueError):
    def __init__(self, model_id: str, dimension: int):
        super().__init__(
            f"Embedding model '{model_id}' returns {dimension}-dimensional vectors; "
            f"the knowledge base supports at most {EMBEDDING_DIMENSION}. Choose a "
            "smaller model (or a Matryoshka model served with fewer dimensions)."
        )


def pad_embedding(vector: list[float], model_id: str) -> list[float]:
    dimension = len(vector)
    if dimension > EMBEDDING_DIMENSION:
        raise EmbeddingDimensionTooLargeError(model_id, dimension)
    if dimension == EMBEDDING_DIMENSION:
        return vector
    return list(vector) + [0.0] * (EMBEDDING_DIMENSION - dimension)


class LocalEmbeddingService(OpenAIEmbeddingService):
    def __init__(
        self,
        db_client: DBClient,
        model_id: str,
        base_url: str | None,
        api_key: str | None = None,
    ):
        if not base_url:
            raise ValueError(
                "base_url is required for Local Models embeddings. Set it in "
                "Models > Embedding."
            )
        # Self-hosted servers usually need no key; the OpenAI client needs one.
        super().__init__(
            db_client=db_client,
            api_key=api_key or "none",
            model_id=model_id,
            base_url=base_url,
        )

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors = await super().embed_texts(texts)
        return [pad_embedding(vector, self.model_id) for vector in vectors]
