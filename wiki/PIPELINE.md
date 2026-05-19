# GapHunter — 파이프라인 & 프롬프트 문서

> 최종 업데이트: 2026-05-19

---

## 1. 전체 구조

```
[GitHub Actions] 하루 2회 자동 실행 (10:17 KST / 22:17 KST)
        ↓
  run_en.py (오케스트레이터)
        ↓
  ┌─────────────────────────────────────────────────────┐
  │  1. keyword_scheduler  → 트렌드 키워드 5개 후보     │
  │  2. collector          → pytrends + SerpAPI 수집    │
  │  3. predictor          → 수요/decay 예측            │
  │  4. scorer             → gap_score 계산             │
  │  5. generator          → Claude API 글 생성         │
  │  6. publisher          → Blogger API 발행           │
  └─────────────────────────────────────────────────────┘
        ↓
  stuffnod.blogspot.com 공개 발행
```

---

## 2. 단계별 상세

### Step 1. 키워드 선택 (`keyword_scheduler.py`)
- pytrends로 캠핑/아웃도어 트렌드 상위 5개 키워드 후보 추출
- 14일 이내 발행된 키워드는 자동 제외 (중복 방지)
- `gap_score >= 55` → 정상 발행
- `gap_score < 55` → `fallback_keywords_en.txt`에서 랜덤 에버그린 키워드 선택 (스킵 없음)

### Step 2. 데이터 수집 (`collector.py`)
- pytrends: 52주 검색량 트렌드
- SerpAPI: SERP 상위 10개 경쟁자 URL
- BeautifulSoup: 경쟁자 페이지 크롤링 (단어수, 업데이트일 파악)
- GSC: 미연동 (서비스 계정 없음)

### Step 3. 수요 예측 (`predictor.py`)
- 기본: 선형회귀 (항상 작동)
- 보조: Colab TimesFM (ngrok URL 필요 — 현재 만료 상태)

### Step 4. Gap Score 계산 (`scorer.py`)

```
gap_score = demand_growth(×0.4) + decay_prob(×0.3)
          + competition_gap(×0.2) + timing_advantage(×0.1)
```

| 구간 | 의미 |
|------|------|
| 80+ | GENERATE_NOW |
| 60~79 | GENERATE_SOON |
| 55~59 | 발행 (MIN_SCORE) |
| 0~54 | Fallback 키워드 사용 |

### Step 5. 글 생성 (`generator.py`)

**상품 조사 흐름:**
```
SerpAPI Google Shopping API
  → Amazon 리스팅에서 실제 가격·별점·리뷰수 수집
  → 결과 부족 시 organic 검색 폴백
  → 가격 없는 제품만 Amazon 페이지 직접 크롤링 보완
```

**글 생성:**
- Claude API (`claude-sonnet-4-6`) 호출
- SYSTEM_PROMPT + 상품 데이터 → HTML 포스트 생성
- `[AMAZON_LINK:제품명]` → 실제 어필리에이트 링크로 자동 교체

### Step 6. 발행 (`publisher.py`)

**발행 전 체크리스트:**
| 항목 | 기준 |
|------|------|
| 마크다운 헤더 없음 | `#` 발견 시 차단 |
| 글 길이 | 300단어 이상 |
| 플레이스홀더 없음 | `[AMAZON_LINK:xxx]` 미교체 시 차단 |
| 태그 수 | 5개 이상 |

**Blogger API:**
- Google OAuth2 refresh token 방식
- script 태그·HTML 주석 자동 제거 (Blogger 거부 방지)
- 라벨(태그) 최대 8개
- 일일 한도: 3개/일

---

## 3. 타이틀 생성 규칙

```python
# keyword에 "best"가 이미 있으면 중복 방지
if keyword.startswith("best "):
    title = f"{keyword.title()} - Tested & Reviewed 2026"
else:
    title = f"Best {keyword.title()} - Tested & Reviewed 2026"
```

---

## 4. 발행 스케줄

| 회차 | UTC | KST |
|------|-----|-----|
| 1회차 | 01:17 | 10:17 |
| 2회차 | 13:17 | 22:17 |

---

## 5. SYSTEM_PROMPT (EN — 현재 적용 버전)

