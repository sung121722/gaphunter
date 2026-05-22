"""
scorer_v2.py
─────────────
[DEPRECATED] 이 모듈은 scorer.py에 통합되었습니다.
scorer.py의 score_gap()이 competition_gap_override / timing_advantage_override
파라미터를 통해 동일한 기능을 제공합니다.

카테고리별 가중치 로직은 category_config.py → scorer.py로 이전 예정.
현재는 하위 호환성을 위해 유지. 직접 import 하지 마세요.

사용:
    from core.scorer_v2 import calculate_gap_score, should_generate
    result = calculate_gap_score(
        demand_growth=0.7,
        decay_prob=0.6,
        competition_gap=0.5,
        timing_advantage=0.8,
        category="camping",
    )
    if should_generate(result):
        ...
"""

import sys
import logging
from dataclasses import dataclass
from pathlib import Path

# category_config.py는 프로젝트 루트에 위치
sys.path.insert(0, str(Path(__file__).parent.parent))

from category_config import get_config, GapWeights

logger = logging.getLogger(__name__)


@dataclass
class GapScoreResult:
    score: float
    grade: str      # GENERATE_NOW / GENERATE_SOON / BORDERLINE / USE_FALLBACK
    weights: GapWeights
    breakdown: dict  # 각 요소별 기여 점수
    category: str


def calculate_gap_score(
    demand_growth: float,    # 0.0-1.0 정규화된 수요 증가율
    decay_prob: float,       # 0.0-1.0 트렌드 소멸 확률
    competition_gap: float,  # 0.0-1.0 경쟁 갭 (높을수록 경쟁 약함)
    timing_advantage: float, # 0.0-1.0 발행 타이밍 우위
    category: str = None,
) -> GapScoreResult:
    """
    카테고리별 가중치를 적용한 gap_score 계산.

    모든 입력값은 0.0-1.0 사이로 정규화되어야 합니다.
    출력 score는 0-100 스케일입니다.
    """
    cfg = get_config(category)
    w = cfg.gap_weights

    raw_score = (
        demand_growth    * w.demand_growth    * 100 +
        decay_prob       * w.decay_prob       * 100 +
        competition_gap  * w.competition_gap  * 100 +
        timing_advantage * w.timing_advantage * 100
    )

    score = round(raw_score, 2)
    grade = _grade(score)

    logger.info(
        f"[SCORER_V2] {cfg.slug} | score={score:.1f} ({grade}) | "
        f"demand={demand_growth:.3f} decay={decay_prob:.3f} "
        f"comp={competition_gap:.3f} timing={timing_advantage:.3f}"
    )

    return GapScoreResult(
        score=score,
        grade=grade,
        weights=w,
        breakdown={
            "demand_growth":    round(demand_growth    * w.demand_growth    * 100, 2),
            "decay_prob":       round(decay_prob       * w.decay_prob       * 100, 2),
            "competition_gap":  round(competition_gap  * w.competition_gap  * 100, 2),
            "timing_advantage": round(timing_advantage * w.timing_advantage * 100, 2),
        },
        category=cfg.slug,
    )


def _grade(score: float) -> str:
    if score >= 80:
        return "GENERATE_NOW"
    elif score >= 60:
        return "GENERATE_SOON"
    elif score >= 55:
        return "BORDERLINE"
    else:
        return "USE_FALLBACK"


def should_generate(result: GapScoreResult) -> bool:
    """55점 이상이면 생성, 미만이면 fallback 키워드 사용"""
    return result.score >= 55
