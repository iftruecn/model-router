"""
Default configuration values for Model Router.

All magic numbers and thresholds are defined here for easy configuration.
These can be overridden via config.yaml or environment variables.
"""

# ===============================================================
# Connection Pool
# ===============================================================

DEFAULT_MAX_CONNECTIONS: int = 100
DEFAULT_MAX_KEEPALIVE_CONNECTIONS: int = 20
DEFAULT_CONNECTION_TIMEOUT: float = 120.0

# Tiered timeouts (v1.2.0, gap-analysis #1)
DEFAULT_CONNECT_TIMEOUT: float = 10.0    # TCP handshake
DEFAULT_READ_TIMEOUT: float = 60.0       # waiting for response body
DEFAULT_WRITE_TIMEOUT: float = 10.0      # sending request body
DEFAULT_POOL_TIMEOUT: float = 10.0       # waiting for connection from pool

# Concurrency limit (v1.0.9, gap-analysis #1c)
DEFAULT_FORWARDING_CONCURRENCY: int = 10  # max concurrent forwarding requests

# ===============================================================
# Router
# ===============================================================

DEFAULT_MAX_FALLBACK_ATTEMPTS: int = 3
DEFAULT_MAX_TOTAL_TIMEOUT: float = 300.0

# ===============================================================
# Classifier / 领域维度
# ===============================================================

# Supported capability domains
DOMAINS = ("coding", "reasoning", "math", "creative", "translation", "vision", "chat")

# Default capability score when unknown
DEFAULT_CAPABILITY_SCORE: float = 5.0

# Long context thresholds
CLASSIFIER_LONG_CONTEXT_MSG_COUNT: int = 4
CLASSIFIER_LONG_CONTEXT_CHAR_COUNT: int = 500

# Ultra-short greeting threshold
CLASSIFIER_ULTRA_SHORT_THRESHOLD: int = 3

# ===============================================================
# Model Registry / 模型注册中心
# ===============================================================

# Registry mode: "online", "offline", "auto" (auto = try online, fallback offline)
DEFAULT_REGISTRY_MODE: str = "auto"

# Cache settings
REGISTRY_CACHE_DIR: str = ".cache"
REGISTRY_CACHE_FILE: str = "model_registry.json"
REGISTRY_CACHE_TTL: int = 86400  # 24 hours in seconds

# Online data sources
REGISTRY_LMSYS_URL: str = "https://lmarena.ai/api/leaderboard"
REGISTRY_ARTIFICIAL_URL: str = "https://artificialanalysis.ai/api/models"
REGISTRY_FETCH_TIMEOUT: float = 30.0  # seconds

# Merge weights: online vs local config
REGISTRY_ONLINE_WEIGHT: float = 0.7
REGISTRY_LOCAL_WEIGHT: float = 0.3

# ===============================================================
# Smart Router / 智能路由
# ===============================================================

# Scoring weights (configurable)
ROUTER_CAPABILITY_WEIGHT: float = 1.0
ROUTER_COST_WEIGHT: float = 0.3
ROUTER_SPEED_WEIGHT: float = 0.2

# Cost normalization: max cost per 1K tokens (for 0-10 scale)
ROUTER_MAX_COST_PER_1K: float = 0.06  # ~GPT-4o price

# Speed tiers (responses per minute, for normalization)
ROUTER_SPEED_FAST: float = 60.0    # >= 60 rpm = fast
ROUTER_SPEED_SLOW: float = 5.0     # <= 5 rpm = slow

# Routing presets (Cursor-style 3 tiers) — capability/cost/speed weights
ROUTING_PRESETS: dict = {
    "intelligence": {
        "capability_weight": 1.0,
        "cost_weight": 0.05,
        "speed_weight": 0.1,
    },
    "balance": {
        "capability_weight": 1.0,
        "cost_weight": 0.3,
        "speed_weight": 0.2,
    },
    "cost": {
        "capability_weight": 1.0,
        "cost_weight": 0.8,
        "speed_weight": 0.3,
    },
}
ROUTING_DEFAULT_PRESET: str = "balance"

# ===============================================================
# Memory Store / 持久记忆 (v1.0.2)
# ===============================================================

MEMORY_SCHEMA_VERSION: int = 1
MEMORY_DEFAULT_AGENT: str = "default"
MEMORY_MAX_REQUEST_LOG: int = 1000   # ring buffer cap (~500KB)
MEMORY_SAVE_INTERVAL: int = 10       # persist every N requests
MEMORY_DEFAULT_DATA_DIR: str = "data"

