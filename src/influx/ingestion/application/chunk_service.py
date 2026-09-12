from influx.core.config import CHUNK_OVERLAP_WORDS, MAX_WORDS_PER_CHUNK



def chunkify_text(
    text: str,
    *,
    max_words: int = MAX_WORDS_PER_CHUNK,
    overlap: int = CHUNK_OVERLAP_WORDS,
) -> list[str]:
    """Split text into windows of at most `max_words` words.
    
    Consecutive windows share `overlap` words so a sentence cut by the boundary
    still appears whole in one of them. Whitespace is normalised: runs of
    spaces, tabs and newlines all count as a single separator.
    """
    if not 0 <= overlap < max_words:
        raise ValueError("overlap must be smaller than max_words")

    words = text.split()
    if not words:
        return []

    step = max_words - overlap
    chunks = [" ".join(words[start : start + max_words]) for start in range(0, len(words), step)]
    # The last window can be a strict suffix of the previous one; drop it.
    if len(chunks) > 1 and len(words) - (len(chunks) - 1) * step <= overlap:
        chunks.pop()
    return chunks
