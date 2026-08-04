"""
Model classification heuristics for auto-inheritance.

Reuses logic from cli/discover.py but as importable functions.
"""


# Tier classification keywords
_FLASH_KEYWORDS = ("flash", "lite", "turbo", "mini", "nano", "fast", "haiku", "small")
_PRO_KEYWORDS = ("pro", "reasoner", "o1", "o3", "opus", "max")


def classify_tier(model_id: str) -> str:
    """Classify model tier from name heuristics."""
    name_lower = model_id.lower()
    parts = set(name_lower.replace("/", "-").replace(".", "-").split("-"))
    for kw in _FLASH_KEYWORDS:
        if kw in parts:
            return "flash"
    return "pro"


def detect_multimodal(model_id: str) -> bool:
    """Detect if model likely supports multimodal/vision input.
    
    P2-4 fix: use part-based matching to avoid false positives.
    """
    name_lower = model_id.lower()
    parts = set(name_lower.replace("/", "-").replace(".", "-").split("-"))
    vision_keywords = (
        "vision", "vl", "gemini", "claude", "gpt-4o", "gpt-4v",
        "grok", "doubao-seed", "omni",
    )
    for kw in vision_keywords:
        if kw in parts:
            return True
    # Compound patterns
    for kw in vision_keywords:
        if "-" in kw and kw in name_lower:
            return True
    return False
