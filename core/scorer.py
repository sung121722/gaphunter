"""
scorer.py — Gap opportunity scoring module
Combines demand + decay + competition signals into a single gap score.
"""

import sys
import json
import datetime
import logging
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)

# ─── Weights (must sum to 1.0) ────────────────────────────────────────────────
W_DEMAND_GROWTH   = 0.4
W_DECAY_PROB      = 0.3
W_COMPETITION_GAP = 0.2
W_TIMING_ADVANTAGE= 0.1


# ─── Sub-score calculators ────────────────────────────────────────────────────

def _demand_growth_score(growth_rate: float) -> float:
    """
    Convert growth_rate (-1.0 ~ +1.0) to a 0~1 score.
    Negative growth still gets partial score (gap opens when demand dies too).
    """
    # Map: -1.0 → 0.2,  0.0 → 0.5,  +1.0 → 1.0
    return float(np.clip(0.5 + growth_rate * 0.5, 0.0, 1.0))


def _competition_gap_score(competitors: list[dict]) -> float:
    """
    Score (0~1) based on weaknesses in current top competitors.
    Higher score = weaker competition = bigger opportunity.

    Factors:
    - avg word count < 1500 → thin content penalty
    - high avg age penalty → stale content
    - fewer than 3 competitors in SERP → low competition
    """
    if not competitors:
        return 0.8  # no competitors found = wide open gap

    word_counts  = [c.get("word_count", 1500) for c in competitors]
    age_penalties = [c.get("age_penalty", 0.5) for c in competitors]

    avg_words = float(np.mean(word_counts))
    avg_age   = float(np.mean(age_penalties))

    # Thin content bonus: <1500 words = 0.3, >3000 words = 0.0
    thin_score = float(np.clip(1.0 - (avg_words / 3000.0), 0.0, 0.3))

    # Age bonus: old content is easier to beat
    age_score  = avg_age * 0.5  # max 0.5

    # Low competition bonus
    density_score = float(np.clip(1.0 - (len(competitors) / 10.0), 0.0, 0.2))

    return float(np.clip(thin_score + age_score + density_score, 0.0, 1.0))


