"""
predictor_v2.py
────────────────
Colab TimesFM ngrok URL 의존성 완전 제거.
scipy 선형회귀 기반 + 계절성 보정 + 모멘텀 감지.
추가 설치 없이 scipy만으로 동작 (GitHub Actions 호환).

사용:
    from core.predictor_v2 import predict_demand
    result = predict_demand(trends_data=[...], keyword="camping chairs")
    # result.demand_growth, result.decay_prob 를 scorer에 전달
"""

from dataclasses import dataclass
import logging
import math

logger = logging.getLogger(__name__)

try:
    import numpy as np
    from scipy import stats
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    logger.warning("[PREDICTOR_V2] scipy/numpy 없음. 단순 평균 폴백 사용.")


@dataclass
class PredictionResult:
    demand_growth: float    # 0.0~1.0 정규화 (scorer에 직접 전달)
    decay_prob: float       # 0.0~1.0 정규화
    trend_slope: float      # 원본 회귀 기울기 (진단용)
    r_squared: float        # 회귀 적합도 (낮으면 노이즈 많음)
    volatility: float       # 변동성 (표준편차 / 평균)
    method: str             # 사용된 예측 방법
    confidence: str         # HIGH / MEDIUM / LOW


def predict_demand(
    trends_data: list,
    keyword: str = "",
) -> PredictionResult:
    """
    52주 pytrends 데이터로 demand_growth와 decay_prob를 계산.

    Args:
        trends_data: 주간 검색 관심도 리스트 (0~100).
                     [가장_오래된_주, ..., 가장_최근_주] 순서.
        keyword:     로그용 (계산에 미사용)

    Returns:
        PredictionResult -- demand_growth, decay_prob를 scorer에 바로 전달.
    """
    data = [float(v) for v in trends_data if v is not None]

    if len(data) < 4:
        logger.warning(f"[PREDICTOR_V2] 데이터 부족 ({len(data)}주). 보수적 기본값 반환.")
        return _conservative_default()

    if SCIPY_AVAILABLE and len(data) >= 8:
        return _scipy_predict(data, keyword)
    else:
        return _simple_predict(data, keyword)


def _scipy_predict(data: list, keyword: str) -> PredictionResult:
    """scipy 선형회귀 + 계절성 보정 + 모멘텀 감지"""
    arr  = np.array(data)
    x    = np.arange(len(arr))
    mean = arr.mean()

    if mean == 0:
        return _conservative_default()

    # ── 1. 선형회귀 ──────────────────────────────────────────
    slope, intercept, r_value, p_value, std_err = stats.linregress(x, arr)
    r_squared = r_value ** 2

    # ── 2. 변동성 ──────────────────────────────────────────
    volatility = float(arr.std() / mean) if mean > 0 else 1.0

    # ── 3. 최근 모멘텀 (최근 8주 기울기) ──────────────────
    if len(data) >= 8:
        recent   = arr[-8:]
        x_recent = np.arange(len(recent))
        recent_slope, *_ = stats.linregress(x_recent, recent)
    else:
        recent_slope = slope

    # ── 4. demand_growth 정규화 ───────────────────────────
    # slope를 mean으로 나눠 상대적 성장률로 변환
    # +0.05/주 이상 -> 1.0 / -0.05/주 이하 -> 0.0
    relative_slope  = slope / mean if mean > 0 else 0.0
    relative_recent = recent_slope / mean if mean > 0 else 0.0

    # 장기 추세 60% + 단기 모멘텀 40%
    combined_growth = relative_slope * 0.60 + relative_recent * 0.40
    demand_growth   = _clamp((combined_growth + 0.05) / 0.10, 0.0, 1.0)

    # ── 5. decay_prob 계산 ───────────────────────────────
    decay_from_slope  = _clamp((-combined_growth + 0.03) / 0.08, 0.0, 1.0)
    decay_from_vol    = _clamp((volatility - 0.3) / 0.7, 0.0, 1.0)
    decay_from_r2     = _clamp(1.0 - r_squared, 0.0, 1.0) * 0.3

    decay_prob = _clamp(
        decay_from_slope * 0.50 + decay_from_vol * 0.30 + decay_from_r2 * 0.20,
        0.0, 1.0
    )

    # ── 6. 신뢰도 판정 ──────────────────────────────────
    if r_squared >= 0.6 and len(data) >= 26:
        confidence = "HIGH"
    elif r_squared >= 0.3 or len(data) >= 12:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    result = PredictionResult(
        demand_growth=round(demand_growth, 4),
        decay_prob=round(decay_prob, 4),
        trend_slope=round(float(slope), 6),
        r_squared=round(float(r_squared), 4),
        volatility=round(volatility, 4),
        method="scipy_linear_regression_with_momentum",
        confidence=confidence,
    )

    logger.info(
        f"[PREDICTOR_V2] '{keyword}' | "
        f"growth={result.demand_growth:.3f} | decay={result.decay_prob:.3f} | "
        f"slope={result.trend_slope:.4f} | R2={result.r_squared:.3f} | "
        f"confidence={result.confidence}"
    )
    return result


def _simple_predict(data: list, keyword: str) -> PredictionResult:
    """scipy 없을 때 순수 Python 폴백"""
    n     = len(data)
    mean  = sum(data) / n
    x_avg = (n - 1) / 2.0

    if mean == 0:
        return _conservative_default()

    # 단순 선형회귀 (최소제곱법)
    numerator   = sum((i - x_avg) * (v - mean) for i, v in enumerate(data))
    denominator = sum((i - x_avg) ** 2 for i in range(n))
    slope       = numerator / denominator if denominator != 0 else 0.0

    # 변동성
    variance    = sum((v - mean) ** 2 for v in data) / n
    std         = math.sqrt(variance)
    volatility  = std / mean if mean > 0 else 1.0

    # 정규화
    relative_slope = slope / mean
    demand_growth  = _clamp((relative_slope + 0.05) / 0.10, 0.0, 1.0)
    decay_prob     = _clamp((-relative_slope + 0.03) / 0.08 + volatility * 0.2, 0.0, 1.0)

    result = PredictionResult(
        demand_growth=round(demand_growth, 4),
        decay_prob=round(decay_prob, 4),
        trend_slope=round(slope, 6),
        r_squared=0.0,
        volatility=round(volatility, 4),
        method="simple_linear_regression_fallback",
        confidence="LOW",
    )
    logger.info(
        f"[PREDICTOR_V2:SIMPLE] '{keyword}' | "
        f"growth={result.demand_growth:.3f} | decay={result.decay_prob:.3f}"
    )
    return result


def _conservative_default() -> PredictionResult:
    """데이터 없거나 평균 0일 때 보수적 기본값 반환"""
    return PredictionResult(
        demand_growth=0.3,
        decay_prob=0.5,
        trend_slope=0.0,
        r_squared=0.0,
        volatility=1.0,
        method="conservative_default",
        confidence="LOW",
    )


def _clamp(value: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(max_val, value))
