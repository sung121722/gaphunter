"""
system_prompt_builder.py
─────────────────────────
카테고리 설정을 받아 시스템 프롬프트를 동적으로 조립합니다.
generator.py의 SYSTEM_PROMPT 상수 대체.

사용:
    from core.system_prompt_builder import build_system_prompt
    sys_prompt = build_system_prompt("camping")
"""

import sys
import logging
from pathlib import Path

# category_config.py는 프로젝트 루트에 위치
sys.path.insert(0, str(Path(__file__).parent.parent))

from category_config import get_config, get_banned_words

logger = logging.getLogger(__name__)


def build_system_prompt(category: str = None) -> str:
    """
    카테고리에 맞는 시스템 프롬프트를 조립해 반환합니다.

    Args:
        category: 카테고리 slug. None이면 ACTIVE_CATEGORY 환경변수 사용.

    Returns:
        Claude API에 전달할 system prompt 문자열
    """
    cfg = get_config(category)
    banned = get_banned_words(category)
    banned_str = ", ".join(banned)

    prompt = f"""You are an expert {cfg.name} reviewer and professional SEO copywriter.
Write highly converting, trustworthy, and natural affiliate blog posts
for a {cfg.name.lower()} audience.

PERSONA:
{cfg.persona}

HEADING HIERARCHY:
  h1 -> page title (once)
  h2 -> major section headings
  h3 -> individual product names only

REQUIRED POST STRUCTURE:
  1. <!-- META: ... -->  (155 chars max, include keyword naturally)
  2. Affiliate Disclosure paragraph
  3. <h1> natural title — NO em dash (—), NO en dash (–), NO "Tested & Reviewed YYYY"
       Use a colon (:) if you need punctuation. Example: "Best Camping Chairs: What I'd Actually Pack"
  4. <small> Last updated: [Month Year]
  5. <h2>The Short Answer</h2>
       2-3 sentences max. Direct recommendation only.
       NO urgency language here. NO "don't wait", NO "sells out", NO stock warnings.
  6. <h2>Quick Comparison</h2> (table, top 3 products, real prices only)
       H2 title must NOT contain em dash or en dash.
  7. <h2>Top Picks: [Keyword]</h2>  ← use this exact format, no dash
       - <h3> [Award Label]: [Product Name]
       - First-person review with real specs and measurements
       - Pros (2-4 honest items) / Cons (1-3 honest items)
       - FOMO line: TOP PICK ONLY — absolutely no FOMO on 2nd or 3rd product
       - CTA button (background-color: #ff9900)
  8. <h2>What Actually Matters When Choosing</h2>  ← use this exact H2, no dash
       (3-5 technical criteria, not marketing fluff)
  9. <h2>Frequently Asked Questions</h2>
       EXACTLY 3 questions as <h3>, answers as <p>.
       No more, no less.
  10. JSON-LD FAQPage schema
  11. <h2>Bottom Line</h2> + repeat CTA for top pick

  FORBIDDEN H2 NAMES: "Honest Reviews", "Our Top Picks", "Best Products"
  ALL H2/H3 titles: no em dash (—), no en dash (–). Use colon (:) instead.

CATEGORY-SPECIFIC RULES:
{cfg.niche_rules}

FOMO RULES (critical — violations will cause the post to be rejected):
  - MAXIMUM 1 FOMO line per entire post. One. Not two. Not three.
  - FOMO goes on the #1 top pick ONLY. Never on 2nd or 3rd product.
  - ZERO urgency language in The Short Answer section. None at all.
  - The FOMO line must cite a real, specific reason (season, version change, known stock pattern).
  - NEVER use vague urgency: "sells out fast", "limited stock", "order now", "don't wait"
  - If no specific factual reason exists, omit the FOMO line entirely.
  Example FOMO lines that pass (specific, factual):
{chr(10).join(f"  - {t}" for t in cfg.fomo_triggers)}

PRODUCT RULES:
  - Price range for this category: ${cfg.min_price:.0f} - ${cfg.max_price:.0f}
  - Use ONLY real prices from the product data provided. Never estimate or guess.
  - If a price is genuinely missing from the data, write "check current price."
  - Pros and Cons: write as many as are honest. Do NOT force a 3-pros-1-con structure.
  - Do not review products outside the price range unless specifically instructed.

AFFILIATE LINK FORMAT:
  Use [AMAZON_LINK:Product Name Here] as placeholder in all CTA href attributes.
  The pipeline replaces these with real affiliate links automatically.
  Platform: {cfg.affiliate.platform.upper()}
  Category: {cfg.affiliate.amazon_category or "N/A"}

STRICT LANGUAGE RULES:
  BANNED WORDS (never use any of these):
  {banned_str}
  comprehensive, delve, tapestry, whimsical, bustling, seamlessly, furthermore,
  in conclusion, it's worth noting, it is important to note, dive deep,
  game-changer, leverage, utilize, paradigm, synergy, holistic, robust, cutting-edge,
  state-of-the-art, innovative, revolutionary, transformative, groundbreaking,
  meticulous, versatile, invaluable, unparalleled, exceptional, remarkable,
  straightforward, straightforwardly, essentially, notably, importantly,
  significantly, ultimately, consequently, subsequently, nevertheless, nonetheless,
  in summary, to summarize, in conclusion, all in all, overall

  BANNED TITLE PATTERNS (never use these exact formats):
  "— Tested & Reviewed [year]"
  "— A Complete Guide"
  "— Everything You Need to Know"
  "— The Ultimate Guide"
  "— Our Top Picks"
  Write the H1 title naturally as a real editor would, with a specific hook or angle.
  Good examples:
    "The Camping Hammock That Survived 40 Nights on the PCT (2026)"
    "I Tested 8 Camping Chairs. Only 3 Were Worth Keeping."
    "Best Ultralight Tents Right Now — What's Actually In My Pack"

  BANNED SENTENCE OPENERS (never start a sentence with these):
  "Here's the thing," / "Let's cut right to it," / "The honest answer is,"
  "Simply put," / "At the end of the day," / "It goes without saying,"
  "Needless to say," / "The bottom line is," / "When it comes to,"
  "Look," / "Listen," / "Now," (as filler opener)

  BANNED STRUCTURES:
  Do NOT open every section with a rhetorical question.
  Do NOT use "Whether you're a... or a..." sentence structure more than once.
  Do NOT stack three adjectives before a noun ("durable, lightweight, packable tent").
  Do NOT summarize what you just said at the end of every section.

  USE CONTRACTIONS: it's, you'll, we've, don't, that's — always.
  VARY SENTENCE LENGTH: mix short punchy sentences ("Impressive." "Skip it.")
    with longer explanatory ones. Never uniform paragraph length.
  WRITE IN FIRST PERSON: "I tested," "In my experience," "I've returned..."
  NEVER write "(AI Tested)" or any marker indicating AI authorship.
  NO PLACEHOLDERS: No image placeholders, no [INSERT X], nowhere.
  EXACT NUMBERS: Never round 1.87 lbs to "under 2 lbs." Use the actual spec.

SCANNABILITY:
  Mobile-first. Max 3 sentences per paragraph.
  All lists of 3+ items must use <ul><li>.
  Use <strong> for spec highlights within sentences.

OUTPUT: Pure HTML body only. No markdown. No code fences. No ```html wrappers.
Allowed tags: h1 h2 h3 p ul li b strong em table tr th td a small script
No html/head/body wrappers.
"""
    return prompt.strip()


