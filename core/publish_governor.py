"""
publish_governor.py
────────────────────
발행 전 품질 + 빈도 게이트.
run_en.py의 publish() 호출 전에 governor.approve() 통과 여부를 확인하세요.

    from core.publish_governor import PublishGovernor
    governor = PublishGovernor(log_path="wiki/publish_governor_log.json")
    result = governor.approve(html_content, title)
    if result.approved:
        publish(...)
        governor.record_publish(title, html_content, result.quality_score)
    else:
        logger.error(result.rejection_reasons)
"""

import json
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# 설정값 — GapHunter 스케줄 기준
# ══════════════════════════════════════════════════════════════

MIN_INTERVAL_HOURS   = 10    # 발행 간격 최소 시간 (12h 스케줄 기준 2h 여유)
RAMP_DAYS            = 90    # 초기 램프업 기간 (일)
RAMP_MAX_PER_WEEK    = 14    # 램프업 중 주당 최대 (2x/day = 14)
STEADY_MAX_PER_WEEK  = 14    # 안정기 주당 최대 (2x/day = 14)
MIN_WORD_COUNT       = 800   # 최소 단어수
MIN_H2_COUNT         = 2     # 최소 H2 헤딩 수
MIN_PRODUCT_COUNT    = 3     # 최소 H3 제품 섹션 수
MAX_FOMO_COUNT       = 1     # FOMO 최대 허용 수 (초과 시 HARD REJECT)

# FOMO 감지 패턴
FOMO_PATTERNS = [
    r'🔥',
    r'sells out fast',
    r'limited stock',
    r'order now',
    r"don't wait",
    r'going fast',
    r'almost gone',
    r'low stock',
    r'act now',
    r'while supplies last',
]

# 2차 금지어 확인 (프롬프트 금지어와 별개)
RESIDUAL_BANNED = [
    "comprehensive", "delve", "seamlessly", "leverage", "utilize",
    "game-changer", "in conclusion", "it's worth noting",
    "let's cut right to it", "here's the thing",
    "(ai tested)", "[ai tested]",
]


# ══════════════════════════════════════════════════════════════
# 데이터 클래스
# ══════════════════════════════════════════════════════════════

@dataclass
class ApprovalResult:
    approved: bool
    rejection_reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    quality_score: float = 0.0   # 0~100
    word_count: int = 0


@dataclass
class PublishRecord:
    title: str
    published_at: str     # ISO 8601
    word_count: int
    quality_score: float


# ══════════════════════════════════════════════════════════════
# PublishGovernor
# ══════════════════════════════════════════════════════════════

