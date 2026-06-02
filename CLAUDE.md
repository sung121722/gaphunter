# GapHunter — Claude Code Context

@AGENTS.md

---

## Claude Code 전용 추가 설정

### 모델
- `config.CLAUDE_MODEL = "claude-sonnet-4-6"` (날짜 접미사 없음)
- 변경 시 `config.py`만 수정

### 작업 시작 전 체크
1. `py config.py` 로 API 키 로드 확인
2. `DRY_RUN_MODE` 값 확인 (`.env`)
3. `wiki/publish_log.json` 최근 발행 키워드 확인

### 커밋 규칙
```
feat(en): ...   # EN 포스트 생성/발행
feat(ko): ...   # KO 포스트 생성
fix: ...        # 버그 수정
chore: ...      # 설정/의존성 변경
```

---

## 현재 상태 (2026-06-02 업데이트)

- ✅ 전체 파이프라인 코드 완성
- ✅ LIVE 모드 실 API 연동
- ✅ gap_score 60+ 달성
- ✅ GitHub Actions 자동화 (daily.yml — 매일 10:17 / 22:17 KST)
- ✅ EN 키워드 64개로 확장 (기존 15개)
- ✅ AdSense 품질 기준 프롬프트 + 거버너 강화
- ✅ Amazon 스펙 테이블 크롤링 추가 (Material/Dimensions/Capacity)
- ✅ Google CSE 403 시 SerpAPI Amazon 엔진 폴백
- ✅ 어필리에이트 링크 검색URL → 실제 /dp/ URL 사용
- ⚠️ Google CSE 결제 계정 연결 완료 — 정상화 확인 필요
- ⚠️ SerpAPI Amazon 엔진 400 오류 (무료 플랜 미지원 가능성)
- ⚠️ Colab TimesFM 서버: ngrok URL 만료 시 수동 재시작 필요
- ❌ GSC 서비스 계정 미연동

---

## 상품 검색 흐름 (EN)

```
Google CSE (1순위)
    ↓ 실패(403) 시
SerpAPI Amazon 엔진 (2순위)
    ↓ 실패(400) 시
dummy 상품 → 거버너 HARD REJECT → 발행 안 됨
```

### Google CSE 403 원인 & 해결
| 원인 | 해결 |
|------|------|
| 결제 계정 미연결 | Google Cloud → 결제 → 결제 계정 연결 |
| API 키 IP/도메인 제한 | Cloud Console → 사용자 인증 정보 → 제한사항 없음으로 변경 |
| 일일 무료 한도(100회) 초과 | UTC 자정(KST 09:00) 후 리셋 |
| API 미활성화 | Cloud Console → API 및 서비스 → Custom Search API 활성화 |

### SerpAPI 400 원인
- Amazon 엔진은 **유료 플랜 필요** (무료 플랜 미지원)
- 대안: Amazon Product Advertising API (Associates 계정으로 무료)

---

## AdSense 품질 기준 (publish_governor.py)

| 항목 | 기준 | 미달 시 |
|------|------|---------|
| 단어수 | 1,500+ | HARD REJECT |
| H2 섹션 | 4개+ | HARD REJECT |
| H3 제품 섹션 | 3개+ | HARD REJECT |
| 어필리에이트 공시 | H1 앞 필수 | HARD REJECT |
| FAQ 스키마 | JSON-LD 필수 | HARD REJECT |
| dummy 상품 감지 | Product A/B/C 등 | HARD REJECT |
| em dash 본문 | 5개 이하 | HARD REJECT |
| 발행 간격 | 1시간+ | HARD REJECT |

---

## 포스트 HTML 필수 구조

```html
<!-- META: [155자 메타 디스크립션] -->
<p><em>This post contains affiliate links...</em></p>  ← H1 앞 필수
<h1>제목 (em dash 금지)</h1>
<p><small>Last updated: Month YYYY</small></p>
<h2>The Short Answer</h2>
<h2>Quick Comparison</h2>  ← 표: Product | Award | Price | Spec | Best For
<h2>Top Picks: [키워드]</h2>
  <h3>Best Overall: [제품명]</h3>
  <h3>Best Value/Budget/...: [제품명]</h3>
  <h3>Best Budget: [제품명]</h3>
<h2>What to Look for in [카테고리]</h2>
<h2>Frequently Asked Questions</h2>  ← 3개, 각 60단어+
<script type="application/ld+json">FAQPage 스키마</script>
<h2>Bottom Line</h2>
```

### 어필리에이트 링크 형식
```html
<a href="https://www.amazon.com/dp/ASIN" rel="nofollow sponsored">...</a>
```
- Claude는 `[AMAZON_LINK:제품명]` 플레이스홀더 사용
- 파이프라인이 실제 /dp/ URL로 자동 교체 (product_url_map 기반)
- Associates ID는 `AMAZON_ASSOCIATES_ID` 환경변수에서 로드

