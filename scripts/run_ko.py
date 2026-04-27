"""
KO pipeline: 갭 스코어 기반 선별 생성

흐름:
  1. 트렌드 상위 3개 키워드 후보 선정
  2. 각 키워드 전체 분석 (collect → predict → score)
  3. gap_score 가장 높은 키워드 선택
  4. gap_score >= GAP_SCORE_MEDIUM(40)이어야만 생성
  5. 기준 미달 시 오늘은 스킵 — 아무 글이나 올리지 않는다
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from core.keyword_scheduler import pick_top_keywords, log_keyword
from core.collector  import collect
from core.predictor  import run_predictions
from core.scorer     import score_gap
from core.generator  import generate_post

LANG       = "ko"
GEO        = "KR"
MIN_SCORE  = config.GAP_SCORE_HIGH     # 60 — 이 이상만 생성 (빈자리 선점 기준)

# ── 1단계: 트렌드 기반 후보 3개 선정 ──────────────────────────────────────────
candidates = pick_top_keywords(LANG, n=3)
print(f"\n[KO] 후보 키워드: {candidates}")

# ── 2단계: 각 후보 전체 분석 → 최고 gap_score 찾기 ──────────────────────────
best_keyword  = None
best_score    = -1
best_snapshot = None
best_gap      = None

for kw in candidates:
    print(f"\n[KO] 분석 중: '{kw}'")
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

# ── 3단계: 기준 미달 시 스킵 ─────────────────────────────────────────────────
print(f"\n[KO] 최고 gap_score: {best_score} ('{best_keyword}')")

if best_score < MIN_SCORE:
    print(f"[KO] SKIP — gap_score {best_score} < 기준 {MIN_SCORE}")
    print(f"[KO] 오늘은 빈자리가 없습니다. 내일 다시 확인합니다.")

    output_file = os.environ.get("GITHUB_OUTPUT", "/tmp/ko_output.txt")
    with open(output_file, "a") as f:
        f.write(f"keyword={best_keyword}\n")
        f.write(f"score={best_score}\n")
        f.write(f"status=skipped\n")
    sys.exit(0)

# ── 4단계: 생성 결정 — 빈자리 선점 ──────────────────────────────────────────
print(f"\n[KO] GENERATE — '{best_keyword}'  gap_score={best_score}  "
      f"action={best_gap['action']}")
print(f"  경쟁자 decay: {best_gap['decay_probability']:.0%}  "
      f"갭 예상: {best_gap['predicted_gap_date']}")

post_result = generate_post(best_keyword, best_gap, language=LANG)
if post_result.get("skipped"):
    print(f"[KO] 생성 스킵: {post_result['reason']}")
    sys.exit(0)

products  = post_result.get("verified_products", [])
file_path = post_result["file_path"]
file_name = os.path.basename(file_path)

log_keyword(best_keyword, LANG, file_path, products, status="generated")

# 이메일 HTML 본문 생성
product_items = "".join(f"<li>{p}</li>" for p in products) if products else "<li>(상품 목록 없음)</li>"

html_body = f"""<html>
<body style="font-family:sans-serif;max-width:600px;margin:auto;padding:20px;">
<h2 style="color:#e84c5a;">GapHunter - 티스토리 발행 대기</h2>
<p style="background:#fff3cd;padding:12px;border-radius:6px;">
  <strong>gap_score {best_score}/100</strong> — {best_gap['action']}<br>
  경쟁자 decay 확률: {best_gap['decay_probability']:.0%} |
  갭 예상일: {best_gap['predicted_gap_date']}
</p>
<table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
  <tr>
    <td style="padding:8px;background:#f5f5f5;font-weight:bold;">키워드</td>
    <td style="padding:8px;">{best_keyword}</td>
  </tr>
  <tr>
    <td style="padding:8px;background:#f5f5f5;font-weight:bold;">파일명</td>
    <td style="padding:8px;font-family:monospace;">posts/{file_name}</td>
  </tr>
  <tr>
    <td style="padding:8px;background:#f5f5f5;font-weight:bold;">Gap Score</td>
    <td style="padding:8px;">{best_score}/100</td>
  </tr>
</table>
<h3>할 일 (약 15분)</h3>
<ol>
  <li>아래 제품들 쿠팡 파트너스에서 링크 생성</li>
  <li>posts/{file_name} 파일에 링크 교체</li>
  <li>티스토리 HTML 모드로 붙여넣기 후 발행</li>
</ol>
<h3>쿠팡 파트너스 링크 필요 제품</h3>
<ul>{product_items}</ul>
<p><a href="https://partners.coupang.com">partners.coupang.com</a> 에서 상품 검색 후 링크 생성</p>
<hr>
<p style="color:#999;font-size:12px;">GapHunter Bot — gap_score {best_score} / 기준 {MIN_SCORE}</p>
</body>
</html>"""

with open("/tmp/email_body.html", "w", encoding="utf-8") as f:
    f.write(html_body)

output_file = os.environ.get("GITHUB_OUTPUT", "/tmp/ko_output.txt")
with open(output_file, "a") as f:
    f.write(f"file_name={file_name}\n")
    f.write(f"keyword={best_keyword}\n")
    f.write(f"score={best_score}\n")
    f.write(f"status=generated\n")

print(f"\n[KO] 포스트 생성 완료: {file_name}")
print(f"[KO] gap_score: {best_score}  →  '{best_keyword}' 선점 준비 완료")
