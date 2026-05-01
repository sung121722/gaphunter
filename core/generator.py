"""
generator.py — Content generation module via Claude API
Produces SEO-optimized articles that fill predicted content gaps.

Flow (LIVE mode):
  1. _search_products()   → SerpAPI로 쿠팡/아마존 실제 상품 조사
  2. _build_user_prompt() → 조사된 상품을 포함한 프롬프트 생성
  3. _claude_post()       → Claude API로 포스트 생성
  4. post-processing      → 링크 변환 / 필수 문구 삽입
"""

import sys
import json
import datetime
import logging
import re
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


# ─── Prompt templates ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert SEO data analyst and a 10-year veteran e-commerce conversion copywriter. Your target audience is strictly the 20s to 40s demographic — smart, active, and pragmatic buyers who highly value functionality, ultralight specs, efficiency, and solving specific daily or outdoor problems.

HEADING HIERARCHY (critical for SEO — never skip a level):
  h1  → page title (once, at the top)
  h2  → major section headings (Hook headline, Top 3 section, Buyer's Guide, FAQ)
  h3  → individual product names only

REQUIRED POST STRUCTURE (follow this order exactly):

1. <!-- META: ... --> (first line, 155 chars max, include keyword)
2. <p><em><strong>Affiliate Disclosure:</strong> This post contains affiliate links. If you buy through them, we earn a small commission at no extra cost to you. We only recommend products we have personally tested.</em></p>
3. <h1>[keyword] [current year]</h1>
4. <small>Last updated: [Month Year]</small>

5. HOOKING INTRO:
   <h2>[Punchy hook headline — provocative, speaks directly to the pain point]</h2>
   <p>2-3 sentences. 20-40s mindset: maximizing efficiency, shaving pack weight, upgrading lifestyle. Zero warm-up.</p>

6. QUICK SUMMARY TABLE:
   <table> — Top 3 products from Verified Products only.
   Columns: Product Name | Best Feature | Price Range | Key Spec/Weight
   Price Range: NEVER say "check price" — always write "Typically $X-$Y".

7. TOP 3 PRODUCT REVIEWS:
   <h2>Our Top 3 [Keyword] Picks</h2>
   For each of the 3 best Verified Products, in this exact order:
   a. <h3>[Award Title]: [Product Name]</h3>  (e.g., "Best Ultralight Pick: Brand X", "Best Budget Pick: Brand Y")
   b. <p><i>[Image Placeholder: Insert Product Image Here]</i></p>
   c. <p>Sharp explanation of why this gear is top-tier. First-person testing language: "What I immediately noticed was..." / "After two weekends with this..." Include 1 real spec (weight, lumens, capacity, etc.).</p>
   d. <ul>
      <li><b>Pro:</b> [specific, measurable benefit]</li>
      <li><b>Pro:</b> [specific, measurable benefit]</li>
      <li><b>Pro:</b> [specific, measurable benefit]</li>
      <li><b>Con:</b> [1 honest, minor flaw — exact wording, e.g. "buckle rattles on rocky descents"]</li>
      </ul>
   e. <p style="color: #d9534f; font-weight: bold;"><i>🔥 Pro Tip: [1 sentence FOMO/urgency — season- or stock-specific, e.g. "Usually sells out before peak season — grab it now."]</i></p>
   f. EXACT CTA HTML (required after every product — no exceptions):
      <p style="text-align: center; margin: 20px 0;"><a href="[AMAZON_LINK:product name]" style="background-color: #ff9900; color: white; padding: 12px 24px; text-decoration: none; font-weight: bold; border-radius: 5px; display: inline-block;">🛒 Check Latest Price on Amazon</a></p>

8. BUYER'S GUIDE:
   <h2>Buyer's Guide: How to Choose the Right [Keyword]</h2>
   <ul> — 3 no-nonsense, technical tips. Focus on materials, weight-to-ratio, packability, durability metrics. No fluff.

9. FAQ:
   <h2>Frequently Asked Questions</h2>
   3 highly specific, technical questions the 20-40s demographic searches on Reddit or Google.
   Each Q as <h3>, answer as <p>. Direct, confident, real numbers.

10. JSON-LD FAQPage schema (Google Rich Snippet — required):
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"FAQPage","mainEntity":[
      {"@type":"Question","name":"Q1?","acceptedAnswer":{"@type":"Answer","text":"A1."}},
      {"@type":"Question","name":"Q2?","acceptedAnswer":{"@type":"Answer","text":"A2."}},
      {"@type":"Question","name":"Q3?","acceptedAnswer":{"@type":"Answer","text":"A3."}}
    ]}
    </script>

STRICT SALES RULES (violating any = rewrite):
- NICHE MATCHING: If topic is "Solo", ONLY solo gear. If "Ultralight", NOTHING over 2 lbs. Keep the niche razor-sharp.
- NO PRICE UNCERTAINTY: NEVER write "Price isn't listed" or "check price". Always provide a psychological price anchor.
- FOMO: Every product MUST have the red urgency line (step 7e). Season- or stock-specific.
- CTA: Every product MUST have the exact orange Amazon button (step 7f). No exceptions.
- Only use Verified Products — never fabricate products.

