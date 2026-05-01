"""
EN pipeline: 갭 스코어 기반 선별 발행

흐름:
  1. 트렌드 상위 5개 키워드 후보 선정
  2. 각 키워드 전체 분석 (collect → predict → score)
  3. gap_score 가장 높은 키워드 선택
  4. gap_score >= 55 → 정상 발행
  5. gap_score < 55 → fallback_keywords_en.txt에서 랜덤 키워드로 무조건 발행
     (블로그 맥박 유지 — 스킵 없음)
"""
import sys
import os
import random
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from core.keyword_scheduler import pick_top_keywords, log_keyword
from core.collector  import collect
from core.predictor  import run_predictions
from core.scorer     import score_gap
from core.generator  import generate_post
from core.publisher  import publish

LANG      = "en"
GEO       = "US"
MIN_SCORE = 55

FALLBACK_FILE = Path(__file__).parent.parent / "fallback_keywords_en.txt"

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
    gap_result  = score_gap(kw, predictions)
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
        lines = [l.strip() for l in FALLBACK_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
        best_keyword = random.choice(lines)
        print(f"[EN] Fallback 키워드 선택: '{best_keyword}'")

        snapshot    = collect(best_keyword, geo=GEO)
        predictions = run_predictions(snapshot)
        best_gap    = score_gap(best_keyword, predictions)
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

title   = f"Best {best_keyword.title()} ({config.CLAUDE_MODEL[:4].upper()} Tested {best_gap['predicted_gap_date'][:4]})"
content = post_result["content"]
pub     = publish(title, content, language=LANG, keyword=best_keyword, dry_run=False)

status   = pub.get("status", "error")
post_url = pub.get("post_url", "")
products = post_result.get("verified_products", [])

if status == "error":
    reason = pub.get("reason", "unknown")
    print(f"[EN] 발행 실패: {reason[:200]}")

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
