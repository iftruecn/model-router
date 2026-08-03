"""
Multi-dimensional query feature extractor for Model Router.

Extracts domain scores and constraints from user input using weighted
pattern matching across 7 domains: coding, reasoning, math, creative,
translation, vision, chat.

Multilingual support: patterns cover EN, ZH, JA, KO, ES, FR, DE.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from model_router.config.defaults import (
    CLASSIFIER_LONG_CONTEXT_CHAR_COUNT,
    CLASSIFIER_LONG_CONTEXT_MSG_COUNT,
    CLASSIFIER_ULTRA_SHORT_THRESHOLD,
    DOMAINS,
)

logger = logging.getLogger(__name__)


@dataclass
class Pattern:
    """A weighted pattern for domain classification."""
    regex: str
    domain: str  # coding, reasoning, math, creative, translation, vision, chat
    weight: float  # 0.0 to 1.0 (strength of signal)
    description: str = ""
    compiled: Optional[re.Pattern] = field(default=None, repr=False)

    def __post_init__(self):
        self.compiled = re.compile(self.regex, re.IGNORECASE)

    def matches(self, text: str) -> bool:
        """Check if pattern matches the text."""
        return bool(self.compiled and self.compiled.search(text))


@dataclass
class QueryFeatures:
    """Extracted features from a user query."""
    domain_scores: dict = field(default_factory=dict)
    requires_vision: bool = False
    estimated_complexity: int = 1  # 1-10
    context_length: int = 0  # total chars
    message_count: int = 0
    is_ultra_short: bool = False
    matched_patterns: list = field(default_factory=list)

    @property
    def primary_domain(self) -> str:
        """Get the domain with highest score."""
        if not self.domain_scores:
            return "chat"
        return max(self.domain_scores, key=self.domain_scores.get)

    @property
    def primary_score(self) -> float:
        """Get the highest domain score."""
        if not self.domain_scores:
            return 0.0
        return max(self.domain_scores.values())

    def to_dict(self) -> dict:
        """Serialize for logging/debugging."""
        return {
            "primary_domain": self.primary_domain,
            "primary_score": self.primary_score,
            "domain_scores": self.domain_scores,
            "requires_vision": self.requires_vision,
            "estimated_complexity": self.estimated_complexity,
            "context_length": self.context_length,
            "is_ultra_short": self.is_ultra_short,
            "matched_patterns": self.matched_patterns[:10],  # limit for logging
        }


# ===============================================================
# Domain Patterns — Multilingual (EN, ZH, JA, KO, ES, FR, DE)
# Each pattern: (regex, domain, weight, description)
# ===============================================================

DOMAIN_PATTERNS = [
    # --- CODING ---
    Pattern(r'(write|编写|生成|创建|implement|build|develop|create)\s+(code|function|class|program|script|模块|函数|类|程序|コード|함수|código|fonction|code)', "coding", 0.9, "code_creation"),
    Pattern(r'```', "coding", 0.8, "code_block"),
    Pattern(r'(debug|调试|fix|修复|解决|troubleshoot|resolve|デバッグ|直す|디버그|고치다|depurar|déboguer|beheben)', "coding", 0.8, "debugging"),
    Pattern(r'(compile|编译|deploy|部署|publish|发布|run|运行|execute|コンパイル|배포|compilar|déployer|bereitstellen)', "coding", 0.7, "deployment"),
    Pattern(r'(refactor|重构|optimize|优化|improve|enhance)\s+(code|function|performance|代码|函数|性能|コード|パフォーマンス)', "coding", 0.7, "code_optimization"),
    Pattern(r'(regex|regular expression|正则|正規表現|정규식|expresión regular)', "coding", 0.6, "regex"),
    Pattern(r'(api|API|endpoint|接口|REST|GraphQL|SDK)', "coding", 0.6, "api_dev"),
    Pattern(r'(database|数据库|SQL|query|查询|テーブル|テーブル|base de données|Datenbank)', "coding", 0.6, "database"),
    Pattern(r'(git|commit|branch|merge|pull request|PR|版本控制)', "coding", 0.5, "version_control"),
    Pattern(r'(python|javascript|java|rust|go\b|typescript|c\+\+|ruby|php|swift|kotlin)', "coding", 0.4, "language_mention"),
    Pattern(r'(algorithm|算法|sort|排序|search|搜索|binary tree|二叉树|linked list|链表)', "coding", 0.7, "algorithm"),

    # --- REASONING ---
    Pattern(r'(analyze|分析|review|审查|审计|audit|examine|解析|レビュー|분석|analizar|analyser|analysieren)', "reasoning", 0.7, "analysis"),
    Pattern(r'(compare|比较|对比|difference|区别|pros and cons|优缺点|比較|비교|comparar)', "reasoning", 0.6, "comparison"),
    Pattern(r'(explain|解释|为什么|why|how does|原理|reason|cause|なぜ|どうして|por qué|pourquoi|warum)', "reasoning", 0.6, "explanation"),
    Pattern(r'(design|设计|architect|架构|plan|规划|scheme|strategy|策略|設計|설계|diseñar|concevoir|entwerfen)', "reasoning", 0.7, "design"),
    Pattern(r'(系统.*设计|架构.*设计|技术.*方案|システム設計|시스템 설계|diseño de sistema)', "reasoning", 0.9, "system_design"),
    Pattern(r'(multi[- ]?step|step\s*by\s*step|逐步|ステップバイステップ|단계별|paso a paso|étape par étape|schrittweise)', "reasoning", 0.8, "multi_step"),
    Pattern(r'(research|调研|调查|investigate|explore|研究|조사|investigar|rechercher|forschen)', "reasoning", 0.6, "research"),
    Pattern(r'(evaluate|评估|判断|assess|estimate|估算|predict|预测|判断|評価|평가|evaluar|évaluer|bewerten)', "reasoning", 0.7, "evaluation"),
    Pattern(r'(logic|逻辑|推理|deduce|deduction|induction|归纳|論理|推論|논리|lógica|logique|Logik)', "reasoning", 0.8, "logic"),

    # --- MATH ---
    Pattern(r'(\b\d+\s*[+\-*/^]\s*\d+\s*=?|calculate|计算|compute|算|計算|계산|calcular|calculer|berechnen)', "math", 0.8, "arithmetic"),
    Pattern(r'(equation|方程|formula|公式|solve|求解|解方程|方程式|数式|방정식|ecuación|équation|Gleichung)', "math", 0.9, "equation"),
    Pattern(r'(probability|概率|统计|statistics|mean|average|中位数|方差|distribution|分布|確率|통계|probabilidad|statistiques)', "math", 0.8, "statistics"),
    Pattern(r'(calculus|微积分|derivative|导数|integral|积分|limit|极限|微分|積分|미적분|cálculo|calcul)', "math", 0.9, "calculus"),
    Pattern(r'(linear algebra|线性代数|matrix|矩阵|vector|向量|eigenvalue|特征值|行列|행렬|matriz|matrice)', "math", 0.8, "linear_algebra"),
    Pattern(r'(proof|证明|theorem|定理|lemma|引理|corollary|推论|証明|정리|teorema|théorème|Theorem)', "math", 0.9, "proof"),
    Pattern(r'(optimization|最优化|maximize|minimize|最大化|最小化|最適化|최적화|optimización)', "math", 0.7, "optimization"),

    # --- CREATIVE ---
    Pattern(r'(write|写|创作|compose|draft)\s+(story|小说|诗|essay|文章|blog|邮件|letter|speech|故事|诗歌|作文|物語|소설|histoire|Geschichte)', "creative", 0.9, "creative_writing"),
    Pattern(r'(poem|诗|俳句|haiku|sonnet|十四行诗|시|poème|Gedicht)', "creative", 0.9, "poetry"),
    Pattern(r'(brainstorm|头脑风暴|idea|创意|ideation|アイデア|브레인스토밍|lluvia de ideas)', "creative", 0.7, "brainstorm"),
    Pattern(r'(tone|语气|style|风格|formal|informal|casual|professional|tone of voice|トーン|스타일|tono)', "creative", 0.5, "style_adjustment"),
    Pattern(r'(rewrite|改写|paraphrase|换一种说法|rephrase|润色|言い換え|쓰기 직기|reescribir|réécrire)', "creative", 0.6, "rewriting"),
    Pattern(r'(marketing|营销|广告|advertisement|copywriting|文案|slogan|标语|マーケティング|마케팅|marketing)', "creative", 0.6, "marketing_copy"),
    Pattern(r'(summarize|总结|摘要|概括|要約|요약|resumir|résumer|zusammenfassen)', "creative", 0.5, "summarization"),

    # --- TRANSLATION ---
    Pattern(r'(translate|翻译|翻訳|번역|traducir|traduire|übersetzen)', "translation", 0.9, "translation_explicit"),
    Pattern(r'(how to say|怎么说|用.*说|in (english|chinese|japanese|korean|spanish|french|german))', "translation", 0.8, "translation_how_to_say"),
    Pattern(r'(convert|转换|に変換|로 변환|convertir en|convertir en)', "translation", 0.4, "conversion"),

    # --- VISION ---
    Pattern(r'(image|图片|照片|截图|screenshot|photo|picture|图像|画像|사진|imagen|image|bild)', "vision", 0.8, "vision_image"),
    Pattern(r'(看到|看见|识别|recognize|检测|detect|describe this|見る|認識|인식|ver|reconnaître|sehen)', "vision", 0.7, "vision_recognize"),
    Pattern(r'(这张|这幅|图中|图上|图片里|この画像|이 이미지|esta imagen|cette image|dieses bild)', "vision", 0.9, "vision_reference"),
    Pattern(r'\.(png|jpg|jpeg|gif|webp|bmp)\b', "vision", 0.9, "vision_file"),
    Pattern(r'(chart|图表|diagram|示意图|graph|图形|フローチャート|차트|diagrama|diagramme|Diagramm)', "vision", 0.6, "vision_chart"),

    # --- CHAT (simple conversational) ---
    Pattern(r'^(hi|hello|hey|你好|您好|嗨|在吗|早上好|晚上好|good morning|good evening)', "chat", 0.3, "greeting"),
    Pattern(r'(thank|thanks|谢谢|感謝|ありがとう|감사합니다|gracias|merci|danke)', "chat", 0.2, "gratitude"),
    Pattern(r'^(ok|okay|好的|明白了|知道了|收到|got it|わかった|알겠어)', "chat", 0.2, "acknowledgment"),
    Pattern(r'(what|who|when|where)\s+\w+\s*\??$', "chat", 0.3, "simple_factual_en"),
    Pattern(r'^(何|谁|什么时候|哪里|哪|多少|几)', "chat", 0.3, "simple_factual_zh"),
]


class DomainClassifier:
    """
    Multi-dimensional domain classifier.

    Extracts domain scores from user input, then the router uses these
    scores to match against model capability profiles.

    Replaces the old binary flash/pro classifier.
    """

    def __init__(
        self,
        patterns: list[Pattern] = None,
    ):
        self._patterns = patterns or DOMAIN_PATTERNS

    def classify(
        self,
        messages: list,
        models_config: dict = None,
    ) -> QueryFeatures:
        """
        Extract features from messages.

        Args:
            messages: Chat messages list
            models_config: Optional models config (unused, kept for API compat)

        Returns:
            QueryFeatures with domain scores and constraints
        """
        user_text = self._extract_user_text(messages).lower()
        msg_count = len(messages)
        total_chars = len(user_text)

        features = QueryFeatures(
            domain_scores={d: 0.0 for d in DOMAINS},
            context_length=total_chars,
            message_count=msg_count,
        )

        # 1. Check for image input → vision
        if self._has_image_input(messages):
            features.requires_vision = True
            features.domain_scores["vision"] = 10.0
            features.matched_patterns.append("vision:image_input(10.0)")

        # 2. Accumulate domain scores from pattern matching
        for pat in self._patterns:
            if pat.matches(user_text):
                features.domain_scores[pat.domain] = (
                    features.domain_scores.get(pat.domain, 0.0) + pat.weight
                )
                features.matched_patterns.append(f"{pat.domain}:{pat.description}({pat.weight})")

                # Auto-enable vision requirement
                if pat.domain == "vision" and pat.weight >= 0.8:
                    features.requires_vision = True

        # 3. Context length boost → reasoning (longer = more complex)
        if msg_count > CLASSIFIER_LONG_CONTEXT_MSG_COUNT:
            features.domain_scores["reasoning"] = features.domain_scores.get("reasoning", 0) + 1.0
        if total_chars > CLASSIFIER_LONG_CONTEXT_CHAR_COUNT:
            features.domain_scores["reasoning"] = features.domain_scores.get("reasoning", 0) + 1.0

        # 4. Estimate complexity (1-10)
        features.estimated_complexity = self._estimate_complexity(user_text, msg_count, features)

        # 5. Ultra-short detection
        stripped = user_text.strip().rstrip("!！。.,，?？!?¡¿")
        features.is_ultra_short = len(stripped) <= CLASSIFIER_ULTRA_SHORT_THRESHOLD

        # 6. If no strong signal, default to chat
        if features.primary_score < 0.5:
            features.domain_scores["chat"] = max(features.domain_scores.get("chat", 0), 0.5)

        logger.debug("Query features: %s", features.to_dict())
        return features

    def _estimate_complexity(
        self,
        text: str,
        msg_count: int,
        features: QueryFeatures,
    ) -> int:
        """Estimate query complexity (1-10)."""
        score = 1.0

        # Length signals
        if len(text) > 100:
            score += 1
        if len(text) > 500:
            score += 1
        if len(text) > 2000:
            score += 1

        # Message count signals
        if msg_count > 4:
            score += 1
        if msg_count > 10:
            score += 1

        # Domain signal strength
        max_domain_score = features.primary_score
        if max_domain_score > 3:
            score += 1
        if max_domain_score > 6:
            score += 1

        # Multi-step indicator
        if any(kw in text for kw in ("step by step", "逐步", "multi-step", "ステップバイステップ")):
            score += 1

        return min(10, max(1, int(score)))

    def _extract_user_text(self, messages: list) -> str:
        """Extract user text from messages, handle multimodal content."""
        parts = []
        for msg in messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(part.get("text", ""))
            else:
                parts.append(str(content))
        return " ".join(parts).strip()

    def _has_image_input(self, messages: list) -> bool:
        """Check if messages contain image data."""
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        return True
        return False


# Global singleton instance
domain_classifier = DomainClassifier()
