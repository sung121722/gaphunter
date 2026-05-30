"""
publish_governor.py
────────────────────
AdSense 승인 기준에 맞는 발행 전 품질 + 빈도 게이트.
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
# 설정값 — AdSense 승인 기준
# ══════════════════════════════════════════════════════════════

MIN_INTERVAL_HOURS   = 10     # 발행 간격 최소 시간
RAMP_DAYS            = 90     # 초기 램프업 기간 (일)
RAMP_MAX_PER_WEEK    = 14     # 램프업 중 주당 최대
STEADY_MAX_PER_WEEK  = 14     # 안정기 주당 최대

# AdSense 품질 기준 (구글 기준: 1000+ 단어, 실질적 내용)
MIN_WORD_COUNT       = 1500   # 최소 단어수 (AdSense 권장 1000+ → 안전마진 1500)
MIN_H2_COUNT         = 4      # 최소 H2 섹션 수 (구조 다양성 증명)
MIN_PRODUCT_COUNT    = 3      # 최소 H3 제품 섹션 수
MIN_FAQ_ANSWER_WORDS = 40     # FAQ 답변 최소 단어수
MAX_FOMO_COUNT       = 1      # FOMO 최대 허용 수 (초과 시 HARD REJECT)

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
    r'hurry',
    r'only \d+ left',
]

# 금지어 (AdSense는 AI 생성 느낌 나는 표현을 저품질로 판단)
RESIDUAL_BANNED = [
    "comprehensive", "delve", "seamlessly", "leverage", "utilize",
    "game-changer", "in conclusion", "it's worth noting",
    "let's cut right to it", "here's the thing",
    "(ai tested)", "[ai tested]",
    "cutting-edge", "state-of-the-art", "revolutionary",
    "transformative", "groundbreaking", "meticulous",
    "unparalleled", "exceptional", "remarkable",
]

# AdSense 필수 요소
REQUIRED_ELEMENTS = {
    "affiliate_disclosure": r'class=["\']disclosure["\']',
    "last_updated":         r'last updated',
    "faq_schema":           r'"@type"\s*:\s*"FAQPage"',
    "comparison_table":     r'<table',
    "amazon_cta":           r'amazon\.com',
    "best_overall_h3":      r'<h3[^>]*>\s*best overall\s*:',
    "best_for":             r'<strong[^>]*>best for\s*:</strong>',
}


# ══════════════════════════════════════════════════════════════
# 데이터 클래스
# ══════════════════════════════════════════════════════════════

@dataclass
class ApprovalResult:
    approved: bool
    rejection_reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    quality_score: float = 0.0
    word_count: int = 0
    adsense_ready: bool = False   # AdSense 제출 준비 완료 여부


@dataclass
class PublishRecord:
    title: str
    published_at: str
    word_count: int
    quality_score: float


# ══════════════════════════════════════════════════════════════
# PublishGovernor
# ══════════════════════════════════════════════════════════════

class PublishGovernor:
    """AdSense 품질 기준 발행 승인 게이트."""

    def __init__(self, log_path: str = "wiki/publish_governor_log.json"):
        self.log_path = Path(log_path)
        self._records: list = self._load_log()

    # ── 공개 인터페이스 ───────────────────────────────────────

    def approve(self, html_content: str, title: str) -> ApprovalResult:
        reasons  = []
        warnings = []
        lower    = html_content.lower()

        # ── Gate 1: 발행 간격 ──────────────────────────────
        interval_ok, interval_msg = self._check_interval()
        if not interval_ok:
            reasons.append(interval_msg)

        # ── Gate 2: 주간 발행 한도 ─────────────────────────
        weekly_ok, weekly_msg = self._check_weekly_limit()
        if not weekly_ok:
            reasons.append(weekly_msg)

        # ── Gate 3: 단어수 (AdSense 핵심 기준) ─────────────
        word_count = self._count_words(html_content)
        if word_count < MIN_WORD_COUNT:
            shortage = MIN_WORD_COUNT - word_count
            reasons.append(
                f"[ADSENSE] 단어수 부족: {word_count}단어 (최소 {MIN_WORD_COUNT}). "
                f"{shortage}단어 추가 필요. AdSense는 얇은 콘텐츠를 거부합니다."
            )

        # ── Gate 4: H2 구조 ─────────────────────────────────
        h2_count = len(re.findall(r'<h2[^>]*>', html_content, re.IGNORECASE))
        if h2_count < MIN_H2_COUNT:
            reasons.append(
                f"[구조] H2 헤딩 부족: {h2_count}개 (최소 {MIN_H2_COUNT}). "
                f"섹션 구분 추가 필요."
            )

        # ── Gate 5: H3 제품 섹션 ────────────────────────────
        h3_count = len(re.findall(r'<h3[^>]*>', html_content, re.IGNORECASE))
        if h3_count < MIN_PRODUCT_COUNT:
            reasons.append(
                f"[구조] H3 제품 섹션 부족: {h3_count}개 (최소 {MIN_PRODUCT_COUNT})."
            )

        # ── Gate 6: 미교체 링크 플레이스홀더 ───────────────
        unresolved = re.findall(r'\[(?:AMAZON_LINK|UNRESOLVED_LINK):[^\]]+\]', html_content)
        if unresolved:
            reasons.append(
                f"[링크] 미교체 어필리에이트 링크 {len(unresolved)}개: "
                f"{unresolved[:3]}{'...' if len(unresolved) > 3 else ''}"
            )

        # ── Gate 7: 이미지/콘텐츠 플레이스홀더 ────────────
        img_placeholders = re.findall(
            r'\[(?:IMAGE|PLACEHOLDER|INSERT|TODO)[^\]]*\]',
            html_content, re.IGNORECASE
        )
        if img_placeholders:
            reasons.append(f"[품질] 플레이스홀더 미처리: {img_placeholders}")

        # ── Gate 8: 마크다운 잔존 ──────────────────────────
        markdown_headers = re.findall(r'^#{1,3} ', html_content, re.MULTILINE)
        if markdown_headers:
            reasons.append(
                f"[형식] 마크다운 헤더 잔존 {len(markdown_headers)}개. "
                f"# → <h2>, ## → <h3> 변환 필요."
            )

        # ── Gate 9: em dash / en dash (헤딩 + 본문 전체) ────
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
                f"[형식] 헤딩에 em/en dash 잔존 {len(dash_headings)}개: "
                f"{dash_headings[:2]}"
            )

        # 본문 전체 em/en dash 카운트 (5개 초과 시 HARD REJECT)
        body_text = re.sub(r'<script[^>]*>.*?</script>', '', html_content,
                           flags=re.IGNORECASE | re.DOTALL)
        body_dash_count = len(re.findall(r'[—–]', body_text))
        if body_dash_count > 5:
            reasons.append(
                f"[형식] 본문 em/en dash {body_dash_count}개. "
                f"모두 콜론(:) 또는 마침표로 교체 필요. "
                f"프롬프트 금지어 적용 확인."
            )

        # ── Gate 10: FOMO 초과 (HARD REJECT) ────────────────
        fomo_hits = 0
        for pat in FOMO_PATTERNS:
            fomo_hits += len(re.findall(pat, lower, re.IGNORECASE))
        if fomo_hits > MAX_FOMO_COUNT:
            reasons.append(
                f"[FOMO] 과다: {fomo_hits}개 감지 (최대 {MAX_FOMO_COUNT}개). "
                f"2번째 이후 제품의 urgency 문구 제거 필요."
            )

        # ── Gate 11: 어필리에이트 공시 확인 (AdSense 필수) ─
        has_disclosure = bool(re.search(
            REQUIRED_ELEMENTS["affiliate_disclosure"], html_content, re.IGNORECASE
        ))
        if not has_disclosure:
            reasons.append(
                "[ADSENSE] 어필리에이트 공시(disclosure) 누락. "
                "H1 앞에 <p class=\"disclosure\"> 반드시 필요. "
                "FTC 규정 + AdSense 정책 위반."
            )

        # ── Gate 12: FAQ 스키마 확인 (AdSense 리치스니펫) ──
        has_faq_schema = bool(re.search(
            REQUIRED_ELEMENTS["faq_schema"], html_content, re.IGNORECASE
        ))
        if not has_faq_schema:
            reasons.append(
                "[구조] FAQPage JSON-LD 스키마 누락. "
                "구조화 데이터 없으면 리치스니펫 불가."
            )

        # ── Gate 13: Last updated 날짜 ──────────────────────
        has_last_updated = bool(re.search(
            REQUIRED_ELEMENTS["last_updated"], html_content, re.IGNORECASE
        ))
        if not has_last_updated:
            warnings.append(
                "[권장] 'Last updated' 날짜 누락. "
                "구글은 최신성을 신뢰 신호로 봅니다."
            )

        # ── Gate 14: dummy 상품 감지 ────────────────────────
        dummy_signals = [
            "product a", "product b", "product c",
            '"product a"', '"product b"', '"product c"',
            ">$29<", ">$59<", ">$89<",
        ]
        found_dummy = [d for d in dummy_signals if d in lower]
        if found_dummy:
            reasons.append(
                f"[품질] dummy 상품 감지: {found_dummy}. "
                f"실제 Amazon 상품으로 교체 필수. "
                f"GOOGLE_SEARCH_CX 환경변수 및 DRY_RUN_MODE 확인."
            )

        # ── Gate 15: FAQ 답변 품질 ──────────────────────────
        faq_answers = re.findall(
            r'<h3[^>]*>[^<]*\?[^<]*</h3>\s*<p>(.*?)</p>',
            html_content, re.IGNORECASE | re.DOTALL
        )
        thin_faqs = []
        for ans in faq_answers:
            clean = re.sub(r'<[^>]+>', '', ans).strip()
            word_c = len(clean.split())
            if word_c < MIN_FAQ_ANSWER_WORDS:
                thin_faqs.append(word_c)
        if thin_faqs:
            warnings.append(
                f"[품질] FAQ 답변이 너무 짧음: {thin_faqs} 단어. "
                f"최소 {MIN_FAQ_ANSWER_WORDS}단어 권장. "
                f"얇은 FAQ는 AdSense 품질 심사에서 감점."
            )

        # ── Warning: 금지어 잔존 ────────────────────────────
        found_banned = [w for w in RESIDUAL_BANNED if w in lower]
        if found_banned:
            warnings.append(
                f"[언어] AI 냄새 나는 금지어 잔존: {found_banned}. "
                f"발행은 가능하나 수정 강권. AdSense는 AI 생성 느낌을 감지합니다."
            )

        # ── Warning: 필수 라벨 ──────────────────────────────
        has_best_overall = bool(re.search(
            REQUIRED_ELEMENTS["best_overall_h3"], html_content, re.IGNORECASE
        ))
        has_best_for = bool(re.search(
            REQUIRED_ELEMENTS["best_for"], html_content, re.IGNORECASE
        ))
        if not has_best_overall:
            warnings.append("[구조] 'Best Overall:' H3 라벨 누락.")
        if not has_best_for:
            warnings.append("[구조] 'Best for:' 문구 누락.")

        # ── Warning: 타이틀 중복 ────────────────────────────
        if re.search(r'\bbest best\b', title, re.IGNORECASE):
            warnings.append(f"[타이틀] 'Best Best' 중복: '{title}'")

        # ── AdSense 준비 판정 ───────────────────────────────
        hard_blocks = [r for r in reasons if "[ADSENSE]" in r or "[품질]" in r]
        adsense_ready = (
            len(reasons) == 0
            and word_count >= MIN_WORD_COUNT
            and has_disclosure
            and has_faq_schema
            and not found_dummy
        )

        # ── 품질 점수 ───────────────────────────────────────
        quality_score = self._calc_quality(
            word_count=word_count,
            h2_count=h2_count,
            h3_count=h3_count,
            has_faq="faq" in lower,
            has_schema=has_faq_schema,
            has_table='<table' in lower,
            banned_count=len(found_banned),
            has_best_overall=has_best_overall,
            has_best_for=has_best_for,
            has_disclosure=has_disclosure,
            has_last_updated=has_last_updated,
        )

        approved = len(reasons) == 0

        if approved:
            logger.info(
                f"[GOVERNOR] APPROVED: '{title}' | "
                f"quality={quality_score:.0f} | {word_count}단어 | "
                f"AdSense={'✅' if adsense_ready else '⚠️'}"
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
            adsense_ready=adsense_ready,
        )

    def record_publish(self, title: str, html_content: str, quality_score: float) -> None:
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
                f"{wait:.1f}시간 후 재시도."
            )
        return True, ""

    def _check_weekly_limit(self):
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        recent_week = [
            r for r in self._records
            if datetime.fromisoformat(r.published_at) > week_ago
        ]
        if self._records:
            first_dt = datetime.fromisoformat(self._records[0].published_at)
            blog_age_days = (now - first_dt).days
        else:
            blog_age_days = 0

        if blog_age_days < RAMP_DAYS:
            limit, phase = RAMP_MAX_PER_WEEK, f"램프업({blog_age_days}일차)"
        else:
            limit, phase = STEADY_MAX_PER_WEEK, "안정기"

        if len(recent_week) >= limit:
            return False, (
                f"주간 발행 한도 초과: 최근 7일 {len(recent_week)}개 / "
                f"한도 {limit}개 ({phase})."
            )
        return True, ""

    # ── 품질 점수 계산 (AdSense 가중치 반영) ────────────────

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
        has_disclosure: bool = False,
        has_last_updated: bool = False,
    ) -> float:
        score = 0.0

        # 단어수 (최대 30점 — AdSense 핵심)
        score += min(30.0, (word_count / MIN_WORD_COUNT) * 30.0)

        # 구조 (최대 20점)
        score += min(10.0, h2_count * 2.5)
        score += min(10.0, h3_count * 3.0)

        # AdSense 필수 요소 (최대 30점)
        if has_faq:          score += 8.0
        if has_schema:       score += 10.0
        if has_table:        score += 7.0
        if has_disclosure:   score += 5.0   # FTC + AdSense 필수

        # 라벨 품질 (최대 10점)
        if has_best_overall: score += 5.0
        if has_best_for:     score += 5.0

        # 신뢰 신호 보너스
        if has_last_updated: score += 2.0

        # 금지어 패널티
        score -= min(10.0, banned_count * 2.0)

        return round(max(0.0, min(100.0, score)), 1)

    # ── 로그 I/O ────────────────────────────────────────────

    def _load_log(self) -> list:
        if not self.log_path.exists():
            return []
        try:
            with open(self.log_path, encoding="utf-8") as f:
                data = json.load(f)
            return [
                PublishRecord(
                    title=item.get("title", ""),
                    published_at=item["published_at"],
                    word_count=item.get("word_count", 0),
                    quality_score=item.get("quality_score", 0.0),
                )
                for item in data if "published_at" in item
            ]
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
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text).strip()
        return len(text.split())
