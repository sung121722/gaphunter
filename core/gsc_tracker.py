"""
gsc_tracker.py
───────────────
발행 직후 GSC 색인 요청 + 30일 후 성과 자동 수집.

전제 조건 (GitHub Secrets):
    GSC_SERVICE_ACCOUNT_JSON  서비스 계정 키 JSON 전체 내용
    GSC_SITE_URL              예: "https://stuffnod.blogspot.com/"

Secrets 없으면 모든 API 호출이 조용히 스킵됩니다 (파이프라인 안 깨짐).
GSC 설정 방법:
    1. Google Search Console → 설정 → 사용자 및 권한 → 서비스 계정 추가
    2. Google Cloud → IAM → 서비스 계정 → 키 생성 (JSON)
    3. GitHub Secrets에 GSC_SERVICE_ACCOUNT_JSON, GSC_SITE_URL 추가

사용:
    from core.gsc_tracker import GSCTracker
    gsc = GSCTracker()
    gsc.register_post(url=post_url, title=title, keyword=keyword, category="camping")

    # 30일 후 성과 체크 (별도 cron 또는 파이프라인 시작 시 실행)
    results = gsc.run_performance_check()
"""

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

# 프로젝트 루트 기준 절대 경로 (working directory 무관)
_PROJECT_ROOT     = Path(__file__).parent.parent
REPORT_PATH       = _PROJECT_ROOT / "wiki" / "gsc_performance.json"
TRACKING_LOG_PATH = _PROJECT_ROOT / "wiki" / "gsc_tracking.json"

# Google API 라이브러리 (선택적 — 없으면 기능 비활성)
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False
    logger.warning("[GSC] google-api-python-client 미설치. GSC 기능 비활성.")


# ══════════════════════════════════════════════════════════════
# 설정
# ══════════════════════════════════════════════════════════════

PERFORMANCE_CHECK_DAYS = 30      # 발행 후 성과 체크 시작 (일)
LOW_PERF_CLICKS        = 5       # 30일 후 이 클릭수 미만이면 저성과
LOW_PERF_POSITION      = 30.0    # 30일 후 이 순위 이하면 저성과


# ══════════════════════════════════════════════════════════════
# 데이터 클래스
# ══════════════════════════════════════════════════════════════

@dataclass
class PostPerformance:
    url:             str
    title:           str
    category:        str
    published_at:    str
    keyword:         str
    clicks_30d:      int   = 0
    impressions_30d: int   = 0
    avg_position:    float = 0.0
    avg_ctr:         float = 0.0
    is_low_perf:     bool  = False
    checked_at:      str   = ""


@dataclass
class CategorySummary:
    category:       str
    post_count:     int
    total_clicks:   int
    avg_position:   float
    top_post_url:   str
    low_perf_count: int


# ══════════════════════════════════════════════════════════════
# GSC 클라이언트
# ══════════════════════════════════════════════════════════════

