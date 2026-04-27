"""
publish_now.py — 기존 생성된 EN 포스트를 Blogger에 즉시 발행
사용법: py publish_now.py posts/camping-chairs_en_2026-04-23.html
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

import httpx

def get_access_token():
    refresh_token  = os.getenv("GOOGLE_REFRESH_TOKEN", "")
    client_id      = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret  = os.getenv("GOOGLE_CLIENT_SECRET", "")
    resp = httpx.post("https://oauth2.googleapis.com/token", data={
        "refresh_token": refresh_token,
        "client_id":     client_id,
        "client_secret": client_secret,
        "grant_type":    "refresh_token",
    })
    data = resp.json()
    if "access_token" not in data:
        print(f"[토큰 에러] 응답: {data}")
        raise Exception(f"토큰 발급 실패: {data}")
    return data["access_token"]

def publish(file_path: str):
    blog_id = os.getenv("BLOGGER_BLOG_ID", "")
    content = Path(file_path).read_text(encoding="utf-8")

    # h1 태그에서 제목 추출
    import re
    m = re.search(r"<h1[^>]*>(.*?)</h1>", content, re.DOTALL)
    title = m.group(1).strip() if m else Path(file_path).stem

    print(f"[pub] {title[:60].encode('ascii','replace').decode()}")
    token = get_access_token()

    resp = httpx.post(
        f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts/",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": title, "content": content},
        timeout=30,
    )
    data = resp.json()
    if "url" in data:
        print(f"[OK] {data['url']}")
    else:
        print(f"[FAIL] {data}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        # 인수 없으면 최근 EN 포스트 자동 선택
        posts = sorted(Path("posts").glob("*_en_*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not posts:
            print("EN 포스트 없음")
            sys.exit(1)
        file_path = str(posts[0])
        print(f"최근 포스트 선택: {file_path}")
    else:
        file_path = sys.argv[1]

    publish(file_path)
