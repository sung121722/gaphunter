"""
category_config.py
──────────────────
GapHunter 카테고리 설정 단일 소스 (Single Source of Truth)

카테고리를 바꾸려면 ACTIVE_CATEGORY 값 하나만 수정하면 됩니다.
프롬프트, gap_score 가중치, fallback 키워드, 어필리에이트 구조가
모두 자동으로 바뀝니다.

사용 예:
    from category_config import get_config
    cfg = get_config()
    print(cfg.persona)
    print(cfg.gap_weights)
"""

from dataclasses import dataclass, field
from typing import Optional
import os

# ──────────────────────────────────────────────────────────────
# 여기 하나만 바꾸면 됩니다
# ──────────────────────────────────────────────────────────────
ACTIVE_CATEGORY: str = os.getenv("ACTIVE_CATEGORY", "camping")
# 환경변수로도 제어 가능: GitHub Secrets에 ACTIVE_CATEGORY 추가

# 지원 카테고리 목록
# "camping" | "kitchen" | "pet" | "home_office" | "fitness"
# ──────────────────────────────────────────────────────────────


@dataclass
class GapWeights:
    """Gap Score 가중치. 합계가 반드시 1.0이어야 합니다."""
    demand_growth:    float  # 수요 증가율
    decay_prob:       float  # 트렌드 소멸 확률 (계절성 높을수록 높게)
    competition_gap:  float  # 경쟁 강도 역수
    timing_advantage: float  # 발행 타이밍 우위

    def __post_init__(self):
        total = (self.demand_growth + self.decay_prob
                 + self.competition_gap + self.timing_advantage)
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"GapWeights 합계가 1.0이어야 합니다. 현재: {total:.3f}")


@dataclass
class AffiliateConfig:
    """어필리에이트 링크 구성"""
    platform:         str            # "amazon" | "cj" | "shareasale"
    associates_id:    str            # 환경변수 키 이름
    amazon_category:  Optional[str]  # Amazon 카테고리 노드 (amazon일 때만)
    base_url:         str            # 링크 베이스 URL
    cookie_days:      int            # 어필리에이트 쿠키 유효기간 (일)
    avg_commission:   float          # 평균 커미션율 (%)


@dataclass
class CategoryConfig:
    """카테고리 전체 설정"""
    name:             str              # 카테고리 표시명
    slug:             str              # 카테고리 식별자
    blogger_label:    str              # Blogger 라벨
    persona:          str              # 시스템 프롬프트에 삽입되는 페르소나
    niche_rules:      str              # 카테고리별 추가 규칙 (프롬프트 삽입용)
    fomo_triggers:    list             # FOMO 문구 풀 (랜덤 선택)
    gap_weights:      GapWeights       # Gap Score 가중치
    affiliate:        AffiliateConfig  # 어필리에이트 설정
    fallback_keywords: list            # 에버그린 fallback 키워드
    banned_words_extra: list           # 카테고리별 추가 금지어 (공통 금지어에 추가)
    image_style:      str              # Unsplash 이미지 쿼리 스타일 힌트
    min_price:        float            # 리뷰 대상 최소 가격 ($)
    max_price:        float            # 리뷰 대상 최대 가격 ($)
    tag_prefix:       list             # Blogger 태그 공통 접두사


# ══════════════════════════════════════════════════════════════
# 카테고리 정의
# ══════════════════════════════════════════════════════════════

