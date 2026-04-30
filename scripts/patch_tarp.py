"""Patch Tarp Shelter post: inject FOMO before each Buy on Amazon link."""
import os, httpx, re
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path("J:/gaphunter/.env"))

token_resp = httpx.post("https://oauth2.googleapis.com/token", data={
    "grant_type": "refresh_token",
    "refresh_token": os.getenv("GOOGLE_REFRESH_TOKEN"),
    "client_id": os.getenv("GOOGLE_CLIENT_ID"),
    "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
}, timeout=15)
token = token_resp.json().get("access_token", "")
blog_id = os.getenv("BLOGGER_BLOG_ID")
post_id = "6818779375438881858"

r = httpx.get(
    f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts/{post_id}",
    headers={"Authorization": f"Bearer {token}"},
    params={"fields": "content"},
    timeout=15,
)
content = r.json().get("content", "")

FOMO = (
    '<p style="color: #d9534f; font-weight: bold;">'
    "<i>&#x1F525; Pro Tip: Stock moves fast heading into peak season. "
    "Check availability before it sells out.</i></p>"
)

# <p>뭔가 <a href="https://www.amazon.com 패턴 앞에 FOMO 삽입
content_new = re.sub(
    r'(<p[^>]*>[^<]{0,10}<a\s+href="https://www\.amazon\.com)',
    FOMO + "\n" + r"\1",
    content,
)

count = content_new.count("d9534f")
print(f"FOMO injected: {count}x")

if content_new != content:
    pr = httpx.patch(
        f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts/{post_id}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"content": content_new},
        timeout=30,
    )
    print(f"PATCH status: {pr.status_code}")
else:
    print("no change")
