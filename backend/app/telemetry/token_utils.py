def estimate_tokens(text: str) -> int:
    """Very lightweight token estimate for local fallback/non-provider responses."""
    if not text.strip():
        return 0
    # Approximation: ~4 chars/token for English text.
    return max(1, len(text) // 4)
