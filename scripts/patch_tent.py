"""Tent 포스트 전용 패치: 이중 중첩 <a><a> 구조 처리"""
import os, httpx, re
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path("J:/gaphunter/.env"))

token_resp = httpx.post("https://oauth2.googleapis.com/token", data={
    "grant_type":    "refresh_token",
    "refresh_token": os.getenv("GOOGLE_REFRESH_TOKEN"),
    "client_id":     os.getenv("GOOGLE_CLIENT_ID"),
    "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
}, timeout=15)
token   = token_resp.json()["access_token"]
blog_id = os.getenv("BLOGGER_BLOG_ID")
pid     = "5761390724835661050"

r = httpx.get(
    f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts/{pid}",
    headers={"Authorization": f"Bearer {token}"},
    params={"fields": "content"},
    timeout=15,
)
content = r.json()["content"]

CTA_TEMPLATE = (
    '<p style="text-align: center; margin: 20px 0;">'
    '<a href="{href}" style="background-color: #ff9900; color: white; '
    'padding: 12px 24px; text-decoration: none; font-weight: bold; '
    'border-radius: 5px; display: inline-block;">'
    "&#x1F6D2; Check Latest Price on Amazon</a></p>"
)

FOMO_LINE = (
    '<p style="color: #d9534f; font-weight: bold;">'
    "<i>&#x1F525; Pro Tip: Stock moves fast heading into peak season "
    "— check availability before it sells out.</i></p>"
)

# 패턴: <p><a href="URL1"><a href="URL2">Buy on Amazon</a></a></p>
# 첫 번째 href (실제 제품 URL)를 사용해 CTA 버튼으로 교체
def convert_nested_links(content):
    def replacer(m):
        href = m.group(1)  # 첫 번째 (실제 상품) URL
        return CTA_TEMPLATE.format(href=href)

    pattern = re.compile(
        r'<p[^>]*>\s*<a\s+href="(https://www\.amazon\.com[^"]+)"[^>]*>'
        r'\s*<a\s+href="[^"]*"[^>]*>Buy on Amazon</a>\s*</a>\s*</p>',
        re.IGNORECASE | re.DOTALL,
    )
    return pattern.sub(replacer, content)

original = content
content  = convert_nested_links(content)
cta_count = content.count("ff9900")
print(f"CTA buttons: {cta_count}")

# FOMO: CTA 버튼 앞에 삽입 (d9534f 없는 경우만)
if "d9534f" not in content:
    content = re.sub(
        r'(<p style="text-align: center; margin: 20px 0;">.*?Check Latest Price on Amazon.*?</p>)',
        FOMO_LINE + "\n" + r"\1",
        content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    print(f"FOMO lines: {content.count('d9534f')}")
else:
    print("FOMO already present")

# Buyer's Guide h2 정비
content = re.sub(
    r"<h2>\s*Buyer's Guide: How to Choose\s*</h2>",
    "<h2>Buyer's Guide: How to Choose</h2>",
    content, flags=re.IGNORECASE,
)

if content == original:
    print("No changes — skip")
else:
    status = httpx.patch(
        f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts/{pid}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"content": content},
        timeout=30,
    ).status_code
    print(f"PATCH status: {status}")