def _timing_advantage_score(forecast: list[float]) -> float:
    """
    Score (0~1) based on forecast trajectory.
    If demand is rising in the next 30 days, timing is good.
    """
    if not forecast or len(forecast) < 2:
        return 0.5

    arr = np.array(forecast)
    first_half  = float(np.mean(arr[:len(arr)//2]))
    second_half = float(np.mean(arr[len(arr)//2:]))

    if first_half < 1e-9:
        return 0.5

    acceleration = (second_half - first_half) / first_half
    # +50% acceleration → 1.0,  flat → 0.5,  -50% → 0.0
    return float(np.clip(0.5 + acceleration, 0.0, 1.0))


def _estimate_gap_date(decay_probability: float, age_penalty: float) -> tuple[str, int]:
    """
    Estimate when the content gap will open based on decay signals.
    Returns (predicted_gap_date_str, days_until_gap).
    """
    # High decay + old content → gap opens soon
    urgency = (decay_probability * 0.6) + (age_penalty * 0.4)

    # urgency 1.0 → 7 days,  0.5 → 45 days,  0.0 → 90 days
    days = int(90 - (urgency * 83))
    days = max(7, min(90, days))

    gap_date = datetime.date.today() + datetime.timedelta(days=days)
    return str(gap_date), days


def _action_label(score: int) -> str:
    if score >= config.GAP_SCORE_URGENT:
        return "GENERATE_NOW"
    if score >= config.GAP_SCORE_HIGH:
        return "GENERATE_SOON"
    if score >= config.GAP_SCORE_MEDIUM:
        return "QUEUE"
    return "MONITOR"


# ─── Public API ───────────────────────────────────────────────────────────────

def score_gap(keyword: str, predictions: dict) -> dict:
    """
    Compute gap opportunity score for a single keyword.

    Input:  predictions dict from predictor.run_predictions()
    Output: gap result dict with score, action, and reasoning.

    Score formula:
        score = demand_growth(0.4) + decay_prob(0.3)
              + competition_gap(0.2) + timing_advantage(0.1)
    All sub-scores normalized to 0~1, final score scaled to 0~100.
    """
    demand   = predictions.get("demand", {})
    comps    = predictions.get("competitor_predictions", [])

    growth_rate   = demand.get("growth_rate", 0.0)
    forecast      = demand.get("forecast", [])

    # Pick the worst (most decaying) competitor as the primary target
    primary = max(comps, key=lambda c: c.get("decay_probability", 0), default={})
    decay_prob  = primary.get("decay_probability", 0.5)
    age_penalty = primary.get("age_penalty", 0.5)

    # Sub-scores (all 0~1)
    s_demand   = _demand_growth_score(growth_rate)
    s_decay    = decay_prob                          # already 0~1
    s_comp     = _competition_gap_score(comps)
    s_timing   = _timing_advantage_score(forecast)

    # Weighted sum → 0~100 integer
    raw = (
        s_demand  * W_DEMAND_GROWTH   +
        s_decay   * W_DECAY_PROB      +
        s_comp    * W_COMPETITION_GAP +
        s_timing  * W_TIMING_ADVANTAGE
    )
    gap_score = int(round(raw * 100))

    gap_date, days_until = _estimate_gap_date(decay_prob, age_penalty)
    action = _action_label(gap_score)

    return {
        "keyword":            keyword,
        "geo":                predictions.get("geo", "US"),
        "gap_score":          gap_score,
        "action":             action,
        "predicted_gap_date": gap_date,
        "days_until_gap":     days_until,
        "competitor_url":     primary.get("url", ""),
        "decay_probability":  round(decay_prob, 3),
        "sub_scores": {
            "demand_growth":    round(s_demand,  3),
            "decay_prob":       round(s_decay,   3),
            "competition_gap":  round(s_comp,    3),
            "timing_advantage": round(s_timing,  3),
        },
        "scored_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


# ─── Product selection scoring ────────────────────────────────────────────────

# 계절 카테고리 → 성수기 월
SEASONAL_PEAKS = {
    "캠핑": [4, 5, 6, 7, 8, 9],
    "camping": [4, 5, 6, 7, 8, 9],
    "난방": [10, 11, 12, 1, 2],
    "heater": [10, 11, 12, 1, 2],
    "에어컨": [6, 7, 8],
    "선풍기": [6, 7, 8],
    "반려동물": [],  # 제외 없음
    "pet": [],
}

# 제외 카테고리
EXCLUDED_CATEGORIES_KO = ["식품", "음료", "건강기능식품", "소모품", "화장품"]
EXCLUDED_CATEGORIES_EN = ["electronics", "computer"]

# 카테고리 우선순위
CATEGORY_PRIORITY_KO = ["캠핑", "건강가전", "주방가전", "계절가전", "반려동물"]
CATEGORY_PRIORITY_EN = ["Outdoor", "Home Kitchen", "Health", "Tools", "Pet"]


def score_product_selection(
    keyword: str,
    language: str = "en",
    price: float = 0.0,
    review_count: int = 0,
    rating: float = 0.0,
    is_rocket: bool = False,
    category: str = "",
) -> dict:
    """
    상품 선정 점수 계산 (0~100).
    쿠팡(ko) / 아마존(en) 기준 각각 다름.

    Returns:
        {
            score: int,
            eligible: bool,   # 필수 조건 충족 여부
            bonus: int,        # 보너스 점수 합계
            penalty: int,      # 페널티 점수 합계
            reasons: [str],    # 점수 이유 목록
            disqualified: bool # 제외 조건 해당 여부
        }
    """
    reasons = []
    bonus   = 0
    penalty = 0
    disqualified = False

    month = datetime.date.today().month

    if language == "ko":
        # ── 필수 조건 ──
        eligible = (
            is_rocket and
            price >= 20000 and
            review_count >= 100
        )
        if not is_rocket:
            disqualified = True
            reasons.append("제외: 로켓배송 아님")
        if price < 10000:
            disqualified = True
            reasons.append("제외: 객단가 1만원 이하")
        if review_count < 50:
            disqualified = True
            reasons.append("제외: 리뷰 50개 미만")

        # ── 보너스 ──
        if is_rocket:
            bonus += 20
            reasons.append("+20: 로켓배송")
        if price >= 20000:
            bonus += 10
            reasons.append("+10: 객단가 2만원 이상")
        if review_count >= 100:
            bonus += 10
            reasons.append("+10: 리뷰 100개 이상")
        if rating >= 4.9:
            bonus += 10
            reasons.append("+10: 별점 4.9 이상")

        # ── 계절 타이밍 ──
        for kw, months in SEASONAL_PEAKS.items():
            if kw in keyword.lower() and months and month in months:
                bonus += 20
                reasons.append(f"+20: 계절 성수기 ({month}월)")
                break

        # ── 카테고리 페널티 ──
        for excl in EXCLUDED_CATEGORIES_KO:
            if excl in category:
                penalty += 30
                reasons.append(f"-30: 제외 카테고리 ({excl})")
                break

    else:  # en / Blogger
        # ── 필수 조건 ──
        eligible = (price >= 30)

        if price < 30:
            reasons.append("미달: 객단가 $30 미만")

        # ── 보너스 ──
        if price >= 30:
            bonus += 10
            reasons.append("+10: 객단가 $30 이상")
        if rating >= 4.5:
            bonus += 10
            reasons.append("+10: 별점 4.5 이상")

        # 커미션율 추정 (카테고리 기반)
        high_commission_cats = ["outdoor", "home kitchen", "health", "tools", "pet"]
        if any(c in category.lower() for c in high_commission_cats):
            bonus += 15
            reasons.append("+15: 고커미션 카테고리")

        # 30~50대 타겟 상품
        target_keywords = ["camping", "kitchen", "health", "fitness", "garden", "tool"]
        if any(kw in keyword.lower() for kw in target_keywords):
            bonus += 10
            reasons.append("+10: 30~50대 타겟 키워드")

        # ── 카테고리 페널티 ──
        for excl in EXCLUDED_CATEGORIES_EN:
            if excl in category.lower():
                penalty += 10
                reasons.append(f"-10: 저커미션 카테고리 ({excl})")
                break

    score = max(0, min(100, bonus - penalty))

    return {
        "score":         score,
        "eligible":      eligible and not disqualified,
        "disqualified":  disqualified,
        "bonus":         bonus,
        "penalty":       penalty,
        "reasons":       reasons,
    }


def score_all(predictions_list: list[dict]) -> list[dict]:
    """Score multiple keyword predictions and sort by gap_score descending."""
    results = []
    for pred in predictions_list:
        kw = pred.get("keyword", "unknown")
        result = score_gap(kw, pred)
        results.append(result)
        logger.info("Scored '%s': %d (%s)", kw, result["gap_score"], result["action"])

    return sorted(results, key=lambda r: r["gap_score"], reverse=True)


# ─── CLI test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)

    # Load snapshot + predictions
    snapshot_path = config.TRENDS_DIR / "camping_chairs_US.json"
    if not snapshot_path.exists():
        print("Run collector first: py core/collector.py")
        sys.exit(1)

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

    sys.path.insert(0, str(Path(__file__).parent))
    from predictor import run_predictions

    predictions = run_predictions(snapshot)
    result      = score_gap(snapshot["keyword"], predictions)

    print("\n=== Gap Score Result ===")
    print(f"  keyword          : {result['keyword']}")
    print(f"  gap_score        : {result['gap_score']}  ({result['action']})")
    print(f"  predicted_gap    : {result['predicted_gap_date']}  ({result['days_until_gap']} days)")
    print(f"  competitor_url   : {result['competitor_url'][:55]}")
    print(f"  decay_prob       : {result['decay_probability']}")
    print()
    print("  Sub-scores:")
    for k, v in result["sub_scores"].items():
        bar = "#" * int(v * 20)
        print(f"    {k:<20} {v:.3f}  |{bar:<20}|")

    print()
    action_to_label = {
        "GENERATE_NOW":  (config.GAP_SCORE_URGENT, "URGENT  (GENERATE_NOW)"),
        "GENERATE_SOON": (config.GAP_SCORE_HIGH,   "HIGH    (GENERATE_SOON)"),
        "QUEUE":         (config.GAP_SCORE_MEDIUM, "MEDIUM  (QUEUE)"),
        "MONITOR":       (0,                        "LOW     (MONITOR)"),
    }
    for action, (threshold, label) in action_to_label.items():
        marker = " <-- current" if action == result["action"] else ""
        print(f"  {threshold:>3}+ : {label}{marker}")
