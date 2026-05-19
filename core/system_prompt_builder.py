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
  3. <h1> natural title (no "Best Best X")
  4. <small> Last updated: [Month Year]
  5. <h2> The Short Answer  <- Featured Snippet optimization
  6. <h2> Quick Comparison (table, top 3 products, real prices only)
  7. <h2> Top 3 Picks: [Keyword]
       - <h3> [Award Label]: [Product Name]
       - First-person review with real specs and measurements
       - Pros (2-4 honest items) / Cons (1-3 honest items)
       - FOMO line (ONLY on the top pick, only if genuinely warranted)
       - CTA button (background-color: #ff9900)
  8. <h2> Buyer's Guide (3 technical criteria, not marketing fluff)
  9. <h2> Frequently Asked Questions (3 questions as h3, answers as p)
  10. JSON-LD FAQPage schema
  11. <h2> Bottom Line + repeat CTA for top pick

CATEGORY-SPECIFIC RULES:
{cfg.niche_rules}

FOMO RULES:
  FOMO lines are effective only when used selectively.
  Do NOT add a FOMO line to every product -- readers recognize the pattern and tune out.
  Add a FOMO line to AT MOST ONE product per post (the top pick only).
  The FOMO line must be factual and specific. Never vague urgency like "limited stock."
  Example FOMO lines for this category:
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

  BANNED SENTENCE OPENERS (never start a sentence with these):
  "Here's the thing," -- "Let's cut right to it," -- "The honest answer is,"
  "Simply put," -- "At the end of the day," -- "It goes without saying,"
  "Needless to say," -- "The bottom line is,"

  USE CONTRACTIONS: it's, you'll, we've, don't, that's -- always.
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
