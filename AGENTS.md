# GapHunter — Agent Instructions

> 이 파일은 모든 AI 코딩 도구(Claude Code, Cursor, Codex, Gemini CLI 등)의
> 공통 컨텍스트입니다. CLAUDE.md는 이 파일을 참조합니다.

---

## 프로젝트 요약

SEO 갭 예측 자동화 시스템. 경쟁자 콘텐츠가 죽어가는 타이밍을 예측해 자동으로 포스트 생성.

- **블로그 (EN)**: https://stuffnod.blogspot.com/ — 아웃도어 용품 리뷰
- **블로그 (KO)**: https://sung1216.tistory.com/ — 건강식품 / 라이프스타일
- **수익화**: Amazon Associates (EN) / 쿠팡 파트너스 AF6344014 (KO)

---

## 파이프라인

```
collector.py → predictor.py → scorer.py → generator.py → 블로그 발행
```

| 단계 | 파일 | 역할 |
|------|------|------|
| 1 | `core/collector.py` | pytrends + SerpAPI + BeautifulSoup 크롤링 |
| 2 | `core/predictor.py` | 선형회귀 / Colab TimesFM 수요 예측 |
| 3 | `core/scorer.py` | gap_score 0~100 계산 |
| 4 | `core/generator.py` | Claude API 콘텐츠 생성 |
| 5 | `core/publisher.py` | Blogger API 자동 발행 |

---

## Gap Score 공식

```
gap_score = demand_growth(0.4) + decay_prob(0.3)
          + competition_gap(0.2) + timing_advantage(0.1)
```

| 구간 | 액션 |
|------|------|
| 80+ | GENERATE_NOW |
| 60~79 | GENERATE_SOON — 발행 기준 (MIN_SCORE) |
| 40~59 | QUEUE |
| 0~39 | MONITOR |

**임계값(GAP_SCORE_HIGH=60)은 절대 낮추지 않는다.**
빈자리가 없으면 그날 스킵하고 내일 다시 확인한다.

---

## 디렉토리 구조

```
J:/gaphunter/
├── AGENTS.md              # 공통 에이전트 컨텍스트 (이 파일)
├── CLAUDE.md              # Claude Code 전용 → @AGENTS.md 참조
├── config.py              # 전체 설정, API 키 로드
├── main.py                # CLI 진입점
├── keywords.json          # 롱테일 키워드 목록 (EN/KO)
├── .env                   # API 키 (git 제외)
├── core/
│   ├── collector.py       # 데이터 수집
│   ├── predictor.py       # 수요/decay 예측
│   ├── scorer.py          # gap_score 계산
│   ├── generator.py       # Claude API 포스트 생성
│   ├── publisher.py       # Blogger 발행
│   └── keyword_scheduler.py  # pytrends 기반 키워드 선택
├── scripts/
│   ├── run_en.py          # EN 파이프라인 (GitHub Actions)
│   └── run_ko.py          # KO 파이프라인 (이메일 알림)
├── .github/workflows/
│   └── daily.yml          # 매일 01:17 UTC 자동 실행
├── wiki/
│   └── publish_log.json   # 발행 이력 (14일 중복 방지)
├── posts/                 # 생성된 HTML 포스트
└── raw/                   # pytrends 수집 JSON + SQLite
```

---

## 자주 쓰는 명령어

```bash
# Windows: python 대신 py 사용
py main.py "camping chairs" --lang en
py scripts/run_en.py          # EN 파이프라인 수동 실행
py scripts/run_ko.py          # KO 파이프라인 수동 실행
py publish_now.py             # 최신 EN 포스트 즉시 발행
py publish_now.py posts/xxx.html   # 특정 포스트 발행
py config.py                  # 설정 확인
```

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

## 금지 사항

- `.env` 파일 커밋 금지
- `lxml` 패키지 추가 금지 (Windows SmartScreen 차단, html.parser로 대체)
- `GAP_SCORE_HIGH` 값을 60 미만으로 수정 금지
- `DRY_RUN_MODE = true` 상태로 배포 금지
- Blogger API 토큰 하드코딩 금지

---

## 현재 상태 (2026-04-27)

- ✅ 전체 파이프라인 코드 완성
- ✅ LIVE 모드 실 API 연동 (pytrends, SerpAPI, Claude)
- ✅ gap_score 60+ 달성 (predictor/scorer 보정 완료)
- ✅ GitHub Actions 자동화 (daily.yml)
- ✅ EN 포스트 Blogger 자동 발행
- ✅ KO 포스트 생성 + 이메일 알림 → 티스토리 수동 발행
- ⚠️ Colab TimesFM 서버: ngrok URL 만료 시 수동 재시작 필요
- ❌ GSC (Google Search Console) 서비스 계정 미연동

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