CATEGORIES: dict = {

    # ──────────────────────────────────────────────────────────
    # 1. 캠핑 / 아웃도어 (현재 운영 중)
    # ──────────────────────────────────────────────────────────
    "camping": CategoryConfig(
        name="Camping & Outdoor Gear",
        slug="camping",
        blogger_label="Camping Gear",
        persona=(
            "You are a veteran backpacker with 15 years of trail experience "
            "across the Appalachians, Pacific Crest Trail, and Rockies. "
            "You've returned gear that failed you and know what holds up. "
            "You write for people who actually sleep outside, not glampers."
        ),
        niche_rules=(
            "WEIGHT RULE: Ultralight keyword -> reject any product over 2 lbs. "
            "Backpacking keyword -> reject anything over 4 lbs. "
            "SEASON RULE: If review window is Oct-Feb, prioritize cold-weather gear. "
            "DURABILITY: Always mention material (e.g., 20D ripstop nylon) and "
            "real-world conditions tested (rain, cold, wind). "
            "AVOID: Gear you wouldn't take on a 3-day solo trip."
        ),
        fomo_triggers=[
            "This model sells out every spring. Stock tends to drop in March.",
            "Sale pricing on this tends to spike in peak season. Right now it's reasonable.",
            "The 2026 version fixed the zipper issue people complained about last year.",
            "This one consistently sells out before major holiday weekends.",
        ],
        gap_weights=GapWeights(
            demand_growth=0.35,    # 계절 수요 변동 중요
            decay_prob=0.35,       # 트렌드 소멸 빠름 (계절성)
            competition_gap=0.20,
            timing_advantage=0.10,
        ),
        affiliate=AffiliateConfig(
            platform="amazon",
            associates_id="AMAZON_ASSOCIATES_ID",
            amazon_category="Camping & Hiking",
            base_url="https://www.amazon.com/dp/",
            cookie_days=24,
            avg_commission=3.0,
        ),
        fallback_keywords=[
            "best ultralight backpacking tent",
            "best sleeping bag for cold weather camping",
            "best camping cookware set",
            "best headlamp for backpacking",
            "best trekking poles for hiking",
            "best bear canister for backpacking",
            "best camp chair lightweight",
            "best water filter for camping",
            "best camping lantern",
            "best hiking boots waterproof",
            "best rain jacket for hiking",
            "best backpack 65 liter",
            "best camping hammock",
            "best camp stove for backpacking",
            "best sleeping pad for backpacking",
        ],
        banned_words_extra=["glamping", "resort", "luxury camping"],
        image_style="realistic outdoor gear trail campsite",
        min_price=15.0,
        max_price=600.0,
        tag_prefix=["camping", "outdoor", "backpacking", "hiking", "gear"],
    ),

    # ──────────────────────────────────────────────────────────
    # 2. 주방 / 요리 도구
    # ──────────────────────────────────────────────────────────
    "kitchen": CategoryConfig(
        name="Kitchen & Cooking",
        slug="kitchen",
        blogger_label="Kitchen Gear",
        persona=(
            "You are a home cook who has been cooking seriously for 20 years "
            "and has burned through enough cheap equipment to know what lasts. "
            "You write for people who cook real meals, not for Instagram. "
            "You care about performance, durability, and value -- not brand names."
        ),
        niche_rules=(
            "PERFORMANCE RULE: Always mention heat distribution, material "
            "(e.g., tri-ply stainless, hard-anodized aluminum), and what "
            "it actually cooked well or poorly. "
            "DISHWASHER RULE: Always state dishwasher-safe or hand-wash only. "
            "PRICE-TO-VALUE: Flag clearly when a $30 option beats a $120 one. "
            "AVOID: Products with less than 500 Amazon reviews unless very new."
        ),
        fomo_triggers=[
            "This is one of those products that goes on sale exactly twice a year.",
            "The 2026 version added induction compatibility -- big upgrade.",
            "This consistently sells out around major cooking holidays.",
            "Prices on cast iron have been creeping up the past two quarters.",
        ],
        gap_weights=GapWeights(
            demand_growth=0.30,
            decay_prob=0.20,       # 계절성 낮음 (요리는 연중)
            competition_gap=0.35,  # 경쟁 치열 -- gap이 중요
            timing_advantage=0.15,
        ),
        affiliate=AffiliateConfig(
            platform="amazon",
            associates_id="AMAZON_ASSOCIATES_ID",
            amazon_category="Kitchen & Dining",
            base_url="https://www.amazon.com/dp/",
            cookie_days=24,
            avg_commission=4.5,
        ),
        fallback_keywords=[
            "best cast iron skillet",
            "best chef knife under 100",
            "best Dutch oven for bread baking",
            "best air fryer for family",
            "best stand mixer for home baking",
            "best stainless steel cookware set",
            "best carbon steel wok",
            "best instant pot size for family",
            "best immersion blender",
            "best cutting board wood",
            "best sheet pan for roasting",
            "best nonstick pan without PFAS",
            "best food processor compact",
            "best kitchen scale for baking",
            "best mandoline slicer safe",
        ],
        banned_words_extra=["foodie", "culinary journey", "gastronomic"],
        image_style="realistic home kitchen cookware cooking",
        min_price=10.0,
        max_price=500.0,
        tag_prefix=["kitchen", "cooking", "cookware", "home cook", "baking"],
    ),

    # ──────────────────────────────────────────────────────────
    # 3. 반려동물
    # ──────────────────────────────────────────────────────────
    "pet": CategoryConfig(
        name="Pet Supplies",
        slug="pet",
        blogger_label="Pet Gear",
        persona=(
            "You are a longtime dog owner (two labs, one rescue mutt) who has "
            "spent more money on pet gear than you'd like to admit. "
            "You write for pet owners who want honest answers, not affiliate fluff. "
            "You've returned products that your dog destroyed in 48 hours "
            "and found the ones that actually survive real dogs."
        ),
        niche_rules=(
            "SAFETY FIRST: Always flag choking hazards, toxic materials, "
            "or products with safety recalls in the past 2 years. "
            "SIZE SPECIFICITY: Always state which dog size the review applies to. "
            "DURABILITY TEST: State how long the product lasted with actual use. "
            "VET CONTEXT: For health products, note 'consult your vet' once. "
            "AVOID: Products with fewer than 200 reviews."
        ),
        fomo_triggers=[
            "This tends to go out of stock during peak adoption seasons (spring, holidays).",
            "The 2026 version has a sturdier strap -- previous version snapped.",
            "This is one of the few products my dogs haven't destroyed in a week.",
            "Prices on durable dog gear have been rising -- this is still reasonable.",
        ],
        gap_weights=GapWeights(
            demand_growth=0.30,
            decay_prob=0.20,
            competition_gap=0.25,
            timing_advantage=0.25,  # 반려동물은 구매 타이밍 민감 (입양 시즌 등)
        ),
        affiliate=AffiliateConfig(
            platform="amazon",
            associates_id="AMAZON_ASSOCIATES_ID",
            amazon_category="Pet Supplies",
            base_url="https://www.amazon.com/dp/",
            cookie_days=24,
            avg_commission=3.0,
        ),
        fallback_keywords=[
            "best indestructible dog toys for aggressive chewers",
            "best dog harness no pull large breed",
            "best dog crate for separation anxiety",
            "best dog food for sensitive stomach",
            "best automatic dog feeder",
            "best dog leash hands free running",
            "best dog water bottle portable",
            "best dog bed for large dogs",
            "best cat litter for odor control",
            "best cat scratching post tall",
            "best pet camera treat dispenser",
            "best dog shampoo for allergies",
            "best flea treatment for dogs",
            "best dog nail grinder quiet",
            "best dog puzzle toy",
        ],
        banned_words_extra=["fur baby", "pawsome", "paw-fect", "doggos"],
        image_style="realistic dog owner pet gear outdoor",
        min_price=8.0,
        max_price=300.0,
        tag_prefix=["pet", "dog", "cat", "pet supplies", "pet gear"],
    ),

    # ──────────────────────────────────────────────────────────
    # 4. 홈 오피스
    # ──────────────────────────────────────────────────────────
    "home_office": CategoryConfig(
        name="Home Office & Productivity",
        slug="home_office",
        blogger_label="Home Office",
        persona=(
            "You have worked remotely for 8 years and have turned your home "
            "office setup into a genuine productivity system. "
            "You've bought and returned enough monitors, chairs, and keyboards "
            "to know what the specs don't tell you. "
            "You write for people who work from home seriously -- not occasionally."
        ),
        niche_rules=(
            "ERGONOMICS: Always mention lumbar support, monitor height, "
            "and wrist position where relevant. "
            "COMPATIBILITY: Always state OS compatibility (Mac/Windows/Linux). "
            "CONNECTIVITY: List ports and wireless standards (USB-C, Bluetooth version). "
            "NOISE: For any audio product, always address background noise in calls. "
            "AVOID: Products that require proprietary software to function."
        ),
        fomo_triggers=[
            "This model is often backordered 3-4 weeks around back-to-school season.",
            "The 2026 refresh added USB-C -- the old version is being discounted now.",
            "Standing desk prices have dropped significantly -- this is near a 2-year low.",
            "Webcam stock tightens every fall. Right now there's good availability.",
        ],
        gap_weights=GapWeights(
            demand_growth=0.40,    # 재택근무 수요 꾸준한 성장
            decay_prob=0.15,       # 계절성 거의 없음
            competition_gap=0.30,  # 경쟁 치열한 카테고리
            timing_advantage=0.15,
        ),
        affiliate=AffiliateConfig(
            platform="amazon",
            associates_id="AMAZON_ASSOCIATES_ID",
            amazon_category="Office Products",
            base_url="https://www.amazon.com/dp/",
            cookie_days=24,
            avg_commission=4.0,
        ),
        fallback_keywords=[
            "best monitor for home office dual setup",
            "best ergonomic office chair under 500",
            "best standing desk for home office",
            "best mechanical keyboard for programming",
            "best webcam for remote work 1080p",
            "best microphone for video calls",
            "best monitor arm adjustable",
            "best laptop stand for desk",
            "best USB hub for MacBook",
            "best noise canceling headphones for work",
            "best desk mat large",
            "best LED desk lamp with USB",
            "best wireless mouse ergonomic",
            "best under desk drawer organizer",
            "best cable management box",
        ],
        banned_words_extra=["hustle", "grind", "productivity hack", "game-changing setup"],
        image_style="realistic clean home office desk setup",
        min_price=15.0,
        max_price=800.0,
        tag_prefix=["home office", "remote work", "productivity", "desk setup", "WFH"],
    ),

    # ──────────────────────────────────────────────────────────
    # 5. 피트니스 / 홈짐
    # ──────────────────────────────────────────────────────────
    "fitness": CategoryConfig(
        name="Fitness & Home Gym",
        slug="fitness",
        blogger_label="Fitness Gear",
        persona=(
            "You have been training consistently for 12 years -- "
            "gym, home, and everything in between. "
            "You've watched the home gym market explode and know which products "
            "survive actual training and which ones belong in a garage sale. "
            "You write for people who train seriously, not people who buy equipment "
            "to feel like they train."
        ),
        niche_rules=(
            "SPACE RULE: Always state footprint dimensions. Small apartments matter. "
            "WEIGHT CAPACITY: Always state max weight capacity. "
            "NOISE RULE: For apartment training, flag noise and floor impact. "
            "PROGRESSION: Mention whether the product allows load progression. "
            "AVOID: Products with safety concerns or poor welding quality reviews."
        ),
        fomo_triggers=[
            "Home gym equipment spiked in price after 2024 -- this is back near MSRP.",
            "Dumbbells and kettlebells tend to sell out in January every year.",
            "This model has had consistent stock since the supply chain stabilized.",
            "Used market for this is thin -- new pricing is actually fair right now.",
        ],
        gap_weights=GapWeights(
            demand_growth=0.35,
            decay_prob=0.25,       # 1월 신년 효과 등 계절성 중간
            competition_gap=0.25,
            timing_advantage=0.15,
        ),
        affiliate=AffiliateConfig(
            platform="amazon",
            associates_id="AMAZON_ASSOCIATES_ID",
            amazon_category="Sports & Outdoors",
            base_url="https://www.amazon.com/dp/",
            cookie_days=24,
            avg_commission=3.0,
        ),
        fallback_keywords=[
            "best adjustable dumbbells for home gym",
            "best pull up bar doorframe",
            "best resistance bands set heavy",
            "best kettlebell for beginners",
            "best yoga mat thick non-slip",
            "best foam roller for recovery",
            "best jump rope for fitness",
            "best ab roller core workout",
            "best squat rack for home gym",
            "best treadmill for small apartment",
            "best battle rope for home workout",
            "best weight bench adjustable",
            "best barbell set for home gym",
            "best gym flooring rubber tiles",
            "best pull up dip station",
        ],
        banned_words_extra=["gains", "swole", "beast mode", "shredded", "ripped"],
        image_style="realistic home gym equipment training",
        min_price=10.0,
        max_price=700.0,
        tag_prefix=["fitness", "home gym", "workout", "exercise equipment", "training"],
    ),
}