---

## GitHub Secrets 목록

| Secret | 용도 |
|--------|------|
| `ANTHROPIC_API_KEY` | Claude API |
| `GOOGLE_CSE_KEY` | Custom Search API 키 (결제 필요) |
| `GOOGLE_SEARCH_CX` | CSE ID (`01f61e948ed664e34`) |
| `SERPAPI_KEY` | Amazon 검색 폴백 (유료 플랜 시 작동) |
| `BLOGGER_BLOG_ID` | stuffnod 블로그 ID |
| `GOOGLE_REFRESH_TOKEN` | Blogger OAuth |
| `GOOGLE_CLIENT_ID` | Blogger OAuth |
| `GOOGLE_CLIENT_SECRET` | Blogger OAuth |
| `AMAZON_ASSOCIATES_ID` | 어필리에이트 태그 |
| `COLAB_PREDICTOR_URL` | TimesFM 예측 서버 (만료 주의) |

---

## 블로그 정보

- **URL**: https://stuffnod.blogspot.com/
- **Blog ID**: 722059588400237416 (BLOGGER_BLOG_ID Secret)
- **Google 계정**: sung121722@gmail.com
- **Blogger 표시명**: Live Better Daily
- **필수 페이지**: Privacy Policy ✅ / About ✅ / Contact ✅

### Blogger 주의사항
- 라벨 최대 8개 (초과 시 400 오류)
- `<script>`, HTML 주석 삽입 금지 (Blogger API 거부)
- URL은 최초 발행 시 확정 (제목 수정해도 URL 불변)
- 발행 날짜 보존 필요 시 pipeline 재실행 금지 → HTML 직접 수정

---

## 기존 포스트 수동 수정 시 체크리스트

Blogger → 글 편집 → **HTML 모드**에서:
1. 상단에 어필리에이트 공시 추가 (`<p><em>This post contains affiliate links...`)
2. dummy 제품(Product A/B/C) → 실제 Amazon 제품으로 교체
3. em dash(—) → 콜론(:) 또는 마침표로 교체
4. FAQ 섹션 + JSON-LD 스키마 추가
5. 실제 Amazon `/dp/ASIN` 링크 확인

---

## 코드 작성 규칙

- **Python**: `py` 명령 사용 (Windows), `python` 아님
- **HTML 파싱**: `BeautifulSoup(html, "html.parser")` — lxml 사용 금지
- **인코딩**: print 시 한글 포함되면 `.encode("ascii", errors="replace").decode()`
- **urllib3**: v2 호환 안 됨 → `"urllib3<2.0"` 유지
- **dotenv**: `load_dotenv(dotenv_path=Path(...) / ".env")` 명시 경로 필수
- **날짜**: `datetime.date.today()` 사용 (dayjs는 JS 전용)
- **임계값**: `config.GAP_SCORE_HIGH = 60` — 절대 낮추지 않음

---

## Vibe Coding 훅 (이 프로젝트 전용)

- **[3-STRIKE]** 같은 에러 3번 → 코딩 중단, 새 접근법 제안
- **[ZERO-TOUCH]** 파이프라인은 항상 headless 자동화 — UI 클릭 의존 설계 금지
- **[STRICT SEMANTICS]** HTML 생성 시 `<article>`, `<main>`, `<section>` 강제 사용
- **[STATE BEFORE UI]** 데이터 스키마·API 확정 전 UI 작업 금지
- **[AUTO-INGEST]** 기능 완료·버그 수정 후 → `wiki/` 또는 이 파일에 자동 문서화
- **[QUERY FIRST]** 새 코드 작성 전 `AGENTS.md` / `CLAUDE.md` / `wiki/` 먼저 읽기

---

## 금지 사항

- `.env` 파일 커밋 금지
- `lxml` 패키지 추가 금지 (Windows SmartScreen 차단, html.parser로 대체)
- `GAP_SCORE_HIGH` 값을 60 미만으로 수정 금지
- `DRY_RUN_MODE = true` 상태로 배포 금지
- Blogger API 토큰 하드코딩 금지
- API 키를 스크린샷에 노출하지 말 것 (노출 시 즉시 키 순환 필요)

---

## Colab 서버 재시작 순서 (ngrok URL 만료 시)

```
1. Colab 열기 → Cell 2 실행 → "Chronos model loaded." 확인
2. Cell 3 실행 → "Flask app defined." 확인
3. Cell 4: NGROK_AUTH_TOKEN = '3CW1zuL2mJMuAcnmYg11ABWzLN1_4M3g1zh4Ujwkp9nBhiUeY'
4. Cell 4 실행 → ngrok URL 복사
5. .env COLAB_PREDICTOR_URL 업데이트
6. Cell 5 실행 → forecast 숫자 출력 확인
```
