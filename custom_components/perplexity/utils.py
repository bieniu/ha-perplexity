"""Utils for Perplexity integration."""

import re

REASONING_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def strip_reasoning(text: str) -> str:
    """Remove reasoning blocks from the model response."""
    return REASONING_BLOCK_RE.sub("", text).strip()
