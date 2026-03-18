"""
Recursive text chunker for RAG ingestion.

Splits documents into overlapping chunks suitable for embedding and
vector storage. Uses a recursive character-splitting strategy:
try paragraph boundaries first, then sentences, then words.
"""


def chunk_text(
    text: str,
    *,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
    separators: list[str] | None = None,
) -> list[str]:
    """
    Split text into overlapping chunks.

    Args:
        text: The full document text.
        chunk_size: Target size of each chunk in characters.
        chunk_overlap: Number of overlapping characters between consecutive chunks.
        separators: Boundary characters to split on, tried in order.
                    Default: double newline → single newline → sentence end → space.

    Returns:
        A list of text chunks.
    """
    if separators is None:
        separators = ["\n\n", "\n", ". ", " "]

    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    return _recursive_split(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap, separators=separators)


def _recursive_split(
    text: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
    separators: list[str],
) -> list[str]:
    """Try each separator in order; fall back to character split."""
    for sep in separators:
        if sep in text:
            parts = text.split(sep)
            chunks = _merge_parts(parts, sep=sep, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            # If we got a reasonable split, return it
            if len(chunks) > 1 or (len(chunks) == 1 and len(chunks[0]) <= chunk_size):
                return chunks

    # Last resort: hard character split with overlap
    return _hard_split(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)


def _merge_parts(
    parts: list[str],
    *,
    sep: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    """Merge small parts into chunks that respect chunk_size."""
    chunks: list[str] = []
    current = ""

    for part in parts:
        candidate = f"{current}{sep}{part}" if current else part

        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current.strip())
            current = part

    if current.strip():
        chunks.append(current.strip())

    # Add overlap: prepend tail of previous chunk to next chunk
    if chunk_overlap > 0 and len(chunks) > 1:
        overlapped: list[str] = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_tail = chunks[i - 1][-chunk_overlap:]
            overlapped.append(f"{prev_tail}{chunks[i]}")
        chunks = overlapped

    return chunks


def _hard_split(text: str, *, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Character-level split when no separator works."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - chunk_overlap if chunk_overlap > 0 else end
    return chunks
