"""
competition_analyzer.py
────────────────────────
collector.py의 SERP 경쟁자 데이터를 받아
competition_gap과 timing_advantage를 실제로 계산합니다.

사용:
    from core.competition_analyzer import analyze_competition, analyze_timing
    from core.competition_analyzer import adapt_competitors

    # collector.py snapshot의 competitors 변환 후 사용
    adapted = adapt_competitors(snapshot["competitors"])
    trends_float = [row["value"] for row in snapshot["trend_series"]]

    comp   = analyze_competition(adapted)
    timing = analyze_timing(trends_float)

    # scorer.py에 override로 전달
    gap_result = score_gap(kw, predictions,
                           competition_gap_override=comp.score,
                           timing_advantage_override=timing.score)
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import math
import logging

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# 포맷 어댑터
# ══════════════════════════════════════════════════════════════

def adapt_competitors(competitor_pages: list) -> list:
    """
    collector.py의 crawl_competitor_page() 결과를
    analyze_competition()이 기대하는 형식으로 변환합니다.

    collector 포맷:
        {"url", "word_count", "published_date", "body_text", ...}

    competition_analyzer 포맷:
        {"url", "word_count", "last_updated", "domain"}
    """
    from urllib.parse import urlparse
    result = []
    for c in competitor_pages:
        url    = c.get("url", "")
        domain = urlparse(url).netloc if url else ""
        result.append({
            "url":          url,
            "word_count":   c.get("word_count", 0),
            "last_updated": c.get("published_date"),   # 필드명 매핑
            "domain":       domain,
        })
    return result


# ══════════════════════════════════════════════════════════════
# 1. competition_gap 계산
# ══════════════════════════════════════════════════════════════

@dataclass
class CompetitionResult:
    score: float               # 0.0~1.0 (높을수록 경쟁 빈틈 있음)
    avg_word_count: int        # 경쟁자 평균 단어수
    avg_freshness_days: float  # 경쟁자 평균 마지막 업데이트 (일 전)
    weak_count: int            # 약한 경쟁자 수
    total_count: int           # 분석한 경쟁자 수
    breakdown: dict


def analyze_competition(serp_results: list) -> CompetitionResult:
    """
    SERP 상위 결과를 분석해 competition_gap 점수를 계산.

    Args:
        serp_results: adapt_competitors()로 변환된 경쟁자 리스트.
            각 항목: {
                "url": str,
                "word_count": int,
                "last_updated": str|None,  # ISO 날짜 문자열
                "domain": str,
            }

    Returns:
        CompetitionResult (.score 를 scorer.py에 직접 전달)
    """
    if not serp_results:
        logger.warning("[COMPETITION] SERP 데이터 없음. 중간값 0.5 반환.")
        return CompetitionResult(
            score=0.5, avg_word_count=0, avg_freshness_days=0.0,
            weak_count=0, total_count=0,
            breakdown={"reason": "no_serp_data"}
        )

    now = datetime.now(timezone.utc)
    word_counts = []
    freshness_days_list = []
    weak_count = 0

    for result in serp_results[:10]:
        wc = result.get("word_count", 0)
        word_counts.append(wc)

        # freshness: 마지막 업데이트로부터 며칠 지났는지
        last_updated = result.get("last_updated")
        if last_updated:
            try:
                updated_str = str(last_updated)
                # ISO datetime 또는 date string 모두 처리
                if "T" in updated_str:
                    updated_dt = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                    if updated_dt.tzinfo is None:
                        updated_dt = updated_dt.replace(tzinfo=timezone.utc)
                else:
                    from datetime import date as _date
                    d = _date.fromisoformat(updated_str[:10])
                    updated_dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
                days_old = (now - updated_dt).days
            except (ValueError, TypeError):
                days_old = 365
        else:
            days_old = 365

        freshness_days_list.append(days_old)

        # 약한 경쟁자: 단어수 < 800 OR 1년 이상 업데이트 없음
        if wc < 800 or days_old > 365:
            weak_count += 1

    n = len(word_counts)
    avg_word_count = int(sum(word_counts) / n) if n else 0
    avg_freshness  = sum(freshness_days_list) / len(freshness_days_list) if freshness_days_list else 0

    # ── 단어수 점수 (경쟁자 평균이 짧을수록 빈틈 있음) ──
    # 평균 500 이하 -> 1.0 / 평균 2000 이상 -> 0.0
    word_score = _clamp(1.0 - (avg_word_count - 500) / 1500, 0.0, 1.0)

    # ── 신선도 점수 (경쟁자가 오래될수록 빈틈 있음) ──
    # 평균 90일 이내 -> 0.0 / 평균 365일 이상 -> 1.0
    freshness_score = _clamp((avg_freshness - 90) / 275, 0.0, 1.0)

    # ── 약한 경쟁자 비율 ──
    weak_ratio = weak_count / len(serp_results)

    # 최종 competition_gap: 세 요소 가중 평균
    score = round((word_score * 0.40 + freshness_score * 0.35 + weak_ratio * 0.25), 4)

    logger.info(
        f"[COMPETITION] score={score:.3f} | "
        f"avg_words={avg_word_count} | avg_age={avg_freshness:.0f}d | "
        f"weak={weak_count}/{len(serp_results)}"
    )

    return CompetitionResult(
        score=score,
        avg_word_count=avg_word_count,
        avg_freshness_days=avg_freshness,
        weak_count=weak_count,
        total_count=len(serp_results),
        breakdown={
            "word_score":      round(word_score, 4),
            "freshness_score": round(freshness_score, 4),
            "weak_ratio":      round(weak_ratio, 4),
        }
    )


# ══════════════════════════════════════════════════════════════
# 2. timing_advantage 계산
# ══════════════════════════════════════════════════════════════

@dataclass
class TimingResult:
    score: float                      # 0.0~1.0 (높을수록 지금이 발행 타이밍)
    momentum: float                   # 최근 4주 평균 / 52주 평균
    is_seasonal_peak: bool
    weeks_to_peak: Optional[int]      # None이면 비계절성
    breakdown: dict


def analyze_timing(trends_data: list) -> TimingResult:
    """
    pytrends 52주 검색량 데이터를 분석해 timing_advantage 점수를 계산.

    Args:
        trends_data: 주간 검색 관심도 값 리스트 (0~100).
                     collector.py trend_series의 value들.
                     [가장_오래된_주, ..., 가장_최근_주] 순서.

    Returns:
        TimingResult (.score 를 scorer.py에 직접 전달)
    """
    if not trends_data or len(trends_data) < 8:
        logger.warning("[TIMING] 트렌드 데이터 부족. 중간값 0.5 반환.")
        return TimingResult(
            score=0.5, momentum=1.0, is_seasonal_peak=False,
            weeks_to_peak=None, breakdown={"reason": "insufficient_data"}
        )

    data      = trends_data[-52:]   # 최대 52주
    recent_4w = data[-4:]
    full_avg  = sum(data) / len(data)

    if full_avg == 0:
        return TimingResult(
            score=0.3, momentum=0.0, is_seasonal_peak=False,
            weeks_to_peak=None, breakdown={"reason": "zero_volume"}
        )

    # ── 모멘텀: 최근 4주 평균 / 전체 평균 ──
    recent_avg = sum(recent_4w) / len(recent_4w)
    momentum   = round(recent_avg / full_avg, 4)

    # ── 계절 피크 탐지 ──
    peak_val = max(data)
    peak_idx = data.index(peak_val)
    weeks_from_peak = (len(data) - 1) - peak_idx

    is_seasonal = (peak_val / full_avg) > 1.6  # 피크가 평균의 1.6배 이상

    if is_seasonal:
        weeks_ahead = -weeks_from_peak
        if 4 <= weeks_ahead <= 12:
            seasonal_score = 1.0
            weeks_to_peak  = weeks_ahead
        elif weeks_ahead > 12:
            seasonal_score = 0.5
            weeks_to_peak  = weeks_ahead
        elif 0 <= weeks_from_peak <= 3:
            seasonal_score = 0.7
            weeks_to_peak  = None
        else:
            seasonal_score = 0.2
            weeks_to_peak  = None
        is_seasonal_peak = True
    else:
        seasonal_score   = 0.5
        weeks_to_peak    = None
        is_seasonal_peak = False

    # ── 모멘텀 점수 변환 ──
    # momentum 1.5 이상 -> 1.0 / 0.5 이하 -> 0.0
    momentum_score = _clamp((momentum - 0.5) / 1.0, 0.0, 1.0)

    if is_seasonal:
        score = round(seasonal_score * 0.65 + momentum_score * 0.35, 4)
    else:
        score = round(momentum_score * 0.70 + seasonal_score * 0.30, 4)

    logger.info(
        f"[TIMING] score={score:.3f} | momentum={momentum:.3f} | "
        f"seasonal={is_seasonal} | weeks_to_peak={weeks_to_peak}"
    )

    return TimingResult(
        score=score,
        momentum=momentum,
        is_seasonal_peak=is_seasonal_peak,
        weeks_to_peak=weeks_to_peak,
        breakdown={
            "momentum_score":  round(momentum_score, 4),
            "seasonal_score":  round(seasonal_score, 4),
            "is_seasonal":     is_seasonal,
            "peak_idx":        peak_idx,
        }
    )


# ══════════════════════════════════════════════════════════════
# 유틸
# ══════════════════════════════════════════════════════════════

def _clamp(value: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(max_val, value))