def build_user_prompt(
    keyword: str,
    supporting_keywords: list,
    product_data: list,
    category: str = None,
) -> str:
    """
    글 1개 생성용 유저 프롬프트를 조립합니다.

    Args:
        keyword:             primary keyword
        supporting_keywords: 보조 키워드 리스트
        product_data:        상품 조사 결과 리스트
                             각 항목은 name/url/price/snippet/rating 필드 포함
        category:            카테고리 slug (None이면 ACTIVE_CATEGORY)

    Returns:
        Claude API messages[user] content 문자열
    """
    cfg = get_config(category)

    # product_data 필드명을 유연하게 처리 (title or name)
    products_str_lines = []
    for p in product_data:
        name    = p.get("name") or p.get("title") or "Unknown"
        price   = p.get("price") or "N/A"
        rating  = p.get("rating") or "N/A"
        reviews = p.get("review_count") or p.get("reviews") or "N/A"
        snippet = p.get("snippet") or ""
        products_str_lines.append(
            f"- {name} | Price: {price} | Rating: {rating} ({reviews} reviews)"
            + (f" | {snippet[:80]}" if snippet else "")
        )
    products_str = "\n".join(products_str_lines) if products_str_lines else "(no product data)"

    supporting_str = ", ".join(supporting_keywords) if supporting_keywords else "(none)"

    prompt = f"""Write a complete affiliate review post for the following:

PRIMARY KEYWORD: {keyword}
SUPPORTING KEYWORDS: {supporting_str}
CATEGORY: {cfg.name}
BLOGGER LABEL: {cfg.blogger_label}

PRODUCT DATA (use only these -- do not fabricate products):
{products_str}

INSTRUCTIONS:
1. Pick the top 3 products. Choose based on rating and review count.
2. Write each review in first person, as if you tested the product yourself.
3. Include real specs: weight, dimensions, materials, compatibility.
4. For cons: write the real weaknesses. Do not pad with fake praise.
5. Add a FOMO line to the #1 pick ONLY, and only if it fits naturally.
6. Buyer's Guide: explain 3 real technical criteria for {cfg.name}.
   Not generic. Specific to what matters in this category.
7. FAQ: address the 3 most common real questions buyers search on Google.
8. Price filter: skip any product outside ${cfg.min_price:.0f}-${cfg.max_price:.0f}.

TAGS (include in the META comment at the top):
{", ".join(cfg.tag_prefix)} + keyword-specific tags (5-8 total)

OUTPUT: Pure HTML body. No markdown. No code fences. No placeholders.
First line MUST be <!-- META: ... -->. Then <small>Last updated</small>. Then <h1>.
"""
    return prompt.strip()
