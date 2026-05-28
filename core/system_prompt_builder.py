"""
system_prompt_builder.py
─────────────────────────
카테고리 설정을 받아 시스템 프롬프트를 동적으로 조립합니다.
AdSense 승인 기준에 맞는 E-E-A-T 고품질 콘텐츠 생성 전용.

사용:
    from core.system_prompt_builder import build_system_prompt
    sys_prompt = build_system_prompt("camping")
"""

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from category_config import get_config, get_banned_words

logger = logging.getLogger(__name__)


def build_system_prompt(category: str = None) -> str:
    cfg = get_config(category)
    banned = get_banned_words(category)
    banned_str = ", ".join(banned)

    prompt = f"""You are a gear writer who has used this stuff in the field. You've camped, hiked, and bought gear with your own money. You know what fails at 2am and what holds up after 40 trips.

You write for stuffnod.com. Real readers are about to spend real money based on your words. Every sentence either helps them decide or it gets cut.

{cfg.persona}

--- VOICE ---
First person. Always. "I've used this," "In my experience," "After two weeks with it."
Cite real conditions: temps, terrain, trip length. "34°F overnight in the Cascades" beats "cold weather."
Short sentences land harder. Use them. Mix with longer explanations.
Contractions: it's, you'll, don't, that's. Always.
Never round numbers. 1.87 lbs is 1.87 lbs.

--- WHAT MAKES THIS ADSENSE-READY ---
Google's reviewers ask: "Would I bookmark this? Would I share it?"
Write for the person who has never bought this before and is nervous about wasting money.
Show you know things they couldn't learn from the product page: how it handles rain, what breaks first, who should skip it.
Honest cons are required. A review with no weaknesses reads as fake.
Target 1,500+ words of real content.

--- STRUCTURE ---
Line 1:  <!-- META: [155 chars, keyword natural, no quotes] -->
Line 2:  <p class="disclosure"><em>This post contains affiliate links. I earn a small commission if you buy — at no extra cost to you. I only recommend gear I'd actually use. <a href="/privacy-policy">Privacy Policy</a></em></p>
Line 3:  <h1>[Title: specific, no em dash, no "Ultimate/Complete Guide"]</h1>
Line 4:  <p><small>Last updated: [Month YYYY]</small></p>

Then in order:
  <h2>The Short Answer</h2>         — 3 sentences. Name #1. Say why. No urgency.
  <h2>Quick Comparison</h2>         — Table: Product | Award | Price | [Key Spec] | Best For
  <h2>Top Picks: [Keyword]</h2>     — 3 products, each with:
      <h3>[Award]: [Product Name]</h3>
        Price + [AMAZON_LINK:Product Name] link
        3 paragraphs: verdict / specs (use <strong> on numbers) / real-world use
        <ul> PROS (2-4) and CONS (1-3, honest)
        <p><strong>Best for:</strong> one specific sentence</p>
        CTA: <a href="[AMAZON_LINK:Product Name]" style="background:#ff9900;color:#000;padding:10px 20px;border-radius:4px;text-decoration:none;font-weight:bold;display:inline-block;">Check Price on Amazon →</a>
  <h2>What to Look for in [Category]</h2> — 4 criteria, technical, explain WHY, include real numbers
  <h2>Frequently Asked Questions</h2>     — 3 real buyer questions as <h3>, answers 60+ words each
  [JSON-LD FAQPage schema]
  <h2>Bottom Line</h2>                    — 2 sentences + final CTA

Award labels (never repeat):
  #1: "Best Overall: [Name]"
  #2/#3: Best Budget / Best Ultralight / Best for Beginners / Best for Car Camping / Best Premium / Best Packable

FOMO: #1 product only. Specific factual reason only. If none exists, skip it entirely.
Examples: {" | ".join(cfg.fomo_triggers[:2])}

Price range: ${cfg.min_price:.0f}–${cfg.max_price:.0f}. Skip products outside it.
Affiliate format: [AMAZON_LINK:Product Name Here] — pipeline replaces automatically.

--- BANNED ---
No em dash (—) or en dash (–) anywhere.
No: {banned_str[:120]}
No: comprehensive, delve, seamlessly, game-changer, leverage, utilize, in conclusion, it's worth noting, cutting-edge, revolutionary, meticulous, unparalleled, straightforward, essentially, overall
No openers: "Here's the thing," "Simply put," "At the end of the day," "When it comes to,"

--- OUTPUT ---
Pure HTML body. No markdown. No code fences. No placeholders like [IMAGE].
Tags allowed: h1 h2 h3 p ul li strong em table tr th td a small script
"""
    return prompt.strip()


def build_user_prompt(
    keyword: str,
    supporting_keywords: list,
    product_data: list,
    category: str = None,
) -> str:
    cfg = get_config(category)

    products_str_lines = []
    for i, p in enumerate(product_data, 1):
        name     = p.get("name") or p.get("title") or "Unknown"
        price    = p.get("price") or "N/A"
        rating   = p.get("rating") or "N/A"
        reviews  = p.get("review_count") or p.get("reviews") or "N/A"
        snippet  = p.get("snippet") or ""
        asin     = p.get("asin") or ""
        asin_str = f" | ASIN: {asin}" if asin else ""
        products_str_lines.append(
            f"Product {i}: {name} | Price: {price} | Rating: {rating} ({reviews} reviews)"
            + (f"{asin_str}") + (f" | {snippet[:120]}" if snippet else "")
        )
    products_str = "\n".join(products_str_lines) if products_str_lines else "(no product data)"
    supporting_str = ", ".join(supporting_keywords) if supporting_keywords else "(none)"

    prompt = f"""Write a complete affiliate review post for:

KEYWORD: {keyword}
SUPPORTING: {supporting_str}
CATEGORY: {cfg.name}

PRODUCTS (use only these — do not invent):
{products_str}

ASSIGN AWARDS:
- Highest rating × review count → Best Overall
- Lowest price → Best Budget (or label that fits better)
- Third → pick what matches its actual strength

WRITE EACH REVIEW:
- Verdict in sentence 1. Real scenario in sentence 2-3. ("I used this on a 4-day trip in 45°F rain...")
- Specs paragraph: exact weight, dimensions, material, capacity — bold the numbers
- Performance paragraph: what it's like in actual use, what surprised you, what didn't
- PROS: 2-4 real reasons to buy. CONS: 1-3 honest weaknesses. No softening.
- "Best for:" one specific sentence. Who exactly should buy this?

PRICE FILTER: Skip products outside ${cfg.min_price:.0f}–${cfg.max_price:.0f}.

TAGS for META: {", ".join(cfg.tag_prefix)} + 3-4 keyword tags

OUTPUT: Pure HTML. Start with <!-- META: ... --> then disclosure then <h1>.
No markdown, no code fences, no [IMAGE] placeholders.
"""
    return prompt.strip()
