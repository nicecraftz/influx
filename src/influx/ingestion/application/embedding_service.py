from ollama import AsyncClient, ResponseError

from influx.core.logging import get_logger
from influx.core.config import (
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_DOCUMENT_PREFIX,
    EMBEDDING_QUERY_PREFIX,
    OLLAMA_EMBEDDING_MODEL,
    OLLAMA_HOST,
)

log = get_logger(__name__)

_client = AsyncClient(host=OLLAMA_HOST)

async def embed_chunks(chunks: list[str]) -> list[list[float]]:
    """Return one vector per chunk, in the same order as the input.

    A list (not a dict keyed by text) because crawled pages routinely repeat
    the same chunk (footers, cookie banners) and every position needs its own
    row.
    """
    vectors: list[list[float]] = []
    for start in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
        batch = [EMBEDDING_DOCUMENT_PREFIX + chunk for chunk in chunks[start : start + EMBEDDING_BATCH_SIZE]]
        vectors.extend(await _embed_batch(batch))

    if vectors and len(vectors[0]) != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"{OLLAMA_EMBEDDING_MODEL} returns {len(vectors[0])}-dimensional vectors, "
            f"EMBEDDING_DIMENSIONS is {EMBEDDING_DIMENSIONS}"
        )
    return vectors


async def embed_query(query: str) -> list[float]:
    """Embed a search query so it lives in the same space as the chunks."""
    (vector,) = await _embed(EMBEDDING_QUERY_PREFIX + query, truncate=True)
    return vector


async def _embed_batch(batch: list[str]) -> list[list[float]]:
    """Embed a batch, refusing silent truncation.

    Ollama reports "input too long" for the whole batch without saying which
    item; MAX_WORDS_PER_CHUNK keeps chunks below the model context so this is
    rare, and when it happens the batch is redone one item at a time so the
    oversized ones can be logged and truncated on purpose.
    """
    try:
        return await _embed(batch, truncate=False)
    except ResponseError as error:
        if error.status_code != 400:
            raise

    vectors: list[list[float]] = []
    for text in batch:
        try:
            vectors.extend(await _embed(text, truncate=False))
        except ResponseError as error:
            if error.status_code != 400:
                raise
            log.warning("chunk exceeds the model context, embedding its head only: %.60s…", text)
            vectors.extend(await _embed(text, truncate=True))
    return vectors


async def _embed(text: str | list[str], *, truncate: bool) -> list[list[float]]:
    response = await _client.embed(
        model=OLLAMA_EMBEDDING_MODEL,
        input=text,
        truncate=truncate,
        dimensions=EMBEDDING_DIMENSIONS,
    )
    return [list(vector) for vector in response.embeddings]
