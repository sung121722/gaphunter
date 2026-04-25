"""
keyword_scheduler.py — 트렌드 기반 스마트 키워드 선택

단순 순환 방식 → pytrends 실시간 트렌드 분석으로 교체.
오늘 gap이 가장 크게 열릴 것으로 예측되는 키워드를 선택.

선택 기준 (점수 합산):
  - 트렌드 상승률 (최근 4주 vs 이전 8주)
  - 계절 성수기 보너스 (피크 직전 달)
  - 최근 발행 여부 (14일 내 발행 시 제외)
"""

import json
import sys
import time
import random
import datetime
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)

KEYWORDS_PATH = Path(__file__).parent.parent / "keywords.json"
LOG_PATH      = config.BASE_DIR / "wiki" / "publish_log.json"

# ─── 계절 키워드 매핑 (피크 직전 달 = 최대 보너스) ──────────────────────────────
# key: 키워드에 포함된 문자열, value: 보너스 점수가 최대인 월 리스트
SEASONAL_PRE_PEAK = {
    # 캠핑/아웃도어 — 5~8월 피크 → 3~6월 선점
    "camping":   [3, 4, 5, 6],
    "캠핑":      [3, 4, 5, 6],
    "hiking":    [3, 4, 5, 6],
    "등산":      [3, 4, 5, 6],
    "backpack":  [3, 4, 5, 6],
    "배낭":      [3, 4, 5, 6],
    "trekking":  [3, 4, 5, 6],
    "hammock":   [4, 5, 6],
    "해먹":      [4, 5, 6],
    # 동계 — 12~2월 피크 → 10~12월 선점
    "winter":    [10, 11, 12],
    "동계":      [10, 11, 12],
    "sleeping bag": [10, 11, 12, 3, 4],
    "침낭":      [10, 11, 12, 3, 4],
    "heater":    [10, 11],
    "난방":      [10, 11],
}


def _load_keywords(language: str) -> list[str]:
    data = json.loads(KEYWORDS_PATH.read_text(encoding="utf-8"))
    return data.get(language, [])


