"""ONI Cortex configuration — all settings from env vars."""

import os
import secrets

DATABASE_URL = os.environ.get(
    "CORTEX_DATABASE_URL",
    "postgresql+asyncpg://cortex:cortex@localhost:5432/cortex",
)
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
CORTEX_DOMAIN = os.environ.get("CORTEX_DOMAIN", "cortex.oni.dev")
JWT_SECRET = os.environ.get("CORTEX_JWT_SECRET", secrets.token_hex(32))
API_KEY_PREFIX_LIVE = "oni_live_"
API_KEY_PREFIX_TEST = "oni_test_"

# Tier limits: {plan: {collections, vectors, queries_per_day}}
TIER_LIMITS = {
    "free":       {"collections": 1,   "vectors": 10_000,    "queries_per_day": 500},
    "pro":        {"collections": 5,   "vectors": 250_000,   "queries_per_day": 10_000},
    "team":       {"collections": 25,  "vectors": 1_000_000, "queries_per_day": 50_000},
    "business":   {"collections": 100, "vectors": 5_000_000, "queries_per_day": 200_000},
    "enterprise": {"collections": -1,  "vectors": -1,        "queries_per_day": -1},
}
