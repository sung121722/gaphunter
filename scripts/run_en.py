"""EN pipeline: 키워드 선택 → 수집 → 예측 → 생성 → Blogger 발행"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.keyword_scheduler import pick_keyword, log_keyword
from core.collector  import collect
from core.predictor  import run_predictions
from core.scorer     import score_gap
from core.generator  import generate_post
from core.publisher  import publish

lang    = "en"
keyword = pick_keyword(lang)
print(f"[EN] 오늘의 키워드: {keyword}")

snapshot    = collect(keyword, geo="US")
predictions = run_predictions(snapshot)
gap_result  = score_gap(keyword, predictions)
score       = gap_result["gap_score"]
print(f"[EN] gap_score: {score}")

post_result = generate_post(keyword, gap_result, language=lang)
if post_result.get("skipped"):
    print(f"[EN] 생성 스킵: {post_result['reason']}")
    sys.exit(0)

title   = f"Best {keyword.title()} 2026: Tested and Ranked"
content = post_result["content"]
pub     = publish(title, content, language=lang, dry_run=False)

status   = pub.get("status", "error")
post_url = pub.get("post_url", "")
products = post_result.get("verified_products", [])

log_keyword(keyword, lang, post_result["file_path"], products, status)

# GitHub Actions output
output_file = os.environ.get("GITHUB_OUTPUT", "/tmp/gh_output.txt")
with open(output_file, "a") as f:
    f.write(f"status={status}\n")
    f.write(f"post_url={post_url}\n")
    f.write(f"keyword={keyword}\n")

print(f"[EN] 발행 완료: {status} -> {post_url}")
