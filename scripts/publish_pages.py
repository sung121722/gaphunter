"""
publish_pages.py
─────────────────
AdSense 심사 필수 정적 페이지 3개를 Blogger에 발행합니다.
  1. Privacy Policy
  2. About
  3. Contact

실행:
    py scripts/publish_pages.py
    py scripts/publish_pages.py --dry-run   # 발행 없이 미리보기만
"""

import sys
import os
import argparse
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env", override=True)

BLOG_ID  = os.getenv("BLOGGER_BLOG_ID", "")
BLOG_URL = "https://stuffnod.blogspot.com"
YEAR     = date.today().year


# ══════════════════════════════════════════════════════════════
# 페이지 콘텐츠
# ══════════════════════════════════════════════════════════════

PAGES = [

    # ── 1. Privacy Policy ──────────────────────────────────────
    {
        "title": "Privacy Policy",
        "content": f"""<h2>Privacy Policy</h2>
<p><em>Last updated: {date.today().strftime('%B %d, %Y')}</em></p>

<p>Welcome to StuffNod ("we," "us," or "our"). This Privacy Policy explains how we collect,
use, and protect information when you visit <strong>{BLOG_URL}</strong>.</p>

<h3>Information We Collect</h3>
<p>We do not directly collect personal information. However, third-party services used on
this site may collect data as described below.</p>

<h3>Google Analytics</h3>
<p>We use Google Analytics to understand how visitors interact with our site. Google Analytics
collects information such as your IP address, browser type, and pages visited.
This data is anonymous and used solely to improve our content.
You can opt out via the
<a href="https://tools.google.com/dlpage/gaoptout" target="_blank" rel="nofollow">Google Analytics Opt-out Browser Add-on</a>.</p>

<h3>Google AdSense</h3>
<p>We use Google AdSense to display advertisements. AdSense may use cookies to serve ads
based on your prior visits to this site or other sites. You can opt out of personalized
advertising by visiting <a href="https://www.google.com/settings/ads" target="_blank" rel="nofollow">Google Ad Settings</a>.</p>

<h3>Affiliate Links (Amazon Associates)</h3>
<p>StuffNod is a participant in the Amazon Services LLC Associates Program, an affiliate
advertising program designed to provide a means for sites to earn advertising fees by
advertising and linking to Amazon.com. When you click an affiliate link and make a purchase,
we may earn a small commission at no extra cost to you.</p>

<h3>Cookies</h3>
<p>This site uses cookies for analytics and advertising purposes. By continuing to use this
site, you consent to the use of cookies in accordance with this policy. You may disable
cookies in your browser settings, though this may affect site functionality.</p>

<h3>Third-Party Links</h3>
<p>Our posts contain links to external websites (including Amazon.com). We are not responsible
for the privacy practices of those sites and encourage you to review their privacy policies.</p>

<h3>Children's Privacy</h3>
<p>This site is not directed at children under 13. We do not knowingly collect personal
information from children.</p>

<h3>Changes to This Policy</h3>
<p>We may update this Privacy Policy from time to time. Changes will be posted on this page
with an updated date.</p>

<h3>Contact</h3>
<p>If you have questions about this Privacy Policy, please use our
<a href="{BLOG_URL}/p/contact.html">Contact page</a>.</p>
""",
    },

    # ── 2. About ───────────────────────────────────────────────
    {
        "title": "About StuffNod",
        "content": f"""<h2>About StuffNod</h2>

<p>StuffNod is an independent outdoor gear review site focused on helping campers,
hikers, and backpackers find equipment that actually holds up in the field.</p>

<h3>What We Do</h3>
<p>Every product we write about is researched through a combination of hands-on testing,
community feedback, and long-term reliability data. We don't just list specs — we explain
what those specs mean when you're three miles from the trailhead in the rain.</p>

<p>Our focus categories:</p>
<ul>
  <li>Backpacking tents and shelters</li>
  <li>Sleeping bags and pads</li>
  <li>Camp chairs, tables, and comfort gear</li>
  <li>Water filtration and hydration</li>
  <li>Headlamps, lanterns, and lighting</li>
  <li>Cooking systems and camp stoves</li>
  <li>Trekking poles and hiking footwear</li>
</ul>

<h3>Our Review Process</h3>
<p>Before recommending a product, we check:</p>
<ul>
  <li>Real-world user reviews across multiple platforms</li>
  <li>Long-term durability reports (not just first-impression reviews)</li>
  <li>Weight and pack size against stated specs</li>
  <li>Value relative to direct competitors in the same price range</li>
</ul>

<h3>Affiliate Disclosure</h3>
<p>StuffNod participates in the Amazon Associates program and other affiliate programs.
When you purchase through links on this site, we may earn a small commission.
This never affects which products we recommend — if something isn't worth buying,
we say so.</p>

<h3>Contact Us</h3>
<p>Questions, gear suggestions, or corrections? Visit our <a href="{BLOG_URL}/p/contact.html">Contact page</a>.</p>
""",
    },

    # ── 3. Contact ─────────────────────────────────────────────
    {
        "title": "Contact",
        "content": f"""<h2>Contact StuffNod</h2>

<p>Have a question about a product review, a gear suggestion, or found an error in one
of our posts? We'd like to hear from you.</p>

<h3>General Inquiries</h3>
<p>For general questions about our content or recommendations:</p>
<p>📧 Email: <strong>kang020672@gmail.com</strong></p>

<h3>Corrections & Updates</h3>
<p>If you've found outdated pricing, a discontinued product, or a factual error in one
of our reviews, please let us know. We update posts when products change significantly.</p>

<h3>Partnership & Collaboration</h3>
<p>We consider gear review partnerships on a selective basis. If you represent a brand
and would like to discuss a potential collaboration, please reach out with your product
details and we'll evaluate fit with our content focus.</p>

<h3>Response Time</h3>
<p>We typically respond within 2–3 business days.</p>

<hr>
<p><small>StuffNod | {BLOG_URL} | {YEAR}</small></p>
""",
    },
]