# ===============================================================
# Learner / 自学习 (v1.0.2, Gaussian Thompson Sampling)
# ===============================================================

LEARNER_PRIOR_K: float = 10.0        # Bayesian prior strength
LEARNER_HANDOFF_N: int = 200         # samples before learned score gains weight
LEARNER_DEV_THRESHOLD: float = 0.3   # min deviation to justify intervention
LEARNER_UCB_C: float = 0.5           # exploration bonus coefficient
LEARNER_VAR_FLOOR: float = 0.01      # posterior variance floor
LEARNER_EWMA_ALPHA_BASE: float = 0.05   # slow decay (models change rarely)
LEARNER_EWMA_ALPHA_MAX: float = 0.20    # faster reaction on abrupt shifts
LEARNER_FALLBACK_PENALTY: float = -1.0  # quality fallback = strong negative
LEARNER_FEEDBACK_POSITIVE: float = 0.8  # explicit user thumbs-up
LEARNER_FEEDBACK_NEGATIVE: float = -1.0  # explicit user thumbs-down
LEARNER_LATENCY_FULL_MS: float = 10000.0  # latency >= 10s -> speed score 0
LEARNER_BASE_REWARD: float = 0.7     # neutral cost score when pricing unknown

# Routing diversity guard (v1.0.3, anti-collapse per "When Routing Collapses")
DIVERSITY_WINDOW: int = 100          # monitor the last N selections
DIVERSITY_DOMINANCE_THRESHOLD: float = 0.9   # one model > 90% -> degraded
DIVERSITY_EXPLORE_RATE: float = 0.05         # force >= 5% exploration picks

# ===============================================================
# Virtual API Keys / 虚拟密钥 (v1.0.3, P0 #3)
# ===============================================================

AUTH_KEY_PREFIX: str = "mr-sk-"      # OpenAI-style recognizable prefix
AUTH_TOKEN_BYTES: int = 24           # secrets.token_urlsafe(24) -> 32 chars
AUTH_KEYS_FILE: str = "api_keys.json"
AUTH_SCHEMA_VERSION: int = 1
AUTH_MASTER_KEY_ENV: str = "MODEL_ROUTER_MASTER_KEY"
AUTH_ENABLED_ENV: str = "MODEL_ROUTER_AUTH_DISABLED"  # set to "1" as kill switch

# Paths never requiring a key (probes + interactive docs)
AUTH_PUBLIC_PATHS: tuple = ("/health", "/", "/docs", "/openapi.json", "/redoc")

# ===============================================================
# Agent capability adapter layer (v1.0.4, static declaration)
# ===============================================================

CAPABILITIES_TIMEOUT_MS: int = 200   # per-borrow-call timeout ceiling
CAPABILITIES_FILE: str = "capabilities.json"      # persisted declaration
CAPABILITY_EVENTS_MAX: int = 200     # audit ring size (FR-热感知 §3)
# Which enhancement points may use borrowed capabilities (FR §2.2)
CAPABILITIES_USE_FOR: dict = {
    "classification": True,   # vector-assisted classification
    "preference": True,       # read user preference from agent memory
    "domain": False,          # knowledge-base domain match (aggressive, off)
}

# ===============================================================
# Semantic Cache / 语义缓存 (FR-Qoder-v2-platform §FR-P1)
# ===============================================================

CACHE_ENABLED: bool = True
CACHE_TTL_SECONDS: int = 300      # entries older than TTL are ignored
CACHE_CAPACITY: int = 512         # LRU ring size
CACHE_SIM_THRESHOLD: float = 0.95 # bigram-Jaccard similarity to hit
CACHE_MIN_KEY_LEN: int = 8        # queries shorter than this are never cached

# ===============================================================
# Quality Check
# ===============================================================

QUALITY_MIN_LENGTH_FLASH: int = 5
QUALITY_MIN_LENGTH_PRO: int = 80
QUALITY_SKIP_IF_MAX_TOKENS_UNDER: int = 100
QUALITY_REPETITION_THRESHOLD: float = 0.3

# ===============================================================
# Server
# ===============================================================

DEFAULT_HOST: str = "127.0.0.1"
DEFAULT_PORT: int = 6060

# ===============================================================
# Logging
# ===============================================================

DEFAULT_LOG_LEVEL: str = "INFO"
DEFAULT_LOG_FORMAT: str = "[%(asctime)s] [%(levelname)s] %(message)s"
DEFAULT_LOG_DATE_FORMAT: str = "%H:%M:%S"

# ===============================================================
# Request Limits
# ===============================================================

MAX_REQUEST_BODY_SIZE: int = 10 * 1024 * 1024  # 10 MB
