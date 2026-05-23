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


def pick_top_keywords(language: str, n: int = 3) -> list[str]:
    """
    트렌드 기반으로 상위 N개 키워드 후보를 반환 (gap_score 평가 전 1차 필터).

    전략:
      1. 최근 14일 내 발행된 키워드 제외
      2. pytrends 3개월 트렌드 → 성장률 + 계절 보너스 합산
      3. 점수 내림차순으로 상위 N개 반환
      4. pytrends 실패 시 리스트 앞쪽부터 N개 반환
    """
    keywords = _load_keywords(language)
    if not keywords:
        raise ValueError(f"keywords.json에 '{language}' 키워드 없음")

    recent    = _recently_published(language)
    available = [kw for kw in keywords if kw.lower() not in recent]

    if not available:
        available = keywords
        print(f"  [키워드] 전체 순환 완료 — 처음부터 재시작")

    geo = "KR" if language == "ko" else "US"

    if not config.DRY_RUN_MODE and len(available) > 1:
        print(f"  [1차 필터] {len(available)}개 후보 트렌드 스코어링 중...")
        growth_rates = _pytrends_growth_rates(available, geo)

        scored = []
        for kw in available:
            g = growth_rates.get(kw, 0.0)
            s = _seasonal_bonus(kw)
            scored.append((kw, g + s, g, s))

        scored.sort(key=lambda x: x[1], reverse=True)

        print(f"  [트렌드 TOP{min(n, len(scored))}]")
        for kw, total, g, s in scored[:n]:
            print(f"    {kw!r:45s}  growth={g:+.2f}  season={s:.2f}  합계={total:+.2f}")

        return [kw for kw, *_ in scored[:n]]
    else:
        # pytrends 실패 시 → 계절 보너스 기준으로 정렬 (list 순서 대신)
        scored_fallback = sorted(
            available,
            key=lambda kw: _seasonal_bonus(kw),
            reverse=True,
        )
        return scored_fallback[:n]


# 하위 호환 — 단일 키워드 반환 (DRY RUN / 레거시 용도)
def pick_keyword(language: str) -> str:
    return pick_top_keywords(language, n=1)[0]


def log_keyword(
    keyword: str,
    language: str,
    file_path: str,
    products: list[str],
    status: str = "generated",
    post_url: str = "",
    title: str = "",
) -> None:
    """
    발행/생성 결과를 publish_log.json에 기록.

    Args:
        post_url: Blogger 발행 URL (published 상태일 때만 의미 있음)
        title:    실제 H1 제목 (keyword와 다를 수 있음)
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
        "title":     title or keyword,
        "platform":  platform,
        "status":    status,
        "post_url":  post_url,
        "file_path": file_path,
        "products":  products,
    })
    LOG_PATH.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 내부 링크용 유틸 ─────────────────────────────────────────────────────────

_STOP_WORDS = {
    "best", "for", "the", "a", "an", "and", "or", "of", "in", "to",
    "with", "under", "over", "on", "at", "by", "from", "vs", "top",
}


def get_related_posts(
    current_keyword: str,
    language: str = "en",
    n: int = 3,
) -> list[dict]:
    """
    현재 키워드와 관련된 기발행 포스트를 반환합니다.
    키워드 단어 overlap 점수 기반 상위 N개.

    Returns:
        [{"title": str, "url": str, "keyword": str}, ...]
        published 상태 + post_url 있는 항목만 포함.
    """
    if not LOG_PATH.exists():
        return []

    try:
        logs = json.loads(LOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []

    platform = "tistory" if language == "ko" else "blogger"
    kw_tokens = {
        w.lower() for w in current_keyword.split()
        if w.lower() not in _STOP_WORDS
    }

    scored = []
    for entry in logs:
        if entry.get("platform") != platform:
            continue
        if entry.get("status") != "published":
            continue
        url = entry.get("post_url", "").strip()
        if not url:
            continue
        entry_kw = entry.get("keyword", "")
        if entry_kw.lower() == current_keyword.lower():
            continue   # 자기 자신 제외

        entry_tokens = {
            w.lower() for w in entry_kw.split()
            if w.lower() not in _STOP_WORDS
        }
        overlap = len(kw_tokens & entry_tokens)

        # camping 카테고리는 같은 카테고리 내 모든 포스트가 관련성 있음
        # → overlap 0이어도 최소 점수 부여
        score = overlap + 0.1

        scored.append({
            "score":   score,
            "title":   entry.get("title") or entry_kw,
            "url":     url,
            "keyword": entry_kw,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return [{"title": r["title"], "url": r["url"], "keyword": r["keyword"]}
            for r in scored[:n]]


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    for lang in ["en", "ko"]:
        kw = pick_keyword(lang)
        print(f"  [{lang.upper()}] 최종 선택 → {kw}")
