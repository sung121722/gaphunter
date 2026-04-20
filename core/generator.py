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

SYSTEM_PROMPT = """You are an expert SEO content writer. Write in a natural, conversational tone
that sounds like a real person who has used and tested these products — not a corporate marketer.

STRICT RULES:
- Never use these words: comprehensive, delve, tapestry, whimsical, bustling, seamlessly,
  furthermore, in conclusion, it's worth noting, it is important to note, dive deep,
  game-changer, leverage, utilize, paradigm, synergy, holistic, multifaceted, robust
- No generic intros like "In today's world..." or "Are you looking for..."
- Lead with the most useful information immediately
- Use specific numbers, weights, dimensions, prices where relevant
- Affiliate link placeholders: [COUPANG_LINK:제품명] or [AMAZON_LINK:KEYWORD]
- Output clean HTML only (no markdown, no code fences, no meta-commentary)
- Use proper HTML tags: <h1>, <h2>, <h3>, <p>, <ul>, <li>, <strong>, <table>, <tr>, <th>, <td>
- Do NOT include <html>, <head>, <body> tags — body content only
- NEVER use markdown link syntax [text](url) — always use <a href="url">text</a> instead
- All links must be proper HTML anchor tags with target="_blank" rel="nofollow"
- ONLY write about products provided in the "Verified Products" section — do NOT invent products"""


# ─── Step 1: 상품 조사 (SerpAPI) ──────────────────────────────────────────────

def _search_products(keyword: str, language: str) -> list[dict]:
    """
    SerpAPI로 쿠팡(KO) 또는 아마존(EN) 실제 상품을 검색해 반환.
    DRY_RUN 또는 키 없으면 더미 반환.

    Returns: [{"name": str, "url": str, "price": str, "source": str}, ...]
    """
    if config.DRY_RUN_MODE or not config.SERPAPI_KEY:
        logger.info("[DRY] _search_products: returning dummy products for '%s'", keyword)
        return _dummy_products(keyword, language)

    if language == "ko":
        query = f"site:coupang.com {keyword} 로켓배송"
    else:
        query = f"site:amazon.com {keyword} best seller"

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
        title = item.get("title", "")
        url   = item.get("link", "")
        snippet = item.get("snippet", "")

        # 쿠팡/아마존 상품 페이지만 필터
        if language == "ko" and "coupang.com/vp/products" not in url:
            continue
        if language == "en" and "amazon.com" not in url:
            continue

        # 간단한 가격 파싱 (snippet에서)
        price_match = re.search(r'[\$₩][\d,]+|[\d,]+원', snippet)
        price = price_match.group(0) if price_match else "가격 확인 필요"

        products.append({
            "name":    title[:80],
            "url":     url,
            "price":   price,
            "snippet": snippet[:150],
            "source":  "coupang" if language == "ko" else "amazon",
        })

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

    # 검색된 상품 목록 → 프롬프트용 텍스트
    product_lines = []
    for i, p in enumerate(products, 1):
        product_lines.append(
            f"  {i}. {p['name']}\n"
            f"     URL: {p['url']}\n"
            f"     Price: {p['price']}\n"
            f"     Info: {p.get('snippet', '')}"
        )
    product_block = "\n".join(product_lines) if product_lines else "  (검색 결과 없음)"

    if language == "ko":
        length_instruction = f"최소 {config.MIN_CHAR_COUNT_KO}자 (한국어)"
        lang_note = (
            "한국어로 작성. 자연스러운 구어체 사용. "
            "금지 표현: '살펴보겠습니다', '알아보겠습니다', '중요합니다', "
            "'다양한', '최적의', '효과적인' 같은 AI 티나는 표현 사용 금지. "
            "출력은 HTML만. 마크다운 사용 금지."
        )
        affiliate_note = (
            "쿠팡 링크 플레이스홀더: [COUPANG_LINK:제품명] 형식으로 삽입. "
            "Verified Products에 있는 제품만 리뷰할 것."
        )
        structure = f"""
<h1>제목 (키워드 포함, 클릭하고 싶은 제목)</h1>

<h2>한 줄 결론</h2>
(150-200자: "{keyword}" 검색한 사람이 실제로 원하는 답을 바로 제공)

<h2>한눈에 보는 추천 목록</h2>
(Verified Products 기반 <table> — 제품명, 가격대, 특징, 추천대상 포함)

<h2>제품별 상세 리뷰</h2>
(각 제품당 150-200자: 실제 스펙 수치 사용, [COUPANG_LINK:제품명] 버튼 포함)

<h2>구매 전 꼭 확인할 것</h2>
(400자: 실제로 중요한 기준 4-5가지, 불필요한 내용 제외)

<h2>자주 묻는 질문</h2>
(실제 검색자들이 궁금해하는 질문 4-5개, 직접적으로 답변)

<h2>최종 추천</h2>
(100자: 가장 강력한 제품 1개 추천 이유 명시, [COUPANG_LINK:제품명] 포함)"""
    else:
        length_instruction = f"Minimum {config.MIN_WORD_COUNT_EN} words"
        lang_note = "Write in English. American tone, direct and specific."
        affiliate_note = (
            "Amazon link placeholder: [AMAZON_LINK:KEYWORD] — include naturally. "
            "Only review products listed in Verified Products."
        )
        structure = f"""
<h1>Title (include keyword, make it click-worthy)</h1>

<h2>The Quick Answer</h2>
(150-200 words: direct answer to what someone searching "{keyword}" wants)

<h2>Top Picks at a Glance</h2>
(quick-reference <table> from Verified Products — include [AMAZON_LINK:{keyword}])

<h2>In-Depth Reviews</h2>
(each product: real specs — dimensions, weight, materials, price. [AMAZON_LINK:product])

<h2>Buying Guide: What Actually Matters</h2>
(4-5 criteria that separate good from bad, no fluff)

<h2>Frequently Asked Questions</h2>
(4-5 questions real searchers ask, answered directly)

<h2>Our Pick</h2>
(single strongest recommendation with specific reason, include [AMAZON_LINK:{keyword}])"""

    return f"""Write a complete SEO article targeting: "{keyword}"

Context:
- Gap score: {gap_score}/100 (gap opens ~{gap_date})
- Decaying competitor: {competitor_url} (decay: {decay_prob:.0%})
- Language: {lang_note}
- Length: {length_instruction}
- {affiliate_note}

Verified Products (ONLY use these — do NOT invent other products):
{product_block}

Required HTML structure:
{structure}

Start directly with <h1>. Output HTML only. No preamble."""


