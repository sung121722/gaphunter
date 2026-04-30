"""
patch_all_posts.py — 기존 3개 Blogger 포스트 일괄 패치
1. "Buy on Amazon" 텍스트 링크 → 오렌지 CTA 버튼 변환
2. FOMO 없는 포스트에 FOMO 삽입
3. Tarp Shelter: 제품 h2 → h3 변환 + h2 섹션 헤더 추가
4. 모든 포스트 h2 섹션 구조 정비 (Buyer's Guide, FAQ)
"""
import os, httpx, re, sys
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path("J:/gaphunter/.env"))

# ── Auth ──────────────────────────────────────────────────────────────────────
token_resp = httpx.post("https://oauth2.googleapis.com/token", data={
    "grant_type":    "refresh_token",
    "refresh_token": os.getenv("GOOGLE_REFRESH_TOKEN"),
    "client_id":     os.getenv("GOOGLE_CLIENT_ID"),
    "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
}, timeout=15)
token   = token_resp.json()["access_token"]
blog_id = os.getenv("BLOGGER_BLOG_ID")

POSTS = {
    "6818779375438881858": "Tarp Shelter",
    "1177118500485374701": "Water Filters",
    "5761390724835661050": "Tent",
}

FOMO_LINE = (
    '<p style="color: #d9534f; font-weight: bold;">'
    "<i>&#x1F525; Pro Tip: Stock moves fast heading into peak season "
    "— check availability before it sells out.</i></p>"
)

CTA_TEMPLATE = (
    '<p style="text-align: center; margin: 20px 0;">'
    '<a href="{href}" style="background-color: #ff9900; color: white; '
    'padding: 12px 24px; text-decoration: none; font-weight: bold; '
    'border-radius: 5px; display: inline-block;">'
    "&#x1F6D2; Check Latest Price on Amazon</a></p>"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_post(pid):
    r = httpx.get(
        f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts/{pid}",
        headers={"Authorization": f"Bearer {token}"},
        params={"fields": "title,content"},
        timeout=15,
    )
    return r.json()


def patch_post(pid, content):
    r = httpx.patch(
        f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts/{pid}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"content": content},
        timeout=30,
    )
    return r.status_code


def convert_text_links_to_cta(content):
    """
    패턴: <p>? <a href="URL" ...>Buy on Amazon</a></p>
    → 오렌지 CTA 버튼으로 교체
    """
    def replacer(m):
        href = m.group(1)
        return CTA_TEMPLATE.format(href=href)

    # "Buy on Amazon" 텍스트 링크 (다양한 주변 문자 포함)
    content = re.sub(
        r'<p[^>]*>[^<]{0,20}<a\s+href="(https://www\.amazon\.com[^"]*)"[^>]*>'
        r'Buy on Amazon</a></p>',
        replacer,
        content,
        flags=re.IGNORECASE,
    )
    return content


def inject_fomo_before_cta(content):
    """
    오렌지 CTA 버튼 바로 앞에 FOMO 삽입 (이미 FOMO 있으면 skip)
    """
    if "d9534f" in content:
        # 이미 일부 FOMO 존재 — CTA 앞에 없는 것만 추가
        # CTA 바로 앞에 d9534f 없으면 삽입
        def maybe_inject(m):
            before = content[:m.start()]
            # 앞 300자 안에 d9534f 있으면 skip
            if "d9534f" in before[-300:]:
                return m.group(0)
            return FOMO_LINE + "\n" + m.group(0)
        return re.sub(
            r'<p style="text-align:\s*center[^>]*>.*?Check Latest Price on Amazon.*?</p>',
            maybe_inject,
            content,
            flags=re.DOTALL | re.IGNORECASE,
        )
    else:
        # FOMO 전혀 없음 — 모든 CTA 앞에 삽입
        return re.sub(
            r'(<p style="text-align:\s*center[^>]*>.*?Check Latest Price on Amazon.*?</p>)',
            FOMO_LINE + "\n" + r"\1",
            content,
            flags=re.DOTALL | re.IGNORECASE,
        )


def fix_heading_hierarchy(content, label):
    """
    Tarp Shelter: 제품 h2 → h3, h2 섹션 헤더 정비
    Water Filters / Tent: h2 섹션 헤더 정비만
    """
    if label == "Tarp Shelter":
        # 제품 리뷰 h2들 → h3 (Honest Reviews 섹션 내부)
        # "Honest Reviews" 이후, "What Actually Matters" 이전 구간의 h2 → h3
        # 전략: "Best ... Pick", "Best for", "Best If" 패턴 h2 → h3
        product_h2_pattern = re.compile(
            r'<h2>((Best|The Best)[^<]{0,80})</h2>',
            re.IGNORECASE,
        )
        # "Honest Reviews" h2 → h2 "Our Top 3 Picks" 로 교체
        content = re.sub(
            r'<h2>\s*Honest Reviews\s*</h2>',
            '<h2>Our Top 3 Ultralight Tarp Shelter Picks</h2>',
            content, flags=re.IGNORECASE,
        )
        # 제품 h2 → h3
        content = product_h2_pattern.sub(r'<h3>\1</h3>', content)

    # 공통: Buyer's Guide h2 정비
    content = re.sub(
        r'<h2>\s*What Actually Matters When Choosing[^<]*</h2>',
        "<h2>Buyer's Guide: How to Choose</h2>",
        content, flags=re.IGNORECASE,
    )
    # 공통: FAQ h2 정비
    content = re.sub(
        r'<h2>\s*Frequently Asked Questions\s*</h2>',
        "<h2>Frequently Asked Questions</h2>",
        content, flags=re.IGNORECASE,
    )
    # "Bottom Line" h2 제거 (내용은 유지, h2 태그만 p로 바꿈)
    content = re.sub(
        r'<h2>\s*Bottom Line\s*</h2>',
        "<h2>Final Verdict</h2>",
        content, flags=re.IGNORECASE,
    )
    return content


# ── Main ──────────────────────────────────────────────────────────────────────

for pid, label in POSTS.items():
    print(f"\n{'='*55}")
    print(f"Processing: {label} ({pid})")

    post    = get_post(pid)
    title   = post.get("title", "").encode("ascii", "replace").decode()
    content = post.get("content", "")
    original = content

    # 1. 텍스트 Buy on Amazon → 오렌지 CTA 버튼
    before_cta = content
    content = convert_text_links_to_cta(content)
    cta_added = content.count("ff9900") - before_cta.count("ff9900")
    print(f"  CTA buttons added  : {cta_added}")

    # 2. FOMO 삽입
    before_fomo = content.count("d9534f")
    content = inject_fomo_before_cta(content)
    fomo_added = content.count("d9534f") - before_fomo
    print(f"  FOMO lines added   : {fomo_added}")

    # 3. 헤딩 계층 정비
    content = fix_heading_hierarchy(content, label)

    # 변경 없으면 skip
    if content == original:
        print("  No changes — skip")
        continue

    status = patch_post(pid, content)
    print(f"  PATCH status       : {status}")
    if status not in (200, 204):
        print(f"  [ERROR] Unexpected status {status}")

print("\nDone.")
