"""
EN pipeline: 갭 스코어 기반 선별 발행

흐름:
  1. 트렌드 상위 5개 키워드 후보 선정
  2. 각 키워드 전체 분석 (collect → predict → score)
  3. gap_score 가장 높은 키워드 선택
  4. gap_score >= 55 → 정상 발행
  5. gap_score < 55 → category_config.fallback_keywords에서 랜덤 키워드로 무조건 발행
     (fallback_keywords_en.txt 존재 시 추가 병합, 블로그 맥박 유지 — 스킵 없음)

카테고리 변경: ACTIVE_CATEGORY 환경변수 또는 category_config.py 수정
"""
import sys
import os
import random
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from category_config import get_config as _get_category_config
from core.keyword_scheduler import pick_top_keywords, log_keyword
from core.collector  import collect
from core.predictor  import run_predictions
from core.scorer     import score_gap
from core.generator  import generate_post
from core.publisher  import publish
from core.publish_governor    import PublishGovernor
from core.competition_analyzer import analyze_competition, analyze_timing, adapt_competitors
from core.gsc_tracker          import GSCTracker

LANG      = "en"
GEO       = "US"
MIN_SCORE = 55

# ── Fallback 키워드: category_config 우선, 없으면 txt 파일 폴백 ──────────────
_CATEGORY_CFG    = _get_category_config()
_FALLBACK_TXT    = Path(__file__).parent.parent / "fallback_keywords_en.txt"
FALLBACK_KEYWORDS: list = _CATEGORY_CFG.fallback_keywords or []

# txt 파일에 추가 키워드가 있으면 병합 (중복 제거)
if _FALLBACK_TXT.exists():
    _txt_lines = [l.strip() for l in _FALLBACK_TXT.read_text(encoding="utf-8").splitlines() if l.strip()]
    _existing  = {kw.lower() for kw in FALLBACK_KEYWORDS}
    for _kw in _txt_lines:
        if _kw.lower() not in _existing:
            FALLBACK_KEYWORDS.append(_kw)
            _existing.add(_kw.lower())

print(f"[EN] Fallback 풀: {len(FALLBACK_KEYWORDS)}개 키워드 "
      f"({len(_CATEGORY_CFG.fallback_keywords)} category + "
      f"{len(FALLBACK_KEYWORDS) - len(_CATEGORY_CFG.fallback_keywords)} txt 추가)")

# ── 1단계: 트렌드 기반 후보 5개 선정 ──────────────────────────────────────────
candidates = pick_top_keywords(LANG, n=5)
print(f"\n[EN] 후보 키워드: {candidates}")

# ── 2단계: 각 후보 전체 분석 → 최고 gap_score 찾기 ──────────────────────────
best_keyword  = None
best_score    = -1
best_snapshot = None
best_gap      = None

for kw in candidates:
    print(f"\n[EN] 분석 중: '{kw}'")
    snapshot    = collect(kw, geo=GEO)
    predictions = run_predictions(snapshot)

    # ── competition_analyzer: 실제 경쟁 갭 + 타이밍 분석 ──────────
    _adapted       = adapt_competitors(snapshot.get("competitors", []))
    _trends_float  = [row["value"] for row in snapshot.get("trend_series", [])]
    _comp_result   = analyze_competition(_adapted)
    _timing_result = analyze_timing(_trends_float)

    gap_result  = score_gap(kw, predictions,
                            competition_gap_override=_comp_result.score,
                            timing_advantage_override=_timing_result.score)
    gap_result["competitors"] = snapshot.get("competitors", [])
    score = gap_result["gap_score"]

    print(f"  gap_score: {score}  ({gap_result['action']})")
    print(f"  decay_prob: {gap_result['decay_probability']:.0%}  "
          f"gap_date: {gap_result['predicted_gap_date']}")

    if score > best_score:
        best_score    = score
        best_keyword  = kw
        best_snapshot = snapshot
        best_gap      = gap_result

    if best_score >= config.GAP_SCORE_HIGH:
        print(f"  → gap_score {best_score} 충분, 나머지 후보 생략")
        break

# ── 3단계: 기준 미달 시 폴백 키워드로 대체 ───────────────────────────────────
print(f"\n[EN] 최고 gap_score: {best_score} ('{best_keyword}')")

