"""
publisher.py — Auto-publishing module
티스토리(KO) + 구글 블로거(EN) 자동 발행.
"""

import sys
import json
import logging
import datetime
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)

# ─── Pre-publish checklist ────────────────────────────────────────────────────

def pre_publish_check(content: str, language: str, tags: list[str]) -> dict:
    """
    발행 전 자동 체크리스트.
    하나라도 실패 시 발행 보류.
    """
    checks = {}
    issues = []

    # 1. HTML 변환 완료 확인 (마크다운 헤더 없어야 함)
    has_md = bool(re.search(r'^#{1,3}\s', content, re.MULTILINE))
    checks["html_converted"] = not has_md
    if has_md:
        issues.append("마크다운 헤더(#) 발견 — HTML 변환 필요")

    # 2. 글 길이 확인
    if language == "ko":
        char_count = len(content.replace(" ", ""))
        checks["length_ok"] = char_count >= config.MIN_CHAR_COUNT_KO
        if not checks["length_ok"]:
            issues.append(f"글 길이 부족: {char_count}자 < {config.MIN_CHAR_COUNT_KO}자")
    else:
        word_count = len(content.split())
        checks["length_ok"] = word_count >= config.MIN_WORD_COUNT_EN
        if not checks["length_ok"]:
            issues.append(f"글 길이 부족: {word_count}단어 < {config.MIN_WORD_COUNT_EN}단어")

    # 3. 플레이스홀더 없음 확인
    placeholders = re.findall(r'\[AMAZON_LINK:[^\]]+\]|\[COUPANG_LINK:[^\]]+\]|여기에_파트너스_링크_삽입', content)
    checks["no_placeholders"] = len(placeholders) == 0
    if placeholders:
        issues.append(f"미교체 플레이스홀더 발견: {placeholders[:3]}")

    # 4. 쿠팡 필수 문구 확인 (KO)
    if language == "ko":
        has_disclosure = "쿠팡 파트너스 활동의 일환" in content
        checks["has_disclosure"] = has_disclosure
        if not has_disclosure:
            issues.append("쿠팡 파트너스 필수 문구 없음")
    else:
        checks["has_disclosure"] = True

    # 5. 태그 최소 5개 확인 (Blogger 전송은 8개 이하로 별도 제한)
    checks["tags_ready"] = len(tags) >= 5
    if not checks["tags_ready"]:
        issues.append(f"태그 부족: {len(tags)}개 < 5개")

    passed = all(checks.values())
    return {
        "passed":  passed,
        "checks":  checks,
        "issues":  issues,
    }


# ─── Tag generator ────────────────────────────────────────────────────────────

def generate_tags(keyword: str, language: str, category: str = "") -> list[str]:
    """키워드 기반 태그 20개 자동 생성."""
    base = keyword.lower().split()

    if language == "ko":
        suffixes = ["추천", "후기", "비교", "순위", "가성비", "2026",
                    "구매가이드", "베스트", "TOP5", "리뷰",
                    "쿠팡", "로켓배송", "할인", "최저가", "직구대안",
                    "선물", "인기", "신상", "브랜드", "사용법"]
        tags = [keyword]
        for s in suffixes:
            tags.append(f"{keyword} {s}")
            if len(tags) >= 20:
                break
        tags = tags[:20]
    else:
        suffixes = ["review", "best", "guide", "2026", "top", "buy",
                    "comparison", "rated", "cheap", "recommendations",
                    "tested", "worth it", "pros cons", "under $50",
                    "for beginners", "lightweight", "durable", "amazon", "deals", "picks"]
        tags = [keyword]
        for s in suffixes:
            tags.append(f"{keyword} {s}")
            if len(tags) >= 20:
                break
        tags = tags[:20]

    return tags


# ─── Tistory publisher ────────────────────────────────────────────────────────

