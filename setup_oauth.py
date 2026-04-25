"""
setup_oauth.py — Blogger OAuth2 최초 1회 설정
Google Cloud Console에서 OAuth2 클라이언트 ID 생성 후 실행.

사용법:
  py setup_oauth.py

결과:
  GOOGLE_REFRESH_TOKEN 출력 → .env 및 GitHub Secrets에 저장
"""

import sys
import os
import webbrowser
import urllib.parse
import http.server
import threading
import httpx
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

# ── 1. .env에서 자동 로드 ──────────────────────────────────────────────────────
CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
print(f"CLIENT_ID: {CLIENT_ID[:30]}...")
print(f"CLIENT_SECRET: {CLIENT_SECRET[:10]}...")

REDIRECT_URI  = "http://localhost:8080"
SCOPE         = "https://www.googleapis.com/auth/blogger"

# ── 2. 인증 URL 열기 ──────────────────────────────────────────────────────────
auth_url = (
    "https://accounts.google.com/o/oauth2/v2/auth"
    f"?client_id={CLIENT_ID}"
    f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
    f"&response_type=code"
    f"&scope={urllib.parse.quote(SCOPE)}"
    f"&access_type=offline"
    f"&prompt=consent"
)

print(f"\n브라우저에서 구글 계정으로 로그인하세요...")
webbrowser.open(auth_url)

# ── 3. 로컬 서버로 code 받기 ──────────────────────────────────────────────────
auth_code = None

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        auth_code = params.get("code", [None])[0]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"<h2>Auth complete! You may close this window.</h2>")
    def log_message(self, *args):
        pass

server = http.server.HTTPServer(("localhost", 8080), Handler)
t = threading.Thread(target=server.handle_request)
t.start()
t.join(timeout=120)

if not auth_code:
    print("인증 실패 — 타임아웃")
    sys.exit(1)

# ── 4. code → refresh_token 교환 ──────────────────────────────────────────────
resp = httpx.post(
    "https://oauth2.googleapis.com/token",
    data={
        "code":          auth_code,
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri":  REDIRECT_URI,
        "grant_type":    "authorization_code",
    },
)
data = resp.json()

if "refresh_token" not in data:
    print(f"\n토큰 발급 실패: {data}")
    sys.exit(1)

refresh_token = data["refresh_token"]

print(f"""
✅ 성공! 아래 3개를 .env 파일과 GitHub Secrets에 저장하세요:

GOOGLE_CLIENT_ID     = {CLIENT_ID}
GOOGLE_CLIENT_SECRET = {CLIENT_SECRET}
GOOGLE_REFRESH_TOKEN = {refresh_token}

GitHub Secrets 추가:
  Settings → Secrets → Actions → New repository secret
""")
