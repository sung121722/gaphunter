"""
GapHunter Configuration
All secrets via environment variables — never hardcode.
"""

import os
import pathlib
from dotenv import load_dotenv

load_dotenv(dotenv_path=pathlib.Path(__file__).parent / ".env", override=True)

# ─── API Keys ────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY      = os.getenv("ANTHROPIC_API_KEY")
SERPAPI_KEY            = os.getenv("SERPAPI_KEY")
GOOGLE_CSE_KEY         = os.getenv("GOOGLE_CSE_KEY")          # Search Console API
GOOGLE_CSE_ID          = os.getenv("GOOGLE_CSE_ID")           # Blogger (EN)
GOOGLE_CSE_ID_KO       = os.getenv("GOOGLE_CSE_ID_KO")        # Tistory (KO)
GOOGLE_SERVICE_ACCOUNT = os.getenv("GOOGLE_SERVICE_ACCOUNT")  # JSON path for GSC OAuth
AMAZON_ASSOCIATES_ID   = os.getenv("AMAZON_ASSOCIATES_ID")
COUPANG_PARTNERS_ID    = os.getenv("COUPANG_PARTNERS_ID")
COLAB_PREDICTOR_URL    = os.getenv("COLAB_PREDICTOR_URL")     # ngrok URL from Colab

# ─── Cost Control (V1 hard limits) ───────────────────────────────────────────
MAX_KEYWORDS_PER_RUN       = int(os.getenv("MAX_KEYWORDS_PER_RUN", 3))
MAX_SERPAPI_CALLS_PER_DAY  = int(os.getenv("MAX_SERPAPI_CALLS_PER_DAY", 10))
MAX_CLAUDE_CALLS_PER_RUN   = int(os.getenv("MAX_CLAUDE_CALLS_PER_RUN", 5))

# DRY_RUN_MODE=True → no real API calls, uses dummy data throughout
DRY_RUN_MODE = os.getenv("DRY_RUN_MODE", "true").lower() in ("true", "1", "yes")

# ─── Gap Score Thresholds ─────────────────────────────────────────────────────
GAP_SCORE_URGENT = 80   # generate content immediately
GAP_SCORE_HIGH   = 45   # generate within 7 days (캠핑 시즌 한시적 하향)
GAP_SCORE_MEDIUM = 40   # add to queue
GAP_SCORE_LOW    = 0    # monitor only

# ─── pytrends Settings ────────────────────────────────────────────────────────
PYTRENDS_DELAY_MIN   = float(os.getenv("PYTRENDS_DELAY_MIN", 2))   # seconds
PYTRENDS_DELAY_MAX   = float(os.getenv("PYTRENDS_DELAY_MAX", 7))   # seconds
PYTRENDS_MAX_RETRIES = int(os.getenv("PYTRENDS_MAX_RETRIES", 5))

# ─── Content Generation Settings ─────────────────────────────────────────────
MIN_WORD_COUNT_EN  = 2000
MIN_CHAR_COUNT_KO  = 1500
CLAUDE_MODEL       = "claude-sonnet-4-20250514"

# Words that signal AI-generated text — must not appear in output
AI_SIGNATURE_WORDS = [
    "comprehensive", "delve", "tapestry", "whimsical", "bustling",
    "seamlessly", "furthermore", "in conclusion", "it's worth noting",
    "it is important to note", "dive deep", "game-changer", "leverage",
    "utilize", "paradigm", "synergy", "holistic",
]

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR   = pathlib.Path(__file__).parent.resolve()
WIKI_DIR   = BASE_DIR / "wiki"
POSTS_DIR  = BASE_DIR / "posts"
RAW_DIR    = BASE_DIR / "raw"
TRENDS_DIR = RAW_DIR / "trends"

# ─── Validation ───────────────────────────────────────────────────────────────
REQUIRED_KEYS_LIVE = [
    ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY),
    ("SERPAPI_KEY",       SERPAPI_KEY),
    ("GOOGLE_CSE_KEY",    GOOGLE_CSE_KEY),
]

def validate_config(dry_run: bool = DRY_RUN_MODE) -> list[str]:
    """Return list of missing keys. Empty list = config OK."""
    if dry_run:
        return []
    return [name for name, val in REQUIRED_KEYS_LIVE if not val]


def print_config_summary() -> None:
    missing = validate_config()
    mode    = "DRY RUN (dummy data)" if DRY_RUN_MODE else "LIVE"

    print(f"\n{'='*50}")
    print(f"  GapHunter Config Summary")
    print(f"{'='*50}")
    print(f"  Mode              : {mode}")
    print(f"  Max keywords/run  : {MAX_KEYWORDS_PER_RUN}")
    print(f"  Max SerpAPI/day   : {MAX_SERPAPI_CALLS_PER_DAY}")
    print(f"  Max Claude/run    : {MAX_CLAUDE_CALLS_PER_RUN}")
    print(f"  Claude model      : {CLAUDE_MODEL}")
    print(f"  Colab URL set     : {'YES' if COLAB_PREDICTOR_URL else 'NO (using dummy predictor)'}")
    print(f"  Wiki dir          : {WIKI_DIR}")
    if missing:
        print(f"\n  ⚠ Missing keys for LIVE mode: {', '.join(missing)}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    print_config_summary()
    issues = validate_config(dry_run=False)
    if issues:
        print(f"[WARN] These keys are unset (OK for dry-run): {issues}")
    else:
        print("[OK] All required keys present.")