def publish_tistory(
    title: str,
    content: str,
    tags: list[str],
    category: str = "캠핑",
    dry_run: bool = True,
) -> dict:
    """
    티스토리 API로 글 발행.
    DRY_RUN: 실제 발행 없이 결과만 시뮬레이션.

    환경변수 필요:
        TISTORY_ACCESS_TOKEN
        TISTORY_BLOG_NAME (예: sung1216)
    """
    access_token = config.__dict__.get("TISTORY_ACCESS_TOKEN") or \
                   __import__("os").getenv("TISTORY_ACCESS_TOKEN", "")
    blog_name    = config.__dict__.get("TISTORY_BLOG_NAME") or \
                   __import__("os").getenv("TISTORY_BLOG_NAME", "sung1216")

    if dry_run or config.DRY_RUN_MODE:
        logger.info("[DRY] Tistory publish simulated: '%s'", title)
        return {
            "platform":   "tistory",
            "status":     "dry_run",
            "title":      title,
            "blog":       f"{blog_name}.tistory.com",
            "tags":       tags,
            "category":   category,
            "published_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "post_url":   f"https://{blog_name}.tistory.com/entry/[DRY-RUN]",
        }

    if not access_token:
        return {"platform": "tistory", "status": "error", "reason": "TISTORY_ACCESS_TOKEN 미설정"}

    try:
        import httpx
        tag_str = ",".join(tags[:10])  # 티스토리 태그 최대 10개 적용
        resp = httpx.post(
            "https://www.tistory.com/apis/post/write",
            params={
                "access_token": access_token,
                "output":       "json",
                "blogName":     blog_name,
                "title":        title,
                "content":      content,
                "visibility":   "3",   # 3 = 발행
                "category":     "0",   # 0 = 기본 카테고리
                "tag":          tag_str,
            },
            timeout=30,
        )
        data = resp.json()
        if data.get("tistory", {}).get("status") == "200":
            post_url = data["tistory"]["item"]["url"]
            return {
                "platform":     "tistory",
                "status":       "published",
                "title":        title,
                "post_url":     post_url,
                "tags":         tags,
                "published_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        else:
            return {"platform": "tistory", "status": "error", "reason": str(data)}
    except Exception as e:
        logger.error("Tistory publish failed: %s", e)
        return {"platform": "tistory", "status": "error", "reason": str(e)}


# ─── Blogger publisher ────────────────────────────────────────────────────────

def _get_blogger_access_token() -> str:
    """
    저장된 refresh token으로 Blogger API access token 발급.
    환경변수 필요:
        GOOGLE_REFRESH_TOKEN
        GOOGLE_CLIENT_ID
        GOOGLE_CLIENT_SECRET
    """
    import os
    import httpx

    refresh_token  = os.getenv("GOOGLE_REFRESH_TOKEN", "")
    client_id      = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret  = os.getenv("GOOGLE_CLIENT_SECRET", "")

    if not all([refresh_token, client_id, client_secret]):
        raise ValueError("GOOGLE_REFRESH_TOKEN / GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET 미설정")

    resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
            "client_id":     client_id,
            "client_secret": client_secret,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def publish_blogger(
    title: str,
    content: str,
    tags: list[str],
    dry_run: bool = True,
) -> dict:
    """
    구글 블로거 API로 글 발행 (OAuth2 refresh token 방식).

    환경변수 필요:
        BLOGGER_BLOG_ID
        GOOGLE_REFRESH_TOKEN
        GOOGLE_CLIENT_ID
        GOOGLE_CLIENT_SECRET

    최초 1회 setup_oauth.py 실행 필요 → refresh token 발급.
    """
    import os
    import httpx

    blog_id = os.getenv("BLOGGER_BLOG_ID", "")

    if dry_run or config.DRY_RUN_MODE:
        logger.info("[DRY] Blogger publish simulated: '%s'", title)
        return {
            "platform":     "blogger",
            "status":       "dry_run",
            "title":        title,
            "blog":         "stuffnod.blogspot.com",
            "tags":         tags,
            "published_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "post_url":     "https://stuffnod.blogspot.com/[DRY-RUN]",
        }

    if not blog_id:
        return {"platform": "blogger", "status": "error", "reason": "BLOGGER_BLOG_ID 미설정"}

    try:
        access_token = _get_blogger_access_token()
        # Blogger API: <script> 태그 거부 → JSON-LD 제거
        clean_content = re.sub(
            r'<script[^>]*>.*?</script>',
            '',
            content,
            flags=re.DOTALL | re.IGNORECASE,
        )
        # Blogger API: HTML 주석 거부
        clean_content = re.sub(r'<!--.*?-->', '', clean_content, flags=re.DOTALL)
        # Blogger API: labels 최대 8개 (초과 시 400 오류)
        resp = httpx.post(
            f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts/",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "title":   title,
                "content": clean_content,
                "labels":  tags[:8],
            },
            timeout=30,
        )
        data = resp.json()
        if "url" in data:
            return {
                "platform":     "blogger",
                "status":       "published",
                "title":        title,
                "post_url":     data["url"],
                "tags":         tags,
                "published_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        else:
            reason = str(data)
            logger.error("Blogger API error: %s", reason)
            print(f"  [Blogger 오류] {reason[:200]}")
            return {"platform": "blogger", "status": "error", "reason": reason}
    except Exception as e:
        logger.error("Blogger publish failed: %s", e)
        return {"platform": "blogger", "status": "error", "reason": str(e)}


# ─── Daily limit guard ────────────────────────────────────────────────────────

def _count_today_posts(platform: str) -> int:
    """오늘 발행한 글 수 확인 (wiki/log.md 기반)."""
    log_path = Path(__file__).parent.parent / "wiki" / "publish_log.json"
    if not log_path.exists():
        return 0
    try:
        logs = json.loads(log_path.read_text(encoding="utf-8"))
        today = str(datetime.date.today())
        return sum(
            1 for entry in logs
            if entry.get("date") == today and entry.get("platform") == platform
        )
    except Exception:
        return 0


def _log_publish(result: dict) -> None:
    """발행 결과를 wiki/publish_log.json에 기록."""
    log_path = Path(__file__).parent.parent / "wiki" / "publish_log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logs = []
    if log_path.exists():
        try:
            logs = json.loads(log_path.read_text(encoding="utf-8"))
        except Exception:
            logs = []

    logs.append({
        "date":         str(datetime.date.today()),
        "platform":     result.get("platform"),
        "status":       result.get("status"),
        "title":        result.get("title"),
        "post_url":     result.get("post_url", ""),
        "published_at": result.get("published_at"),
    })

    log_path.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── Public API ───────────────────────────────────────────────────────────────

DAILY_LIMITS = {"tistory": 3, "blogger": 3}


def publish(
    title: str,
    content: str,
    language: str = "en",
    category: str = "",
    dry_run: bool = True,
) -> dict:
    """
    글 발행 메인 함수.
    1. 태그 자동 생성
    2. 발행 전 체크리스트
    3. 일일 발행 한도 확인
    4. 플랫폼별 발행
    5. 로그 기록
    """
    platform = "tistory" if language == "ko" else "blogger"

    # 태그 생성
    tags = generate_tags(title, language, category)

    # 발행 전 체크
    check = pre_publish_check(content, language, tags)
    if not check["passed"]:
        print(f"\n  [!] 발행 보류 — 체크 실패:")
        for issue in check["issues"]:
            print(f"      - {issue}")
        return {
            "platform": platform,
            "status":   "blocked",
            "issues":   check["issues"],
        }

    # 일일 한도 확인
    limit = DAILY_LIMITS[platform]
    today_count = _count_today_posts(platform)
    if today_count >= limit and not dry_run:
        print(f"  [!] {platform} 일일 한도 초과 ({today_count}/{limit})")
        return {"platform": platform, "status": "limit_exceeded"}

    # 발행
    print(f"\n  체크리스트 통과 ({len(tags)}개 태그)")
    if platform == "tistory":
        result = publish_tistory(title, content, tags, category, dry_run=dry_run)
    else:
        result = publish_blogger(title, content, tags, dry_run=dry_run)

    # 로그 기록
    _log_publish(result)

    return result


# ─── CLI test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("\n=== Publisher DRY RUN 테스트 ===")

    dummy_content_ko = """<h1>캠핑용품 추천 2026</h1>
<p>테스트 콘텐츠입니다.</p>
<p>이 포스팅은 쿠팡 파트너스 활동의 일환으로,
이에 따른 일정액의 수수료를 제공받습니다.</p>"""

    dummy_content_en = """<h1>Best Camping Gear 2026</h1>
<p>Test content with enough words """ + "word " * 2000 + """</p>"""

    for lang, content, title in [
        ("ko", dummy_content_ko, "캠핑용품 추천 2026"),
        ("en", dummy_content_en, "Best Camping Gear 2026"),
    ]:
        result = publish(title, content, language=lang, dry_run=True)
        print(f"\n  [{lang.upper()}] {result['status']} — {result.get('post_url', result.get('issues', ''))}")