def _recently_published(language: str, days: int = 14) -> set[str]:
    """최근 N일 이내 발행(또는 생성)된 키워드 set 반환."""
    if not LOG_PATH.exists():
        return set()
    try:
        logs = json.loads(LOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return set()

    cutoff   = datetime.date.today() - datetime.timedelta(days=days)
    platform = "tistory" if language == "ko" else "blogger"

    recent = set()
    for entry in logs:
        if entry.get("platform") != platform:
            continue
        try:
            pub_date = datetime.date.fromisoformat(entry["date"])
        except Exception:
            continue
        if pub_date >= cutoff:
            kw = entry.get("keyword") or entry.get("title", "")
            if kw:
                recent.add(kw.lower())
    return recent


def _seasonal_bonus(keyword: str) -> float:
    """
    현재 월이 해당 키워드의 '선점 적기'이면 보너스 반환 (0.0 ~ 0.3).
    피크 직전달 = 0.3, 피크 2달 전 = 0.15, 나머지 = 0.0
    """
    month = datetime.date.today().month
    kw_lower = keyword.lower()

    for tag, peak_months in SEASONAL_PRE_PEAK.items():
        if tag in kw_lower:
            if month in peak_months:
                # 첫 번째 피크 달이 몇 달 뒤인지 계산
                idx = peak_months.index(month)
                # 리스트 앞쪽일수록 피크에서 멀어짐 → 보너스 낮음
                bonus = 0.3 * (1.0 - idx / max(len(peak_months), 1))
                return round(bonus, 2)
    return 0.0


def _pytrends_growth_rates(keywords: list[str], geo: str) -> dict[str, float]:
    """
    pytrends로 최근 3개월 트렌드를 가져와
    '최근 4주 평균 / 이전 8주 평균' 비율을 성장률로 반환.
    실패 시 모든 키워드에 0.0 반환.
    """
    from pytrends.request import TrendReq
    growth = {kw: 0.0 for kw in keywords}

    # pytrends는 한 번에 최대 5개 비교
    batches = [keywords[i:i+5] for i in range(0, len(keywords), 5)]

    for batch in batches:
        delay = random.uniform(config.PYTRENDS_DELAY_MIN, config.PYTRENDS_DELAY_MAX)
        time.sleep(delay)
        try:
            pt = TrendReq(hl="en-US" if geo == "US" else "ko-KR",
                          tz=360, timeout=(10, 25), retries=2, backoff_factor=0.5)
            pt.build_payload(batch, timeframe="today 3-m", geo=geo)
            df = pt.interest_over_time()
            if df.empty:
                continue

            for kw in batch:
                if kw not in df.columns:
                    continue
                series = df[kw].values.astype(float)
                if len(series) < 12:
                    continue
                recent  = series[-4:].mean()   # 최근 4주
                earlier = series[-12:-4].mean() # 이전 8주
                if earlier < 1e-6:
                    growth[kw] = 0.0
                else:
                    # +1.0 = 2배 상승,  0.0 = 변화없음,  -1.0 = 절반으로 감소
                    growth[kw] = round((recent - earlier) / (earlier + 1e-6), 3)

        except Exception as e:
            logger.warning("pytrends batch failed (%s) — using 0.0 for %s", e, batch)

    return growth


def pick_keyword(language: str) -> str:
    """
    오늘 발행할 키워드 1개 선택.

    전략:
      1. 최근 14일 내 발행된 키워드 제외
      2. 남은 키워드에 대해 pytrends 3개월 트렌드 조회
      3. 성장률 + 계절 보너스 합산 → 점수 최고 키워드 선택
      4. pytrends 실패 시 첫 번째 미발행 키워드로 폴백
    """
    keywords = _load_keywords(language)
    if not keywords:
        raise ValueError(f"keywords.json에 '{language}' 키워드 없음")

    recent    = _recently_published(language)
    available = [kw for kw in keywords if kw.lower() not in recent]

    if not available:
        # 전부 발행됨 → 처음부터 재순환
        available = keywords
        print(f"  [키워드] 전체 순환 완료 — 처음부터 재시작")

    # ── pytrends 실시간 트렌드 스코어링 ──────────────────────────────
    geo = "KR" if language == "ko" else "US"

    if not config.DRY_RUN_MODE:
        print(f"  [키워드 스코어링] {len(available)}개 후보 트렌드 분석 중...")
        growth_rates = _pytrends_growth_rates(available, geo)

        scored = []
        for kw in available:
            g = growth_rates.get(kw, 0.0)
            s = _seasonal_bonus(kw)
            total = g + s
            scored.append((kw, total, g, s))
            logger.info("  %s | growth=%.2f season=%.2f total=%.2f", kw, g, s, total)

        scored.sort(key=lambda x: x[1], reverse=True)

        # 상위 3개 출력
        print(f"  [키워드 순위 TOP3]")
        for kw, total, g, s in scored[:3]:
            print(f"    {kw!r:40s}  growth={g:+.2f}  season={s:.2f}  total={total:+.2f}")

        chosen, score, g, s = scored[0]
        print(f"  [선택] '{chosen}'  (growth={g:+.2f}, season={s:.2f}, score={score:+.2f})")
    else:
        # DRY RUN — 그냥 첫 번째
        chosen = available[0]
        print(f"  [DRY] 키워드 선택: '{chosen}'")

    return chosen


def log_keyword(keyword: str, language: str, file_path: str,
                products: list[str], status: str = "generated") -> None:
    """
    발행/생성 결과를 publish_log.json에 기록.
    """
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logs = []
    if LOG_PATH.exists():
        try:
            logs = json.loads(LOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            logs = []

    platform = "tistory" if language == "ko" else "blogger"
    logs.append({
        "date":      str(datetime.date.today()),
        "keyword":   keyword,
        "platform":  platform,
        "status":    status,
        "file_path": file_path,
        "products":  products,
        "title":     keyword,
    })
    LOG_PATH.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    for lang in ["en", "ko"]:
        kw = pick_keyword(lang)
        print(f"  [{lang.upper()}] 최종 선택 → {kw}")