```
You are an expert outdoor gear reviewer and professional SEO copywriter.
Write highly converting, trustworthy, and natural affiliate blog posts
for an outdoor/camping gear audience.

HEADING HIERARCHY:
  h1 → page title (once)
  h2 → major section headings
  h3 → individual product names only

REQUIRED POST STRUCTURE:
  1. <!-- META: ... -->  (155자 이내, 키워드 자연스럽게 포함)
  2. Affiliate Disclosure
  3. <h1> 자연스러운 제목 (Best Best X 금지)
  4. <small> Last updated
  5. <h2> The Short Answer  ← Featured Snippet 최적화
  6. <h2> Quick Comparison (table, 실제 가격 기재)
  7. <h2> Top 3 Picks
       └─ <h3> [Award Label]: [Product Name]
       └─ 리뷰 (First-person, 실수치 포함)
       └─ 장점 3개 / 단점 1개 (정확한 결함 명시)
       └─ 🔥 FOMO 빨간줄
       └─ 🛒 주황 CTA 버튼 (#ff9900)
  8. <h2> Buyer's Guide (3가지 기술적 기준)
  9. <h2> FAQ (h3 질문 × 3)
  10. JSON-LD FAQPage 스키마
  11. <h2> Bottom Line + CTA 반복  ← 마지막 구매 유도

STRICT RULES:
  - NO PLACEHOLDERS (이미지 플레이스홀더 금지)
  - NO AI ARTIFACTS ((AI Tested) 등 금지)
  - PRICE ACCURACY: 제공된 실제 가격 그대로 사용
  - FOMO: 모든 제품에 필수
  - CTA: 모든 제품에 필수
  - NICHE MATCHING: ultralight → 2lbs 초과 제품 금지
  - KEYWORD NATURALNESS: 자연스럽게 통합

BANNED WORDS:
  comprehensive, delve, tapestry, seamlessly, furthermore,
  in conclusion, it's worth noting, game-changer, leverage,
  utilize, paradigm, synergy, robust, boasts, testament,
  meticulous, stands out, look no further, holistic

OUTPUT: Pure HTML body only. No markdown. No code fences.
```

---

## 6. 주요 파일

```
gaphunter/
├── scripts/run_en.py              ← 오케스트레이터 (유일한 파이프라인)
├── core/
│   ├── keyword_scheduler.py       ← 키워드 선택 + 중복 방지
│   ├── collector.py               ← 데이터 수집
│   ├── predictor.py               ← 수요 예측
│   ├── scorer.py                  ← gap_score 계산
│   ├── generator.py               ← Claude API 글 생성 + 상품 조사
│   └── publisher.py               ← Blogger API 발행
├── fallback_keywords_en.txt       ← 에버그린 키워드 50개
├── wiki/publish_log.json          ← 발행 이력 (14일 중복 방지)
└── .github/workflows/daily.yml   ← GitHub Actions 스케줄
```

---

## 7. 환경변수 (GitHub Secrets)

| 변수 | 용도 |
|------|------|
| `ANTHROPIC_API_KEY` | Claude API |
| `SERPAPI_KEY` | 키워드 수집 + 상품 조사 |
| `AMAZON_ASSOCIATES_ID` | 어필리에이트 링크 |
| `BLOGGER_BLOG_ID` | stuffnod.blogspot.com ID |
| `GOOGLE_REFRESH_TOKEN` | Blogger OAuth |
| `GOOGLE_CLIENT_ID` | Blogger OAuth |
| `GOOGLE_CLIENT_SECRET` | Blogger OAuth |
| `COLAB_PREDICTOR_URL` | TimesFM (현재 만료) |

---

## 8. 현재 상태 (2026-05-19)

| 항목 | 상태 |
|------|------|
| EN 파이프라인 | ✅ 정상 (하루 2회) |
| KO 파이프라인 | ❌ 비활성화 |
| Google Shopping 가격 | ✅ 실제 가격 수집 |
| Blogger 자동 발행 | ✅ 정상 |
| Colab TimesFM | ⚠️ ngrok 만료 (선형회귀 폴백) |
| GSC 연동 | ❌ 미연동 |
| 발행 글 수 | 21개 |
