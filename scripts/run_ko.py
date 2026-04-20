"""KO pipeline: 키워드 선택 → 수집 → 예측 → 생성 → 이메일 알림용 파일 저장"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.keyword_scheduler import pick_keyword, log_keyword
from core.collector  import collect
from core.predictor  import run_predictions
from core.scorer     import score_gap
from core.generator  import generate_post

lang    = "ko"
keyword = pick_keyword(lang)
print(f"[KO] 오늘의 키워드: {keyword}")

snapshot    = collect(keyword, geo="KR")
predictions = run_predictions(snapshot)
gap_result  = score_gap(keyword, predictions)
score       = gap_result["gap_score"]
print(f"[KO] gap_score: {score}")

post_result = generate_post(keyword, gap_result, language=lang)
if post_result.get("skipped"):
    print(f"[KO] 생성 스킵: {post_result['reason']}")
    sys.exit(0)

products  = post_result.get("verified_products", [])
file_path = post_result["file_path"]
file_name = os.path.basename(file_path)

log_keyword(keyword, lang, file_path, products, status="generated")

# 이메일 HTML 본문 생성
product_items = "".join(f"<li>{p}</li>" for p in products) if products else "<li>(상품 목록 없음)</li>"

html_body = f"""<html>
<body style="font-family:sans-serif;max-width:600px;margin:auto;padding:20px;">
<h2 style="color:#e84c5a;">GapHunter - 티스토리 발행 대기</h2>
<table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
  <tr>
    <td style="padding:8px;background:#f5f5f5;font-weight:bold;">키워드</td>
    <td style="padding:8px;">{keyword}</td>
  </tr>
  <tr>
    <td style="padding:8px;background:#f5f5f5;font-weight:bold;">파일명</td>
    <td style="padding:8px;font-family:monospace;">posts/{file_name}</td>
  </tr>
  <tr>
    <td style="padding:8px;background:#f5f5f5;font-weight:bold;">Gap Score</td>
    <td style="padding:8px;">{score}/100</td>
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
<p style="color:#999;font-size:12px;">GapHunter Bot - 자동 생성됨</p>
</body>
</html>"""

with open("/tmp/email_body.html", "w", encoding="utf-8") as f:
    f.write(html_body)

# GitHub Actions output
output_file = os.environ.get("GITHUB_OUTPUT", "/tmp/ko_output.txt")
with open(output_file, "a") as f:
    f.write(f"file_name={file_name}\n")
    f.write(f"keyword={keyword}\n")
    f.write(f"score={score}\n")

print(f"[KO] 포스트 생성 완료: {file_name}")
