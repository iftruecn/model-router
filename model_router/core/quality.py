"""
Quality checker for Model Router v1.0.9.

Improved quality checking with:
- Composite checking (multiple strategies combined)
- Reduced false positives (refusal pattern refinement)
- Configurable thresholds
- Multilingual support: EN, ZH, JA, KO, ES, FR, DE
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

from model_router.config.defaults import (
    QUALITY_MIN_LENGTH_FLASH,
    QUALITY_MIN_LENGTH_PRO,
    QUALITY_REPETITION_THRESHOLD,
    QUALITY_SKIP_IF_MAX_TOKENS_UNDER,
)

logger = logging.getLogger(__name__)


@dataclass
class QualityResult:
    """Result of quality check."""
    passed: bool
    reason: str
    details: Optional[dict] = None


class QualityChecker:
    """
    Improved quality checker with reduced false positives and multilingual support.

    Key improvements over v1.0:
    1. Refusal patterns require combination (not single keyword)
    2. Configurable min length by tier
    3. Better repetition detection
    4. Skip checks for explicit short-output requests
    5. Multilingual refusal detection (EN, ZH, JA, KO, ES, FR, DE)
    """

    def __init__(
        self,
        min_length_flash: int = QUALITY_MIN_LENGTH_FLASH,
        min_length_pro: int = QUALITY_MIN_LENGTH_PRO,
        repetition_threshold: float = QUALITY_REPETITION_THRESHOLD,
        skip_if_max_tokens_under: int = QUALITY_SKIP_IF_MAX_TOKENS_UNDER,
    ):
        self._min_length_flash = min_length_flash
        self._min_length_pro = min_length_pro
        self._repetition_threshold = repetition_threshold
        self._skip_if_max_tokens_under = skip_if_max_tokens_under

    def check(
        self,
        response_text: str,
        model_key: str,
        models_config: dict,
        max_tokens: Optional[int] = None,
    ) -> QualityResult:
        """
        Check output quality.

        Args:
            response_text: The model's response text
            model_key: Model identifier
            models_config: Models configuration
            max_tokens: User-requested max_tokens (for skip logic)

        Returns:
            QualityResult with passed/reason/details
        """
        details = {
            "text_length": len(response_text.strip()) if response_text else 0,
            "checks_performed": [],
        }

        # 1. Empty response check
        if not response_text or not response_text.strip():
            details["checks_performed"].append("empty:FAIL")
            return QualityResult(False, "empty_response", details)

        # 2. Skip length check for explicit short-output requests
        if max_tokens and max_tokens < self._skip_if_max_tokens_under:
            details["checks_performed"].append(f"skip_length(max_tokens={max_tokens})")
            return QualityResult(True, "ok_small_max_tokens", details)

        # 3. Length check by tier
        tier = models_config.get(model_key, {}).get("tier", "pro")
        min_len = self._min_length_flash if tier == "flash" else self._min_length_pro
        text_length = len(response_text.strip())

        if text_length < min_len:
            details["checks_performed"].append(f"length:FAIL({text_length}<{min_len})")
            return QualityResult(
                False,
                f"too_short({text_length}<{min_len})",
                details,
            )
        details["checks_performed"].append(f"length:OK({text_length}>={min_len})")

        # 4. Improved refusal detection (combination-based, multilingual)
        refusal_result = self._check_refusal(response_text)
        details["checks_performed"].append(f"refusal:{refusal_result}")

        if refusal_result == "FAIL":
            # Only fail if refusal + short content (combination check)
            if text_length < min_len * 2:
                return QualityResult(False, "refusal_short_response", details)
            # If response is long enough, don't fail on refusal alone
            logger.debug(
                "Refusal pattern matched but response is long (%d chars), passing",
                text_length,
            )

        # 5. Repetition detection
        repetition_result = self._check_repetition(response_text)
        details["checks_performed"].append(f"repetition:{repetition_result}")

        if repetition_result == "FAIL":
            return QualityResult(False, "highly_repetitive", details)

        return QualityResult(True, "ok", details)

    def _check_refusal(self, text: str) -> str:
        """
        Check for refusal patterns with reduced false positives.
        Multilingual: EN, ZH, JA, KO, ES, FR, DE

        v1.0 issue: Single keywords like "无法" would trigger refusal.
        v1.0.1: Require combination of refusal language + short/no substance.
        """
        # Strong refusal patterns (multilingual) — require combination with short content
        strong_refusal = [
            # EN
            r'\b(I cannot help|I\'m unable to|I won\'t be able to|I cannot assist)\b',
            # ZH
            r'(抱歉.*无法|对不起.*不能|我无法帮助|很遗憾.*不能)',
            # JA
            r'(申し訳.*できません|お手伝い.*できません|残念.*できません)',
            # KO
            r'(죄송.*수 없습니다|도움.*수 없습니다)',
            # ES
            r'(lo siento.*no puedo|no puedo ayudar)',
            # FR
            r'(je suis désolé.*ne peux pas|je ne peux pas aider)',
            # DE
            r'(es tut mir leid.*kann nicht|ich kann nicht helfen)',
        ]

        # Weak refusal patterns (multilingual) — alone not enough to fail
        weak_refusal = [
            # EN
            r'\b(as an AI|as a language model|I cannot|I can\'t)\b',
            # ZH
            r'(作为.*AI|作为一个人工智能|无法|不能)',
            # JA
            r'(AIとして|できません|申し訳ありません)',
            # KO
            r'(AI로서|수 없습니다|죄송합니다)',
            # ES
            r'(como IA|como modelo de lenguaje)',
            # FR
            r'(en tant qu\'IA|en tant que modèle)',
            # DE
            r'(als KI|als Sprachmodell)',
        ]

        text_lower = text.lower()

        # Check strong refusal first
        for pat in strong_refusal:
            if re.search(pat, text_lower, re.IGNORECASE):
                return "FAIL"

        # Weak refusal alone is not enough
        weak_matches = sum(1 for pat in weak_refusal if re.search(pat, text_lower, re.IGNORECASE))
        if weak_matches >= 2:  # Multiple weak signals = likely refusal
            return "WARN"

        return "OK"

    def _check_repetition(self, text: str) -> str:
        """
        Check for repetitive content (hallucination marker).

        Improved: Only flag if significant portion is repetitive.
        """
        lines = text.strip().split("\n")
        if len(lines) <= 3:
            return "OK"  # Too short to judge

        non_empty_lines = [line.strip() for line in lines if line.strip()]
        if not non_empty_lines:
            return "FAIL"

        unique_lines = len(set(non_empty_lines))
        ratio = unique_lines / len(non_empty_lines)

        if ratio < self._repetition_threshold:
            return "FAIL"

        return "OK"


# Global singleton instance
quality_checker = QualityChecker()