class GSCTracker:
    """
    발행 후 성과 추적 및 저성과 글 플래그.
    run_en.py에서 publish 성공 직후 register_post()를 호출하세요.
    """

    def __init__(
        self,
        site_url: str = None,
        service_account_json: str = None,
    ):
        self.site_url = site_url or os.getenv("GSC_SITE_URL", "")
        sa_json_str   = service_account_json or os.getenv("GSC_SERVICE_ACCOUNT_JSON", "")
        self._service = self._build_service(sa_json_str)
        self._tracking: list = self._load_tracking()

    # ── 공개 인터페이스 ───────────────────────────────────────

    def register_post(
        self,
        url: str,
        title: str,
        keyword: str,
        category: str,
    ) -> None:
        """
        발행 직후 호출. URL을 추적 목록에 등록하고 색인 요청.

        Args:
            url:      발행된 Blogger 글 URL
            title:    글 제목
            keyword:  primary keyword
            category: 카테고리 slug
        """
        if not url:
            logger.warning("[GSC] register_post: URL 없음. 스킵.")
            return

        record = {
            "url":          url,
            "title":        title,
            "keyword":      keyword,
            "category":     category,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "checked":      False,
        }
        self._tracking.append(record)
        self._save_tracking()
        logger.info(f"[GSC] 추적 등록: {url}")

        # 색인 요청 (GSC 서비스 없으면 스킵)
        self._request_indexing(url)

    def run_performance_check(self) -> list:
        """
        발행 30일 이상 지난 글들의 GSC 성과를 수집.
        저성과 글에 플래그를 달고 리포트를 업데이트합니다.

        Returns:
            체크된 PostPerformance 리스트
        """
        if not self._service:
            logger.warning("[GSC] 서비스 미연결. 성과 체크 건너뜀. "
                           "(GSC_SERVICE_ACCOUNT_JSON, GSC_SITE_URL 설정 필요)")
            return []

        now     = datetime.now(timezone.utc)
        results = []

        for record in self._tracking:
            if record.get("checked"):
                continue

            pub_dt   = datetime.fromisoformat(record["published_at"])
            age_days = (now - pub_dt).days

            if age_days < PERFORMANCE_CHECK_DAYS:
                continue

            perf = self._fetch_performance(
                url=record["url"],
                start_date=(pub_dt + timedelta(days=7)).strftime("%Y-%m-%d"),
                end_date=now.strftime("%Y-%m-%d"),
            )

            is_low = (
                perf["clicks"]   < LOW_PERF_CLICKS or
                perf["position"] > LOW_PERF_POSITION
            )

            post_perf = PostPerformance(
                url=record["url"],
                title=record["title"],
                category=record["category"],
                published_at=record["published_at"],
                keyword=record["keyword"],
                clicks_30d=perf["clicks"],
                impressions_30d=perf["impressions"],
                avg_position=perf["position"],
                avg_ctr=perf["ctr"],
                is_low_perf=is_low,
                checked_at=now.isoformat(),
            )
            results.append(post_perf)

            record["checked"]     = True
            record["is_low_perf"] = is_low
            record["clicks_30d"]  = perf["clicks"]
            record["position"]    = perf["position"]

            if is_low:
                logger.warning(
                    f"[GSC] LOW PERF: '{record['title']}' | "
                    f"clicks={perf['clicks']} | position={perf['position']:.1f}"
                )
                self._log_improvement_hints(record, perf)
            else:
                logger.info(
                    f"[GSC] OK: '{record['title']}' | "
                    f"clicks={perf['clicks']} | position={perf['position']:.1f}"
                )

        self._save_tracking()
        self._update_report(results)
        return results

    def get_category_summary(self) -> list:
        """카테고리별 성과 요약 반환"""
        checked = [r for r in self._tracking if r.get("checked")]
        if not checked:
            return []

        categories: dict = {}
        for r in checked:
            cat = r.get("category", "unknown")
            categories.setdefault(cat, []).append(r)

        summaries = []
        for cat, records in categories.items():
            clicks_list = [r.get("clicks_30d", 0) for r in records]
            pos_list    = [r.get("position", 100) for r in records]
            low_count   = sum(1 for r in records if r.get("is_low_perf"))
            top_record  = max(records, key=lambda r: r.get("clicks_30d", 0))

            summaries.append(CategorySummary(
                category=cat,
                post_count=len(records),
                total_clicks=sum(clicks_list),
                avg_position=sum(pos_list) / len(pos_list) if pos_list else 0.0,
                top_post_url=top_record.get("url", ""),
                low_perf_count=low_count,
            ))

        return sorted(summaries, key=lambda s: s.total_clicks, reverse=True)

    # ── GSC API 호출 ─────────────────────────────────────────

    def _request_indexing(self, url: str) -> None:
        """Google Indexing API로 즉시 색인 요청"""
        if not self._service:
            return
        try:
            indexing_service = build(
                "indexing", "v3",
                credentials=self._service._http.credentials
            )
            indexing_service.urlNotifications().publish(
                body={"url": url, "type": "URL_UPDATED"}
            ).execute()
            logger.info(f"[GSC] 색인 요청 완료: {url}")
        except Exception as e:
            logger.warning(f"[GSC] 색인 요청 실패 (무시): {e}")

    def _fetch_performance(self, url: str, start_date: str, end_date: str) -> dict:
        """Search Console API로 URL 성과 데이터 수집"""
        default = {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": 100.0}
        if not self._service:
            return default
        try:
            response = self._service.searchanalytics().query(
                siteUrl=self.site_url,
                body={
                    "startDate":   start_date,
                    "endDate":     end_date,
                    "dimensions":  ["page"],
                    "dimensionFilterGroups": [{
                        "filters": [{
                            "dimension":  "page",
                            "operator":   "equals",
                            "expression": url,
                        }]
                    }],
                    "rowLimit": 1,
                }
            ).execute()

            rows = response.get("rows", [])
            if not rows:
                return default

            row = rows[0]
            return {
                "clicks":      int(row.get("clicks", 0)),
                "impressions": int(row.get("impressions", 0)),
                "ctr":         round(float(row.get("ctr", 0.0)), 4),
                "position":    round(float(row.get("position", 100.0)), 2),
            }
        except Exception as e:
            logger.error(f"[GSC] 성과 데이터 수집 실패: {url} | {e}")
            return default

    # ── 개선 힌트 ────────────────────────────────────────────

    def _log_improvement_hints(self, record: dict, perf: dict) -> None:
        hints    = []
        impr     = perf.get("impressions", 0)
        position = perf.get("position", 100)
        ctr      = perf.get("ctr", 0.0)

        if impr > 100 and ctr < 0.02:
            hints.append("노출은 있지만 클릭률 낮음 -> 제목/메타 설명 개선 필요")
        if impr < 10:
            hints.append("노출 자체가 없음 -> 키워드 난이도 재검토 또는 내부링크 추가")
        if position > 50:
            hints.append("순위 50위 이하 -> 단어수 증가, 구조 개선, 백링크 필요")
        if 20 < position <= 50:
            hints.append("순위 20~50위권 -> 콘텐츠 깊이 보강으로 상위 진입 가능")
        if not hints:
            hints.append("전반적 콘텐츠 품질 재검토 필요")

        logger.warning(
            f"[GSC] 개선 힌트 for '{record['title']}':\n"
            + "\n".join(f"  -> {h}" for h in hints)
        )

    # ── 리포트 ──────────────────────────────────────────────

    def _update_report(self, new_results: list) -> None:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if REPORT_PATH.exists():
            with open(REPORT_PATH, encoding="utf-8") as f:
                existing = json.load(f)

        new_entries = [
            {
                "url":             p.url,
                "title":           p.title,
                "category":        p.category,
                "keyword":         p.keyword,
                "published_at":    p.published_at,
                "clicks_30d":      p.clicks_30d,
                "impressions_30d": p.impressions_30d,
                "avg_position":    p.avg_position,
                "avg_ctr":         p.avg_ctr,
                "is_low_perf":     p.is_low_perf,
                "checked_at":      p.checked_at,
            }
            for p in new_results
        ]

        url_set  = {e["url"] for e in existing}
        combined = existing + [e for e in new_entries if e["url"] not in url_set]

        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(combined, f, ensure_ascii=False, indent=2)

        logger.info(f"[GSC] 리포트 업데이트: {REPORT_PATH} ({len(combined)}건)")

    # ── 서비스 계정 초기화 ───────────────────────────────────

    def _build_service(self, sa_json_str: str):
        if not GOOGLE_API_AVAILABLE:
            return None
        if not sa_json_str:
            logger.info(
                "[GSC] GSC_SERVICE_ACCOUNT_JSON 환경변수 없음. "
                "GSC 기능 비활성 (파이프라인은 정상 동작)."
            )
            return None
        try:
            sa_info     = json.loads(sa_json_str)
            credentials = service_account.Credentials.from_service_account_info(
                sa_info,
                scopes=[
                    "https://www.googleapis.com/auth/webmasters.readonly",
                    "https://www.googleapis.com/auth/indexing",
                ],
            )
            return build("searchconsole", "v1", credentials=credentials)
        except Exception as e:
            logger.error(f"[GSC] 서비스 계정 초기화 실패: {e}")
            return None

    def _load_tracking(self) -> list:
        if not TRACKING_LOG_PATH.exists():
            return []
        with open(TRACKING_LOG_PATH, encoding="utf-8") as f:
            return json.load(f)

    def _save_tracking(self) -> None:
        TRACKING_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TRACKING_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(self._tracking, f, ensure_ascii=False, indent=2)