# ══════════════════════════════════════════════════════════════
# Blogger Pages API
# ══════════════════════════════════════════════════════════════

def _get_access_token() -> str:
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN", "")
    client_id     = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")

    if not all([refresh_token, client_id, client_secret]):
        raise ValueError("GOOGLE_REFRESH_TOKEN / GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET 미설정")

    resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
            "client_id":     client_id,
            "client_secret": client_secret,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def publish_page(title: str, content: str, access_token: str, dry_run: bool = False) -> dict:
    """Blogger Pages API로 정적 페이지 발행"""
    if dry_run:
        print(f"  [DRY-RUN] 페이지 발행 생략: '{title}'")
        return {"status": "dry_run", "title": title}

    if not BLOG_ID:
        raise ValueError("BLOGGER_BLOG_ID 환경변수 미설정")

    url  = f"https://www.googleapis.com/blogger/v3/blogs/{BLOG_ID}/pages/"
    body = {"title": title, "content": content}

    resp = httpx.post(
        url,
        json=body,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    data = resp.json()

    if resp.status_code in (200, 201):
        page_url = data.get("url", "")
        print(f"  ✅ 발행 완료: '{title}'")
        print(f"     URL: {page_url}")
        return {"status": "published", "title": title, "url": page_url}
    else:
        reason = data.get("error", {}).get("message", resp.text[:200])
        print(f"  ❌ 발행 실패: '{title}' — {reason}")
        return {"status": "error", "title": title, "reason": reason}


# ══════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="AdSense 필수 정적 페이지 발행")
    parser.add_argument("--dry-run", action="store_true", help="발행 없이 미리보기만")
    args = parser.parse_args()

    dry_run = args.dry_run

    print(f"\n{'='*55}")
    print(f"  AdSense 필수 페이지 발행")
    print(f"  블로그: {BLOG_URL}")
    print(f"  모드:   {'DRY-RUN (실제 발행 없음)' if dry_run else 'LIVE'}")
    print(f"{'='*55}\n")

    if not dry_run:
        print("[인증] Blogger API 토큰 발급 중...")
        try:
            token = _get_access_token()
            print("[인증] 완료\n")
        except Exception as e:
            print(f"[인증] 실패: {e}")
            sys.exit(1)
    else:
        token = ""

    results = []
    for page in PAGES:
        print(f"▶ '{page['title']}' 발행 중...")
        result = publish_page(page["title"], page["content"], token, dry_run=dry_run)
        results.append(result)
        print()

    print(f"{'='*55}")
    print(f"  완료: {len([r for r in results if r['status'] in ('published','dry_run')])}개 페이지")
    if not dry_run:
        print(f"\n  다음 단계:")
        print(f"  1. {BLOG_URL} 에서 Pages 메뉴 확인")
        print(f"  2. 블로그 레이아웃 → 'Pages' 위젯에 표시 설정")
        print(f"  3. AdSense 신청: https://www.google.com/adsense/start/")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