WRITING RULES:
- Vary sentence length hard. "Nope." beside a 40-word sentence.
- One-word reactions: "Impressive." / "Overkill." / "Skip it."
- Con must name the exact flaw: "zipper snagged on day 3", not "some users report issues"
- Exact numbers always. Never round 1.87 lbs to "under 2 lbs."
- Contractions always: it's, you'll, don't, that's

BANNED WORDS (fail condition — rewrite entire sentence if found):
comprehensive, delve, tapestry, seamlessly, furthermore, in conclusion,
it's worth noting, game-changer, leverage, utilize, paradigm, synergy,
robust, boasts, testament, meticulous, stands out, look no further, holistic

OUTPUT FORMAT:
- Pure HTML body content only. No markdown. No code fences. No ```html wrappers.
- Allowed tags: h1 h2 h3 p ul li b strong em table tr th td a small script
- No html/head/body wrappers
- Affiliate links: [AMAZON_LINK:product name] placeholder in CTA href
- Only use Verified Products — never fabricate"""

SYSTEM_PROMPT_KO = """당신은 SEO 전문 데이터 분석가이자 10년 경력의 이커머스 전환율 카피라이터입니다. 타겟: 20~40대 — 기능성, 가성비, 실용성을 최우선으로 따지는 스마트한 구매자.

헤딩 계층 (SEO 필수 — 절대 단계 건너뛰지 말 것):
  h1  → 페이지 제목 (딱 한 번, 상단)
  h2  → 주요 섹션 헤더 (훅 헤드라인 / Top 3 섹션 / 구매 가이드 / FAQ)
  h3  → 개별 제품명 전용

필수 포스트 구조 (순서 그대로):

1. <!-- META: ... --> 첫 줄 (키워드 포함, 155자 이내)
2. <p><em><strong>제휴 링크 안내:</strong> 이 포스팅에는 쿠팡 파트너스 제휴 링크가 포함되어 있습니다. 링크를 통해 구매 시 소정의 수수료를 받을 수 있으며, 구매자에게 추가 비용은 없습니다. 직접 써본 제품만 추천합니다.</em></p>
3. <h1>[키워드] [연도]</h1>
4. <small>최종 업데이트: [연월]</small>

5. 훅 인트로:
   <h2>[핵심 페인포인트를 찌르는 도발적 헤드라인]</h2>
   <p>2~3문장. 20~40대 언어로 — 가성비, 무게, 효율, 실용. 워밍업 없이 바로 본론.</p>

6. 빠른 비교표:
   <table> — Verified Products 상위 3개만.
   컬럼: 제품명 | 핵심 특징 | 가격대 | 핵심 스펙/무게
   가격대: 절대 "가격 확인" 금지 — 반드시 "약 X만원대" 또는 "X,000원~Y,000원" 형식으로 작성.

7. 제품 리뷰 섹션:
   <h2>추천 Top 3: [키워드] 직접 써본 솔직 리뷰</h2>
   Verified Products 중 최상위 3개에 대해 아래 순서 그대로:
   a. <h3>[어워드 제목]: [제품명]</h3>  (예: "가성비 픽: 브랜드X", "초경량 픽: 브랜드Y", "디자인 픽: 브랜드Z")
   b. <p><i>[이미지 플레이스홀더: 제품 이미지 삽입]</i></p>
   c. <p>직접 테스트 언어로 핵심 설명. "직접 써보니 첫 느낌은...", "실제로 테스트해보니...", "한 달 써보고 나서...". 실제 수치 1개 반드시 포함 (무게·용량·밝기 등).</p>
   d. <ul>
      <li><b>장점:</b> [구체적, 수치 기반 혜택]</li>
      <li><b>장점:</b> [구체적, 수치 기반 혜택]</li>
      <li><b>장점:</b> [구체적, 수치 기반 혜택]</li>
      <li><b>단점:</b> [딱 1개 — 정확한 결함 명시, 예: "버클이 20회 개폐 후 헐거워짐"]</li>
      </ul>
   e. <p style="color: #d9534f; font-weight: bold;"><i>🔥 지금 바로: [1문장 FOMO/긴급성 — 시즌·재고 기반, 예: "5월 연휴 전 재고 빠르게 소진됩니다 — 지금 확인하세요."]</i></p>
   f. 쿠팡 CTA 버튼 (제품마다 필수 — 예외 없음):
      <p style="text-align: center; margin: 20px 0;"><a href="[COUPANG_LINK:제품명]" style="background-color: #ff6000; color: white; padding: 12px 24px; text-decoration: none; font-weight: bold; border-radius: 5px; display: inline-block;">🛒 쿠팡에서 최저가 확인하기</a></p>

8. 구매 가이드:
   <h2>구매 가이드: [키워드] 고를 때 진짜 봐야 할 것</h2>
   <ul> — 3가지 핵심 기준. 소재, 무게 대비 효율, 내구성 수치 중심. 군더더기 없이.

9. FAQ:
   <h2>자주 묻는 질문</h2>
   20~40대가 네이버·구글·레딧에서 실제로 검색하는 기술적 질문 3개.
   각 Q는 <h3>, 답변은 <p>. 직설적, 수치 포함.

10. JSON-LD FAQPage 스키마 (구글 리치 스니펫 — 필수):
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"FAQPage","mainEntity":[
      {"@type":"Question","name":"Q1?","acceptedAnswer":{"@type":"Answer","text":"A1."}},
      {"@type":"Question","name":"Q2?","acceptedAnswer":{"@type":"Answer","text":"A2."}},
      {"@type":"Question","name":"Q3?","acceptedAnswer":{"@type":"Answer","text":"A3."}}
    ]}
    </script>

11. 쿠팡 파트너스 필수 문구 (마지막에 반드시):
    <p><small>이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.</small></p>

판매 규칙 (위반 시 전면 재작성):
- 니치 매칭: 키워드가 "솔로"면 1인용만. "초경량"이면 2kg 초과 절대 금지.
- 가격 불확실성 금지: "가격 확인하세요" 절대 금지. 반드시 가격 앵커 제시.
- FOMO 필수: 모든 제품에 빨간 긴급성 문장 (7e항) 포함. 시즌·재고 구체적으로.
- CTA 필수: 모든 제품에 주황 쿠팡 버튼 (7f항) 포함. 예외 없음.
- Verified Products만 — 제품 창작 절대 금지.

글쓰기 규칙:
- 문장 길이 들쑥날쑥. "별로." 한 단어 옆에 40자짜리 문장. 균일 금지.
- 직접 테스트 언어 필수: "직접 써보니", "실제 테스트해보니", "한 달 써보고 나서"
- 한 단어 단평: "별로.", "오버스펙.", "패스." — 적절히 섞어라
- 단점은 반드시 구체적 결함: "3일째 지퍼 걸림", "버클이 반복 개폐 시 약함"
- 실제 수치 그대로 (850g을 "1kg 미만"으로 뭉개기 금지)
- 구어체 자연스럽게: "근데", "사실", "솔직히"

금지 표현 (있으면 전면 재작성):
살펴보겠습니다, 알아보겠습니다, 중요합니다, 다양한, 최적의, 효과적인,
포괄적인, 탁월한, 시너지, 패러다임, 원활하게, 결론적으로, 최고의 선택

출력:
- 순수 HTML만. 마크다운 없음.
- 허용 태그: h1 h2 h3 p ul li strong em table tr th td a small script
- html/head/body 래퍼 없음
- Verified Products만 — 제품 창작 절대 금지"""


# ─── Step 1: 상품 조사 (SerpAPI) ──────────────────────────────────────────────

def _crawl_product_details(url: str, language: str) -> dict:
    """
    제품 페이지를 실시간 크롤링해 실제 스펙·가격·특징 추출.
    Amazon(EN) / Coupang(KO) 모두 지원. 실패 시 빈 dict 반환.
    """
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8" if language == "ko" else "en-US,en;q=0.9",
        }
        resp = httpx.get(url, headers=headers, timeout=12, follow_redirects=True)
        if resp.status_code != 200:
            return {}

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")

        result = {}

        if language == "en" and "amazon.com" in url:
            # Amazon 제품 페이지 파싱
            t = soup.find("span", {"id": "productTitle"})
            result["name"] = t.get_text(strip=True)[:120] if t else ""

            # 가격 (여러 selector 시도)
            for sel in ["span.a-price-whole", "#priceblock_ourprice",
                        "#priceblock_dealprice", "span.a-offscreen"]:
                p = soup.select_one(sel)
                if p:
                    result["price"] = p.get_text(strip=True)[:30]
                    break

            # 제품 특징 bullet points
            bullets = soup.select("#feature-bullets ul li span.a-list-item")
            result["features"] = [b.get_text(strip=True)[:150]
                                   for b in bullets[:6] if b.get_text(strip=True)]

            # 별점
            r = soup.select_one("span.a-icon-alt")
            result["rating"] = r.get_text(strip=True)[:20] if r else ""

            # 리뷰 수
            rc = soup.select_one("#acrCustomerReviewText")
            result["review_count"] = rc.get_text(strip=True)[:30] if rc else ""

        elif language == "ko" and "coupang.com" in url:
            # 쿠팡 제품 페이지 파싱
            t = soup.find("h1", {"class": "prod-buy-header__title"}) or \
                soup.find("div", {"class": "prod-title"})
            result["name"] = t.get_text(strip=True)[:120] if t else ""

            p = soup.select_one("strong.prod-buy-price__item-price") or \
                soup.select_one(".total-price strong")
            result["price"] = p.get_text(strip=True)[:30] if p else ""

            bullets = soup.select(".prod-attr-list li") or \
                      soup.select(".product-detail-content li")
            result["features"] = [b.get_text(strip=True)[:150]
                                   for b in bullets[:6] if b.get_text(strip=True)]

            r = soup.select_one(".rating-star-num")
            result["rating"] = r.get_text(strip=True)[:20] if r else ""

        return result

    except Exception as e:
        logger.debug("Product crawl failed for %s: %s", url, e)
        return {}


def _search_products(keyword: str, language: str) -> list[dict]:
    """
    SerpAPI로 쿠팡(KO) 또는 아마존(EN) 실제 상품을 검색 후
    제품 페이지를 실시간 크롤링해 스펙·가격·특징까지 보강.
    DRY_RUN 또는 키 없으면 더미 반환.

    Returns: [{"name": str, "url": str, "price": str, "features": [...], ...}, ...]
    """
    if config.DRY_RUN_MODE or not config.SERPAPI_KEY:
        logger.info("[DRY] _search_products: returning dummy products for '%s'", keyword)
        return _dummy_products(keyword, language)

    current_year = datetime.date.today().year
    if language == "ko":
        query = f"site:coupang.com {keyword} 로켓배송"
    else:
        query = f"site:amazon.com {keyword} best seller {current_year}"

    params = {
        "q":       query,
        "api_key": config.SERPAPI_KEY,
        "num":     10,
        "gl":      "kr" if language == "ko" else "us",
        "hl":      "ko" if language == "ko" else "en",
    }

    try:
        resp = httpx.get("https://serpapi.com/search", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("SerpAPI product search failed: %s — using dummy", e)
        return _dummy_products(keyword, language)

    products = []
    for item in data.get("organic_results", []):
        title   = item.get("title", "")
        url     = item.get("link", "")
        snippet = item.get("snippet", "")

        # 쿠팡/아마존 상품 페이지만 필터
        if language == "ko" and "coupang.com/vp/products" not in url:
            continue
        if language == "en" and "amazon.com" not in url:
            continue

        # snippet에서 가격 파싱 (크롤링 전 기본값)
        price_match = re.search(r'[\$₩][\d,]+|[\d,]+원', snippet)
        price = price_match.group(0) if price_match else "가격 확인 필요"

        product = {
            "name":     title[:80],
            "url":      url,
            "price":    price,
            "snippet":  snippet[:150],
            "features": [],
            "rating":   "",
            "source":   "coupang" if language == "ko" else "amazon",
        }

        # ── 실시간 제품 페이지 크롤링으로 스펙 보강 ──────────────────
        details = _crawl_product_details(url, language)
        if details:
            if details.get("name"):
                product["name"] = details["name"]
            if details.get("price"):
                product["price"] = details["price"]
            if details.get("features"):
                product["features"] = details["features"]
            if details.get("rating"):
                product["rating"] = details["rating"]
            if details.get("review_count"):
                product["review_count"] = details["review_count"]
            logger.info("Crawled product details for: %s", product["name"][:50])

        products.append(product)
        if len(products) >= 5:
            break

    if not products:
        logger.warning("No products found via SerpAPI for '%s' — using dummy", keyword)
        return _dummy_products(keyword, language)

    logger.info("Found %d verified products for '%s'", len(products), keyword)
    return products


def _dummy_products(keyword: str, language: str) -> list[dict]:
    """DRY RUN용 더미 상품 목록."""
    if language == "ko":
        return [
            {"name": f"{keyword} A제품 (더미)", "url": "https://coupang.com", "price": "3~5만원", "snippet": "더미 상품입니다."},
            {"name": f"{keyword} B제품 (더미)", "url": "https://coupang.com", "price": "8~12만원", "snippet": "더미 상품입니다."},
            {"name": f"{keyword} C제품 (더미)", "url": "https://coupang.com", "price": "1~2만원", "snippet": "더미 상품입니다."},
        ]
    return [
        {"name": f"{keyword} Product A (dummy)", "url": "https://amazon.com", "price": "$29", "snippet": "Dummy product."},
        {"name": f"{keyword} Product B (dummy)", "url": "https://amazon.com", "price": "$59", "snippet": "Dummy product."},
        {"name": f"{keyword} Product C (dummy)", "url": "https://amazon.com", "price": "$89", "snippet": "Dummy product."},
    ]


# ─── Step 2: 프롬프트 생성 ────────────────────────────────────────────────────

def _build_user_prompt(keyword: str, gap_data: dict, language: str,
                        products: list[dict]) -> str:
    competitor_url = gap_data.get("competitor_url", "")
    gap_score      = gap_data.get("gap_score", 0)
    decay_prob     = gap_data.get("decay_probability", 0)
    gap_date       = gap_data.get("predicted_gap_date", "")

    # 검색된 상품 목록 → 프롬프트용 텍스트 (실시간 크롤링 스펙 포함)
    product_lines = []
    for i, p in enumerate(products, 1):
        features_text = ""
        if p.get("features"):
            features_text = "\n     Features:\n" + "\n".join(
                f"       - {f}" for f in p["features"]
            )
        rating_text = f"\n     Rating: {p['rating']}" if p.get("rating") else ""
        review_text = f" ({p['review_count']})" if p.get("review_count") else ""
        product_lines.append(
            f"  {i}. {p['name']}\n"
            f"     URL: {p['url']}\n"
            f"     Price: {p['price']}"
            f"{rating_text}{review_text}\n"
            f"     Snippet: {p.get('snippet', '')}"
            f"{features_text}"
        )
    product_block = "\n\n".join(product_lines) if product_lines else "  (검색 결과 없음)"

    # 경쟁사 페이지 실시간 리뷰 본문 (collector에서 크롤링된 body_text)
    competitor_refs = gap_data.get("competitors", [])
    ref_lines = []
    for c in competitor_refs[:2]:
        body = c.get("body_text", "").strip()
        if body:
            ref_lines.append(
                f"  Source: {c.get('url', '')[:80]}\n"
                f"  Excerpt: {body[:1500]}"
            )
    reference_block = "\n\n".join(ref_lines) if ref_lines else "  (없음)"

    current_year  = datetime.date.today().year
    current_month = datetime.date.today().strftime("%B %Y")   # e.g. "April 2026"

    if language == "ko":
        _today = datetime.date.today()
        current_month_ko = f"{_today.year}년 {_today.month}월"
        structure = f"""
<!-- META: {keyword} 직접 써본 후기. 가격·스펙 실시간 비교 {current_year}년 최신 업데이트. -->

<small>최종 업데이트: {current_year}년 {datetime.date.today().month}월 | 직접 사용 리뷰</small>

<h1>{keyword} 추천 (클릭 유발 제목 — 키워드 자연 포함)</h1>

<h2>한 줄 결론 — {keyword} 뭐 사야 해?</h2>
(2-3문장: 검색한 사람이 진짜 원하는 답 바로 제공. AI 냄새 금지.)

<h2>한눈에 비교</h2>
(Verified Products 기반 <table> — 제품명, 실제가격, 무게/크기, 추천대상, 단점 1줄)

<h2>제품별 솔직 리뷰</h2>
(각 제품: 실제 스펙 수치, 장점 2개, 단점 1개 이상, [COUPANG_LINK:제품명] 버튼)

<h2>{keyword} 고를 때 진짜 중요한 것</h2>
(4-5가지 기준. 광고 문구 아닌 실용적 기준만.)

<h2>자주 묻는 질문</h2>
(5개: People Also Ask 형식 실제 검색 질문 + 직접적 답변)
(뒤에 FAQPage JSON-LD schema 추가)

<h2>최종 추천 — {keyword} 이거 사세요</h2>
(1개 강추 + 이유 + [COUPANG_LINK:제품명])

<hr>
<p><small>이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.</small></p>"""

        # 계절 타이밍 컨텍스트 (KO)
        month = datetime.date.today().month
        if month in [3, 4, 5]:
            timing_ctx_ko = (
                f"[타이밍] 지금은 {current_year}년 {month}월. 캠핑 성수기(5~8월) 직전입니다. "
                f"사람들이 지금 활발하게 검색하고 구매하는 시기. "
                f"글에서 '캠핑 시즌 전 미리 준비' 맥락을 자연스럽게 녹이세요."
            )
        elif month in [6, 7, 8]:
            timing_ctx_ko = (
                f"[타이밍] 지금은 {current_year}년 {month}월. 캠핑 성수기 한가운데. "
                f"독자들이 바로 사용할 장비가 필요합니다. 빠른 배송·즉시 사용 강조."
            )
        elif month in [9, 10]:
            timing_ctx_ko = (
                f"[타이밍] 지금은 {current_year}년 {month}월. 가을 캠핑 + 동계 준비 시기. "
                f"가성비·내구성 중심으로 작성하세요."
            )
        else:
            timing_ctx_ko = (
                f"[타이밍] 지금은 {current_year}년 {month}월. 비수기 리서치 시기. "
                f"내년 시즌 대비 구매 의향자 대상으로 작성하세요."
            )

        return f"""다음 키워드로 SEO 글을 작성하세요: "{keyword}"

작성 날짜: {datetime.date.today()} | 최소 2000자 | 구어체 | AI 표현 일체 금지

{timing_ctx_ko}
경쟁사 콘텐츠 노후화 확률: {int(decay_prob*100)}% (60일 내) — 그 갭이 열리기 전에 먼저 선점해야 합니다.

Verified Products (오늘 {datetime.date.today()} 실시간 크롤링 — 이 제품만 사용):
{product_block}

참고 자료 (실시간 크롤링된 경쟁사 리뷰 — 스펙 정확도 참고용):
{reference_block}

필수 HTML 구조:
{structure}

첫 줄은 반드시 <!-- META: ... --> 로 시작. 그 다음 <small>업데이트 날짜</small>. 그 다음 <h1>. HTML만 출력."""

    else:
        structure = f"""
<!-- META: [155-char: include "{keyword}", year {current_year}, specific benefit] -->

<small>Last updated: {current_month} — tested hands-on</small>

<h1>[Keyword-rich title that makes someone click — not generic]</h1>

<h2>The Short Answer</h2>
(2-3 sentences: exactly what someone searching "{keyword}" needs to know RIGHT NOW)

<h2>Top {keyword.title()} — Quick Comparison</h2>
(table from Verified Products: name, price, weight/size, best for, one downside)

<h2>Honest Reviews</h2>
(per product: real specs, 2 pros, 1+ con, [AMAZON_LINK:product name])

<h2>What Actually Matters When Choosing</h2>
(4-5 practical criteria — no marketing fluff)

<h2>Frequently Asked Questions</h2>
(5 real People Also Ask questions + direct answers)
(follow immediately with FAQPage JSON-LD schema)

<h2>Bottom Line</h2>
(1 strongest pick + specific reason + [AMAZON_LINK:{keyword}])"""

        # 계절 타이밍 컨텍스트
        month = datetime.date.today().month
        if month in [3, 4, 5]:
            timing_ctx = (
                f"TIMING CONTEXT: It's {current_month}. Camping season is about to peak (May–August). "
                f"People are actively planning and buying NOW — before summer crowds. "
                f"This article needs to feel timely and urgent. Reference upcoming season where natural."
            )
        elif month in [6, 7, 8]:
            timing_ctx = (
                f"TIMING CONTEXT: It's {current_month}. Peak camping season. "
                f"Readers need answers fast — they're actively camping or about to go. "
                f"Keep advice practical and immediate."
            )
        elif month in [9, 10]:
            timing_ctx = (
                f"TIMING CONTEXT: It's {current_month}. End of camping season + fall hiking. "
                f"Great time to buy — end-of-season deals available. "
                f"Also cold-weather gear becoming relevant."
            )
        else:
            timing_ctx = (
                f"TIMING CONTEXT: It's {current_month}. Off-season planning phase. "
                f"Readers are researching for next season. Focus on durability and value."
            )

        return f"""Write a complete SEO article for: "{keyword}"

Today: {datetime.date.today()} | Year: {current_year} | All specs/prices from today's live crawl.
Minimum 1500 words. Human voice. Zero AI-sounding phrases.

{timing_ctx}

Gap context: competitors writing about this are {int(decay_prob*100)}% likely to decay in 60 days.
This article needs to rank BEFORE that gap opens (~{gap_date}).

Verified Products (live-scraped {datetime.date.today()} — use ONLY these):
{product_block}

Reference Sources (live-crawled review pages — use for real specs):
{reference_block}

Required HTML structure:
{structure}

First line MUST be <!-- META: ... -->. Then <small>Last updated</small>. Then <h1>. HTML only."""


# ─── Step 3: Claude API 호출 ──────────────────────────────────────────────────

def _extract_meta(content: str) -> tuple[str, str]:
    """
    첫 줄의 <!-- META: ... --> 주석에서 메타 디스크립션 추출.
    Returns (meta_description, content_without_meta_comment)
    """
    meta = ""
    lines = content.split("\n", 1)
    first = lines[0].strip()
    m = re.match(r"<!--\s*META:\s*(.+?)\s*-->", first)
    if m:
        meta = m.group(1)[:155]
        content = lines[1] if len(lines) > 1 else ""
    return meta, content.strip()


def _claude_post(keyword: str, gap_data: dict, language: str,
                  products: list[dict]) -> str:
    import anthropic

    sys_prompt = SYSTEM_PROMPT_KO if language == "ko" else SYSTEM_PROMPT
    client     = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    user_prompt = _build_user_prompt(keyword, gap_data, language, products)

    logger.info("Calling Claude API for '%s' (%s) with %d verified products",
                keyword, language, len(products))
    message = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=8192,
        system=sys_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return message.content[0].text


# ─── Step 4: 후처리 ───────────────────────────────────────────────────────────

def _check_ai_signatures(text: str) -> list[str]:
    """Return list of banned AI-signature words found in text."""
    found = []
    lower = text.lower()
    for word in config.AI_SIGNATURE_WORDS:
        if word.lower() in lower:
            found.append(word)
    return found


def _fix_nested_links(text: str) -> str:
    """
    Claude가 이미 <a href="..."> 태그를 생성했는데
    _inject_affiliate_links가 또 감싸서 이중 중첩이 되는 경우 수정.
    패턴: href="<a href="URL" ...>Buy on Amazon</a>"  → href="URL"
    """
    # href 안에 <a> 태그가 중첩된 경우 제거
    text = re.sub(
        r'href="<a href="([^"]+)"[^>]*>[^<]*</a>"',
        r'href="\1"',
        text,
    )
    return text


def _inject_affiliate_links(text: str, language: str) -> str:
    """Replace affiliate placeholders with real HTML anchor tags.
    이중 중첩 방지: Claude가 이미 <a> 태그를 넣은 경우 플레이스홀더만 교체.
    """
    if language == "ko":
        pid = config.COUPANG_PARTNERS_ID or "AF6344014"

        def _coupang_url(kw: str) -> str:
            return f"https://www.coupang.com/np/search?q={kw.strip()}&affiliate={pid}"

        def replace_coupang(match):
            url = _coupang_url(match.group(1))
            return (
                f'<a href="{url}" target="_blank" rel="nofollow" '
                f'style="background:#e84c5a;color:#fff;padding:6px 14px;'
                f'border-radius:4px;text-decoration:none;font-weight:bold;">'
                f'쿠팡에서 보기 →</a>'
            )

        # Case 1: placeholder inside href="" → URL only
        text = re.sub(
            r'href="\[COUPANG_LINK:([^\]]+)\]"',
            lambda m: f'href="{_coupang_url(m.group(1))}"',
            text,
        )
        text = re.sub(
            r'href="\[AMAZON_LINK:([^\]]+)\]"',
            lambda m: f'href="{_coupang_url(m.group(1))}"',
            text,
        )

        # Case 2: standalone placeholder → full <a> tag
        text = re.sub(r"\[COUPANG_LINK:([^\]]+)\]", replace_coupang, text)
        text = re.sub(r"\[AMAZON_LINK:([^\]]+)\]", replace_coupang, text)
        return _fix_nested_links(text)

    # English — Amazon Associates
    tag = config.AMAZON_ASSOCIATES_ID or ""

    def _amazon_url(kw: str) -> str:
        kw_enc = kw.strip().replace(" ", "+")
        return f"https://www.amazon.com/s?k={kw_enc}" + (f"&tag={tag}" if tag else "")

    # Case 1: placeholder is inside an existing href="" attribute → replace with URL only
    text = re.sub(
        r'href="\[AMAZON_LINK:([^\]]+)\]"',
        lambda m: f'href="{_amazon_url(m.group(1))}"',
        text,
    )
    text = re.sub(
        r'href="\[COUPANG_LINK:([^\]]+)\]"',
        lambda m: f'href="{_amazon_url(m.group(1))}"',
        text,
    )

    # Case 2: standalone placeholder → wrap with full <a> tag
    def replace_amazon(match):
        return f'<a href="{_amazon_url(match.group(1))}" target="_blank" rel="nofollow">Buy on Amazon</a>'
    text = re.sub(r"\[AMAZON_LINK:([^\]]+)\]", replace_amazon, text)
    text = re.sub(r"\[COUPANG_LINK:([^\]]+)\]", replace_amazon, text)
    return _fix_nested_links(text)


def _convert_markdown_links(text: str) -> str:
    """Safety net: convert leftover [text](url) markdown links to HTML <a> tags."""
    return re.sub(
        r'\[([^\]]+)\]\((https?://[^\)]+)\)',
        r'<a href="\2" target="_blank" rel="nofollow">\1</a>',
        text,
    )


# ─── Dummy generator (DRY RUN) ────────────────────────────────────────────────

def _dummy_post(keyword: str, language: str, products: list[dict]) -> str:
    if language == "ko":
        product_items = "\n".join(
            f"<li><strong>{p['name']}</strong> — {p['price']}</li>"
            for p in products
        )
        return (
            f"<h1>{keyword} 추천 TOP {len(products)} — 직접 써본 후기 (더미)</h1>\n"
            f"<h2>한 줄 결론</h2>\n"
            f"<p>{keyword}을 찾고 있다면 아래 검증된 제품 중에서 선택하세요.</p>\n"
            f"<h2>추천 제품</h2><ul>{product_items}</ul>\n"
            f"<p>[더미 포스트 — LIVE 모드에서 Claude API가 생성합니다 — {datetime.date.today()}]</p>"
        )
    product_items = "\n".join(
        f"<li><strong>{p['name']}</strong> — {p['price']}</li>"
        for p in products
    )
    return (
        f"<h1>Best {keyword.title()} — Tested and Ranked (Dummy)</h1>\n"
        f"<h2>The Quick Answer</h2>\n"
        f"<p>Top verified products for {keyword}:</p>\n"
        f"<ul>{product_items}</ul>\n"
        f"<p>[DUMMY POST — LIVE mode uses Claude API — {datetime.date.today()}]</p>"
    )


# ─── Public API ───────────────────────────────────────────────────────────────

def generate_post(keyword: str, gap_data: dict, language: str = "en") -> dict:
    """
    Generate a full SEO article for the given keyword and gap context.

    Flow:
      1. Search verified products via SerpAPI (coupang/amazon)
      2. Build prompt with verified product list
      3. Call Claude API (or return dummy in DRY_RUN)
      4. Post-process: inject affiliate links, convert markdown links
      5. Save to posts/ directory

    Returns dict with keyword, language, content, word_count, file_path, etc.
    """
    use_dummy = config.DRY_RUN_MODE or not config.ANTHROPIC_API_KEY

    # ── Step 1: 상품 조사 ──────────────────────────────────────────
    print(f"  [상품 조사] SerpAPI로 '{keyword}' 실제 상품 검색 중...")
    products = _search_products(keyword, language)
    print(f"  [상품 조사] {len(products)}개 상품 확인완료")
    for p in products:
        safe_name  = p['name'][:60].encode("ascii", errors="replace").decode()
        safe_price = str(p['price']).encode("ascii", errors="replace").decode()
        print(f"    - {safe_name} / {safe_price}")

    # ── Step 2+3: 포스트 생성 ──────────────────────────────────────
    if use_dummy:
        logger.info("[%s] generate_post: dummy content for '%s'",
                    "DRY" if config.DRY_RUN_MODE else "NO_KEY", keyword)
        content = _dummy_post(keyword, language, products)
    else:
        if config.MAX_CLAUDE_CALLS_PER_RUN <= 0:
            logger.warning("MAX_CLAUDE_CALLS_PER_RUN limit reached — skipping '%s'", keyword)
            return {"keyword": keyword, "skipped": True, "reason": "rate_limit"}
        content = _claude_post(keyword, gap_data, language, products)
        config.MAX_CLAUDE_CALLS_PER_RUN -= 1

        # ── 길이 부족 시 1회 재시도 ───────────────────────────────────
        min_len = config.MIN_CHAR_COUNT_KO if language == "ko" else config.MIN_WORD_COUNT_EN
        actual  = len(content) if language == "ko" else len(content.split())
        unit    = "자" if language == "ko" else "단어"

        if actual < min_len and config.MAX_CLAUDE_CALLS_PER_RUN > 0:
            logger.warning(
                "Content too short for '%s': %d%s (min %d) — retrying with stricter prompt",
                keyword, actual, unit, min_len
            )
            print(f"  [경고] 글 길이 부족 ({actual}{unit} < {min_len}{unit}) — 재생성 중...")

            # 재시도 프롬프트에 길이 위반 명시
            retry_note = (
                f"\n\nCRITICAL: Previous attempt was only {actual} {unit}. "
                f"You MUST write at least {min_len} {'characters' if language == 'ko' else 'words'}. "
                f"Expand every section. Do not skip any part of the required structure."
            ) if language == "en" else (
                f"\n\n[필수] 이전 출력이 {actual}자밖에 안 됐습니다. "
                f"반드시 {min_len}자 이상 작성하세요. 모든 섹션을 충분히 확장하세요."
            )

            import anthropic as _ant
            sys_prompt = SYSTEM_PROMPT_KO if language == "ko" else SYSTEM_PROMPT
            client2    = _ant.Anthropic(api_key=config.ANTHROPIC_API_KEY)
            user_prompt2 = _build_user_prompt(keyword, gap_data, language, products) + retry_note
            msg2 = client2.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=8192,
                system=sys_prompt,
                messages=[{"role": "user", "content": user_prompt2}],
            )
            content = msg2.content[0].text
            config.MAX_CLAUDE_CALLS_PER_RUN -= 1

            actual2 = len(content) if language == "ko" else len(content.split())
            print(f"  [재시도 결과] {actual2}{unit}")

    # ── Step 4: 후처리 ─────────────────────────────────────────────
    # 메타 디스크립션 추출 (첫 줄 <!-- META: ... --> 주석)
    meta_description, content = _extract_meta(content)

    content = _inject_affiliate_links(content, language)
    content = _convert_markdown_links(content)

    # 쿠팡 파트너스 필수 문구 자동 삽입 (KO)
    if language == "ko" and "쿠팡 파트너스 활동의 일환" not in content:
        content += (
            "\n<hr>\n"
            "<p><small>이 포스팅은 쿠팡 파트너스 활동의 일환으로, "
            "이에 따른 일정액의 수수료를 제공받습니다.</small></p>"
        )

    warnings = _check_ai_signatures(content)

    word_count = len(content.split())
    slug = re.sub(r"[^\w가-힣-]", "-", keyword.lower()).strip("-")
    filename = f"{slug}_{language}_{datetime.date.today()}.html"
    file_path = config.POSTS_DIR / filename

    config.POSTS_DIR.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")

    if warnings:
        logger.warning("AI signature words found in '%s': %s", keyword, warnings)

    return {
        "keyword":               keyword,
        "language":              language,
        "content":               content,
        "meta_description":      meta_description,
        "word_count":            word_count,
        "verified_products":     [p["name"] for p in products],
        "ai_signature_warnings": warnings,
        "generated_at":          datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "file_path":             str(file_path),
    }


# ─── CLI test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)

    snapshot_path = config.TRENDS_DIR / "camping_chairs_US.json"
    if not snapshot_path.exists():
        print("Run collector first: py core/collector.py")
        sys.exit(1)

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

    sys.path.insert(0, str(Path(__file__).parent))
    from predictor import run_predictions
    from scorer    import score_gap

    predictions = run_predictions(snapshot)
    gap_data    = score_gap(snapshot["keyword"], predictions)
    result      = generate_post(snapshot["keyword"], gap_data, language="en")

    if result.get("skipped"):
        print(f"Skipped: {result['reason']}")
        sys.exit(0)

    print("\n=== Generated Post ===")
    def _s(v): return str(v).encode("ascii", errors="replace").decode()
    print(f"  keyword            : {_s(result['keyword'])}")
    print(f"  words              : {result['word_count']}")
    print(f"  file               : {result['file_path']}")
    print(f"  verified_products  : {_s(result.get('verified_products', []))}")
    print(f"  warnings           : {_s(result['ai_signature_warnings'] or 'none')}")
    print()
    print("--- Preview (first 800 chars) ---")
    preview = result["content"][:800].encode("ascii", errors="replace").decode("ascii")
    print(preview)
    print("...")
