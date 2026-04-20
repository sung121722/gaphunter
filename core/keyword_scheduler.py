"""
keyword_scheduler.py — 매일 발행할 키워드 자동 선택
publish_log.json 기반으로 최근에 쓰지 않은 키워드를 순환 선택.
"""

import json
import sys
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

KEYWORDS_PATH = Path(__file__).parent.parent / "keywords.json"
LOG_PATH      = config.BASE_DIR / "wiki" / "publish_log.json"


def _load_keywords(language: str) -> list[str]:
    data = json.loads(KEYWORDS_PATH.read_text(encoding="utf-8"))
    return data.get(language, [])


def _recently_published(language: str, days: int = 14) -> set[str]:
    """최근 N일 이내 발행된 키워드 set 반환."""
    if not LOG_PATH.exists():
        return set()
    try:
        logs = json.loads(LOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return set()

    cutoff = datetime.date.today() - datetime.timedelta(days=days)
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
            # title에서 키워드 역추적 (keyword 필드 없으면 title 사용)
            kw = entry.get("keyword") or entry.get("title", "")
            if kw:
                recent.add(kw.lower())
    return recent


def pick_keyword(language: str) -> str:
    """
    오늘 발행할 키워드 1개 선택.
    - 최근 14일 내 발행된 키워드 제외
    - 남은 키워드 중 리스트 순서대로 첫 번째
    - 전부 발행됐으면 가장 오래된 것부터 재사용
    """
    keywords = _load_keywords(language)
    if not keywords:
        raise ValueError(f"keywords.json에 '{language}' 키워드 없음")

    recent = _recently_published(language)
    available = [kw for kw in keywords if kw.lower() not in recent]

    if available:
        chosen = available[0]
        print(f"  [키워드 선택] '{chosen}' (미발행 {len(available)}개 중 첫 번째)")
    else:
        # 전부 발행됨 → 처음부터 다시
        chosen = keywords[0]
        print(f"  [키워드 선택] '{chosen}' (전체 순환 완료 — 처음부터 재시작)")

    return chosen


def log_keyword(keyword: str, language: str, file_path: str,
                products: list[str], status: str = "generated") -> None:
    """
    KO 포스트 생성 결과를 publish_log.json에 기록.
    (실제 발행은 수동이므로 status='generated'로 기록)
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
    for lang in ["en", "ko"]:
        kw = pick_keyword(lang)
        print(f"  [{lang}] → {kw}")