# ══════════════════════════════════════════════════════════════
# 공통 금지어 (모든 카테고리에 적용)
# ══════════════════════════════════════════════════════════════
BANNED_WORDS_COMMON: list = [
    "comprehensive", "delve", "tapestry", "seamlessly", "furthermore",
    "in conclusion", "it's worth noting", "game-changer", "leverage",
    "utilize", "paradigm", "synergy", "robust", "boasts", "testament",
    "meticulous", "stands out", "look no further", "holistic",
    "transformative", "innovative", "cutting-edge", "best practices",
    "going forward", "at the end of the day", "needless to say",
    "it goes without saying", "the bottom line is",
]


# ══════════════════════════════════════════════════════════════
# 공개 인터페이스
# ══════════════════════════════════════════════════════════════

def get_config(category: str = None) -> CategoryConfig:
    """
    활성 카테고리 설정을 반환합니다.

    Args:
        category: 카테고리 slug. None이면 ACTIVE_CATEGORY 사용.

    Returns:
        CategoryConfig 인스턴스

    Raises:
        ValueError: 지원하지 않는 카테고리
    """
    slug = category or ACTIVE_CATEGORY
    if slug not in CATEGORIES:
        available = ", ".join(CATEGORIES.keys())
        raise ValueError(
            f"지원하지 않는 카테고리: '{slug}'. "
            f"사용 가능: {available}"
        )
    return CATEGORIES[slug]


def get_banned_words(category: str = None) -> list:
    """공통 금지어 + 카테고리별 금지어 합친 리스트 반환"""
    cfg = get_config(category)
    return BANNED_WORDS_COMMON + cfg.banned_words_extra


def list_categories() -> list:
    """지원 카테고리 목록 반환"""
    return list(CATEGORIES.keys())