# ─── Step 3: Claude API 호출 ──────────────────────────────────────────────────

def _claude_post(keyword: str, gap_data: dict, language: str,
                  products: list[dict]) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    user_prompt = _build_user_prompt(keyword, gap_data, language, products)

    logger.info("Calling Claude API for '%s' (%s) with %d verified products",
                keyword, language, len(products))
    message = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
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


def _inject_affiliate_links(text: str, language: str) -> str:
    """Replace affiliate placeholders with real HTML anchor tags."""
    if language == "ko":
        pid = config.COUPANG_PARTNERS_ID or "AF6344014"
        def replace_coupang(match):
            kw = match.group(1).strip()
            url = f"https://www.coupang.com/np/search?q={kw}&affiliate={pid}"
            return (
                f'<a href="{url}" target="_blank" rel="nofollow" '
                f'style="background:#e84c5a;color:#fff;padding:6px 14px;'
                f'border-radius:4px;text-decoration:none;font-weight:bold;">'
                f'쿠팡에서 보기 →</a>'
            )
        text = re.sub(r"\[COUPANG_LINK:([^\]]+)\]", replace_coupang, text)
        # 혹시 AMAZON_LINK 플레이스홀더가 있으면 쿠팡으로 대체
        text = re.sub(r"\[AMAZON_LINK:([^\]]+)\]", replace_coupang, text)
        return text

    # English — Amazon Associates
    tag = config.AMAZON_ASSOCIATES_ID or ""
    def replace_amazon(match):
        kw = match.group(1).replace(" ", "+")
        url = f"https://www.amazon.com/s?k={kw}" + (f"&tag={tag}" if tag else "")
        return f'<a href="{url}" target="_blank" rel="nofollow">Buy on Amazon</a>'
    text = re.sub(r"\[AMAZON_LINK:([^\]]+)\]", replace_amazon, text)
    text = re.sub(r"\[COUPANG_LINK:([^\]]+)\]", replace_amazon, text)
    return text


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
        print(f"    - {p['name'][:60]} / {p['price']}")

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

    # ── Step 4: 후처리 ─────────────────────────────────────────────
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
    slug = keyword.lower().replace(" ", "-")
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
    print(f"  keyword            : {result['keyword']}")
    print(f"  words              : {result['word_count']}")
    print(f"  file               : {result['file_path']}")
    print(f"  verified_products  : {result.get('verified_products', [])}")
    print(f"  warnings           : {result['ai_signature_warnings'] or 'none'}")
    print()
    print("--- Preview (first 800 chars) ---")
    preview = result["content"][:800].encode("ascii", errors="replace").decode("ascii")
    print(preview)
    print("...")