is_fallback = False
if best_score < MIN_SCORE:
    print(f"[EN] gap_score {best_score} < 기준 {MIN_SCORE} — Fallback 모드 진입")
    try:
        if not FALLBACK_KEYWORDS:
            print("[EN] Fallback 풀이 비어 있습니다. 파이프라인 종료.")
            sys.exit(1)
        best_keyword = random.choice(FALLBACK_KEYWORDS)
        print(f"[EN] Fallback 키워드 선택: '{best_keyword}' "
              f"(풀 크기: {len(FALLBACK_KEYWORDS)})")

        snapshot    = collect(best_keyword, geo=GEO)
        predictions = run_predictions(snapshot)
        _adapted_fb      = adapt_competitors(snapshot.get("competitors", []))
        _trends_fb       = [row["value"] for row in snapshot.get("trend_series", [])]
        _comp_fb         = analyze_competition(_adapted_fb)
        _timing_fb       = analyze_timing(_trends_fb)
        best_gap    = score_gap(best_keyword, predictions,
                                competition_gap_override=_comp_fb.score,
                                timing_advantage_override=_timing_fb.score)
        best_gap["competitors"] = snapshot.get("competitors", [])
        best_score  = best_gap["gap_score"]
        is_fallback = True
        print(f"[EN] Fallback gap_score: {best_score}")
    except Exception as e:
        print(f"[EN] Fallback 실패: {e}")
        sys.exit(1)

# ── 4단계: 발행 결정 ──────────────────────────────────────────────────────────
mode_label = "[FALLBACK]" if is_fallback else "[GAP]"
print(f"\n[EN] PUBLISH {mode_label} - '{best_keyword}'  gap_score={best_score}  action={best_gap['action']}")
print(f"  경쟁자 decay: {best_gap['decay_probability']:.0%}  "
      f"갭 예상: {best_gap['predicted_gap_date']}")

post_result = generate_post(best_keyword, best_gap, language=LANG)
if post_result.get("skipped"):
    print(f"[EN] 생성 스킵: {post_result['reason']}")
    sys.exit(0)

content = post_result["content"]

# ── 제목: Claude가 생성한 H1 추출 → 없으면 키워드 기반 폴백 ──────────────────
import re as _re
_h1_match = _re.search(r'<h1[^>]*>(.*?)</h1>', content, _re.IGNORECASE | _re.DOTALL)
if _h1_match:
    # HTML 태그 제거 후 사용
    title = _re.sub(r'<[^>]+>', '', _h1_match.group(1)).strip()
    print(f"[EN] 제목 (H1 추출): {title}")
else:
    # 폴백: 키워드 기반 (H1이 없는 비정상 케이스)
    _kw = best_keyword.strip()
    _kw_title = _kw.title()
    _year = best_gap['predicted_gap_date'][:4]
    title = f"Best {_kw_title} ({_year})" if not _kw.lower().startswith("best ") \
            else f"{_kw_title} ({_year})"
    print(f"[EN] 제목 (폴백): {title}")

# ── GOVERNOR: 발행 전 품질 게이트 ────────────────────────────────────────────
_gov_log = Path(__file__).parent.parent / "wiki" / "publish_governor_log.json"
_governor = PublishGovernor(log_path=str(_gov_log))
_approval = _governor.approve(content, title)

for _w in _approval.warnings:
    print(f"[GOVERNOR] WARNING: {_w}")

if not _approval.approved:
    print(f"[GOVERNOR] BLOCKED (품질 기준 미달):")
    for _r in _approval.rejection_reasons:
        print(f"  -> {_r}")
    sys.exit(1)

print(f"[GOVERNOR] APPROVED | quality={_approval.quality_score:.0f} | words={_approval.word_count}")

pub     = publish(title, content, language=LANG, keyword=best_keyword, dry_run=False)

status   = pub.get("status", "error")
post_url = pub.get("post_url", "")
products = post_result.get("verified_products", [])

if status == "error":
    reason = pub.get("reason", "unknown")
    print(f"[EN] 발행 실패: {reason[:200]}")
else:
    # 발행 성공 시 governor 로그 기록
    _governor.record_publish(title, content, _approval.quality_score)

    # GSC 추적 등록 + 색인 요청 (Secrets 없으면 조용히 스킵)
    if post_url:
        _gsc = GSCTracker()
        _gsc.register_post(
            url=post_url,
            title=title,
            keyword=best_keyword,
            category=_CATEGORY_CFG.slug,
        )

log_keyword(best_keyword, LANG, post_result["file_path"], products, status)

output_file = os.environ.get("GITHUB_OUTPUT", os.path.join(os.environ.get("TEMP", "/tmp"), "gh_output.txt"))
with open(output_file, "a") as f:
    f.write(f"status={status}\n")
    f.write(f"post_url={post_url}\n")
    f.write(f"keyword={best_keyword}\n")
    f.write(f"score={best_score}\n")
    f.write(f"fallback={is_fallback}\n")

print(f"\n[EN] 발행 완료: {status} {mode_label}")
if post_url:
    print(f"[EN] URL: {post_url}")
print(f"[EN] gap_score: {best_score}  →  '{best_keyword}' 선점 완료")