class PublishGovernor:
    """발행 전 승인 게이트."""

    def __init__(self, log_path: str = "wiki/publish_governor_log.json"):
        self.log_path = Path(log_path)
        self._records: list = self._load_log()

    # ── 공개 인터페이스 ───────────────────────────────────────

    def approve(self, html_content: str, title: str) -> ApprovalResult:
        """
        발행 승인 여부를 판단합니다.

        Returns:
            ApprovalResult.approved == True여야 발행 가능
        """
        reasons  = []
        warnings = []

        # ── Gate 1: 발행 간격 ──────────────────────────────
        interval_ok, interval_msg = self._check_interval()
        if not interval_ok:
            reasons.append(interval_msg)

        # ── Gate 2: 주간 발행 한도 ─────────────────────────
        weekly_ok, weekly_msg = self._check_weekly_limit()
        if not weekly_ok:
            reasons.append(weekly_msg)

        # ── Gate 3: 단어수 ──────────────────────────────────
        word_count = self._count_words(html_content)
        if word_count < MIN_WORD_COUNT:
            reasons.append(
                f"단어수 부족: {word_count}단어 (최소 {MIN_WORD_COUNT}). "
                f"약 {MIN_WORD_COUNT - word_count}단어 추가 필요."
            )

        # ── Gate 4: 구조 체크 ───────────────────────────────
        h2_count = len(re.findall(r'<h2[^>]*>', html_content, re.IGNORECASE))
        if h2_count < MIN_H2_COUNT:
            reasons.append(
                f"H2 헤딩 부족: {h2_count}개 (최소 {MIN_H2_COUNT}). "
                f"섹션 구분 필요."
            )

        h3_count = len(re.findall(r'<h3[^>]*>', html_content, re.IGNORECASE))
        if h3_count < MIN_PRODUCT_COUNT:
            reasons.append(
                f"H3 제품 섹션 부족: {h3_count}개 (최소 {MIN_PRODUCT_COUNT}). "
                f"제품 리뷰 수 확인 필요."
            )

        # ── Gate 5: 미교체 링크 플레이스홀더 ───────────────
        unresolved = re.findall(r'\[(?:AMAZON_LINK|UNRESOLVED_LINK):[^\]]+\]', html_content)
        if unresolved:
            reasons.append(
                f"미교체 어필리에이트 링크 {len(unresolved)}개: "
                f"{unresolved[:3]}{'...' if len(unresolved) > 3 else ''}"
            )

        # ── Gate 6: 이미지 플레이스홀더 ────────────────────
        img_placeholders = re.findall(r'\[(?:IMAGE|PLACEHOLDER|INSERT)[^\]]*\]',
                                       html_content, re.IGNORECASE)
        if img_placeholders:
            reasons.append(f"이미지 플레이스홀더 미처리: {img_placeholders}")

        # ── Gate 7: 마크다운 잔존 체크 ─────────────────────
        markdown_headers = re.findall(r'^#{1,3} ', html_content, re.MULTILINE)
        if markdown_headers:
            reasons.append(
                f"마크다운 헤더 잔존 {len(markdown_headers)}개. "
                f"HTML 변환 필요: # -> <h2>, ## -> <h3>"
            )

        # ── Gate 8: em dash / en dash in headings (HARD REJECT) ─
        heading_texts = re.findall(
            r'<h[123][^>]*>(.*?)</h[123]>', html_content,
            re.IGNORECASE | re.DOTALL
        )
        dash_headings = [
            re.sub(r'<[^>]+>', '', h).strip()
            for h in heading_texts
            if re.search(r'[—–]', h)
        ]
        if dash_headings:
            reasons.append(
                f"헤딩에 em dash/en dash 잔존 {len(dash_headings)}개 "
                f"(post_process 미작동): {dash_headings[:2]}"
            )

        # ── Gate 9: FOMO 1개 초과 (HARD REJECT) ────────────
        fomo_hits = 0
        lower_content = html_content.lower()
        for pat in FOMO_PATTERNS:
            fomo_hits += len(re.findall(pat, lower_content, re.IGNORECASE))
        if fomo_hits > MAX_FOMO_COUNT:
            reasons.append(
                f"FOMO 과다: {fomo_hits}개 감지 (최대 {MAX_FOMO_COUNT}개). "
                f"2번째 이후 제품의 urgency 문구 제거 필요."
            )

        # ── Gate 10: 필수 라벨 확인 (Warning) ──────────────
        has_best_overall = bool(re.search(
            r'<h3[^>]*>[^<]*best overall[^<]*</h3>',
            html_content, re.IGNORECASE
        ))
        has_best_for = bool(re.search(
            r'<strong[^>]*>best for:</strong>',
            html_content, re.IGNORECASE
        ))

        # ── Warning: 금지어 잔존 ────────────────────────────
        lower = html_content.lower()
        found_banned = [w for w in RESIDUAL_BANNED if w in lower]
        if found_banned:
            warnings.append(
                f"금지어 잔존 (발행은 가능하나 수정 권장): {found_banned}"
            )

        # ── Warning: 필수 라벨 누락 ─────────────────────────
        if not has_best_overall:
            warnings.append("'Best Overall:' H3 라벨 누락 — 시스템 프롬프트 확인")
        if not has_best_for:
            warnings.append("'Best for:' 문구 누락 — 제품별 추천 대상 문장 없음")

        # ── Warning: 제목에 "Best Best" ─────────────────────
        if re.search(r'\bbest best\b', title, re.IGNORECASE):
            warnings.append(f"타이틀에 'Best Best' 중복: '{title}'")

        # ── 품질 점수 ───────────────────────────────────────
        quality_score = self._calc_quality(
            word_count=word_count,
            h2_count=h2_count,
            h3_count=h3_count,
            has_faq="faq" in html_content.lower(),
            has_schema='"@type": "FAQPage"' in html_content,
            has_table='<table' in html_content.lower(),
            banned_count=len(found_banned),
            has_best_overall=has_best_overall,
            has_best_for=has_best_for,
        )

        approved = len(reasons) == 0

        if approved:
            logger.info(
                f"[GOVERNOR] APPROVED: '{title}' | "
                f"quality={quality_score:.0f} | {word_count}단어"
            )
        else:
            logger.error(f"[GOVERNOR] BLOCKED: '{title}' | 사유 {len(reasons)}개")
            for r in reasons:
                logger.error(f"  -> {r}")

        for w in warnings:
            logger.warning(f"[GOVERNOR] WARNING: {w}")

        return ApprovalResult(
            approved=approved,
            rejection_reasons=reasons,
            warnings=warnings,
            quality_score=quality_score,
            word_count=word_count,
        )

    def record_publish(self, title: str, html_content: str, quality_score: float) -> None:
        """발행 성공 후 호출. 로그에 기록합니다."""
        record = PublishRecord(
            title=title,
            published_at=datetime.now(timezone.utc).isoformat(),
            word_count=self._count_words(html_content),
            quality_score=quality_score,
        )
        self._records.append(record)
        self._save_log()
        logger.info(f"[GOVERNOR] 발행 기록 저장: '{title}'")

    # ── 내부 게이트 로직 ─────────────────────────────────────

    def _check_interval(self):
        if not self._records:
            return True, ""
        last = self._records[-1]
        last_dt = datetime.fromisoformat(last.published_at)
        elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
        if elapsed < MIN_INTERVAL_HOURS:
            wait = MIN_INTERVAL_HOURS - elapsed
            return False, (
                f"발행 간격 부족: 마지막 발행 {elapsed:.1f}시간 전. "
                f"{wait:.1f}시간 후 재시도. (최소 {MIN_INTERVAL_HOURS}시간)"
            )
        return True, ""

    def _check_weekly_limit(self):
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)

        recent_week = [
            r for r in self._records
            if datetime.fromisoformat(r.published_at) > week_ago
        ]

        # 블로그 나이 계산
        if self._records:
            first_dt = datetime.fromisoformat(self._records[0].published_at)
            blog_age_days = (now - first_dt).days
        else:
            blog_age_days = 0

        if blog_age_days < RAMP_DAYS:
            limit = RAMP_MAX_PER_WEEK
            phase = f"램프업({blog_age_days}일차)"
        else:
            limit = STEADY_MAX_PER_WEEK
            phase = "안정기"

        if len(recent_week) >= limit:
            return False, (
                f"주간 발행 한도 초과: 최근 7일 {len(recent_week)}개 / "
                f"한도 {limit}개 ({phase}). "
                f"내일 이후 재시도."
            )
        return True, ""

    # ── 품질 점수 계산 ───────────────────────────────────────

    def _calc_quality(
        self,
        word_count: int,
        h2_count: int,
        h3_count: int,
        has_faq: bool,
        has_schema: bool,
        has_table: bool,
        banned_count: int,
        has_best_overall: bool = False,
        has_best_for: bool = False,
    ) -> float:
        score = 0.0

        # 단어수 (최대 25점)
        score += min(25.0, (word_count / MIN_WORD_COUNT) * 25.0)

        # 구조 (최대 25점)
        score += min(12.0, h2_count * 4.0)
        score += min(13.0, h3_count * 4.0)

        # 부가 요소 (최대 30점)
        if has_faq:    score += 10.0
        if has_schema: score += 10.0
        if has_table:  score += 10.0

        # 라벨 품질 보너스 (최대 10점)
        if has_best_overall: score += 5.0
        if has_best_for:     score += 5.0

        # 금지어 패널티 (최대 -10점)
        score -= min(10.0, banned_count * 2.0)

        return round(max(0.0, min(100.0, score)), 1)

    # ── 로그 I/O ────────────────────────────────────────────

    def _load_log(self) -> list:
        if not self.log_path.exists():
            return []
        try:
            with open(self.log_path, encoding="utf-8") as f:
                data = json.load(f)
            records = []
            for item in data:
                if "published_at" in item:
                    records.append(PublishRecord(
                        title=item.get("title", ""),
                        published_at=item["published_at"],
                        word_count=item.get("word_count", 0),
                        quality_score=item.get("quality_score", 0.0),
                    ))
            return records
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[GOVERNOR] 로그 파싱 실패: {e}. 빈 로그로 시작.")
            return []

    def _save_log(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {
                "title":         r.title,
                "published_at":  r.published_at,
                "word_count":    r.word_count,
                "quality_score": r.quality_score,
            }
            for r in self._records
        ]
        with open(self.log_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _count_words(html: str) -> int:
        """HTML 태그 제거 후 단어 수 계산"""
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text).strip()
        return len(text.split())
