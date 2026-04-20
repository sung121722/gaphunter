# GapHunter — Claude Context

## 프로젝트 요약
SEO 갭 예측 자동화 시스템. 경쟁자 콘텐츠가 죽어가는 타이밍을 예측해 자동으로 포스트 생성.

- **블로그 (EN)**: https://stuffnod.blogspot.com/ — AI 도구 / 아웃도어 용품 리뷰
- **블로그 (KO)**: https://sung1216.tistory.com/ — 건강식품 / 라이프스타일
- **수익화**: Amazon Associates (EN) / 쿠팡 파트너스 AF6344014 (KO)

---

## 파이프라인
```
collector.py → predictor.py → scorer.py → generator.py → 블로그 발행
```

---

## 디렉토리 구조
```
J:/gaphunter/
├── config.py              # 전체 설정, API 키 로드
├── main.py                # CLI 진입점
├── .env                   # API 키 (git 제외)
├── retro-notes.md         # 세션별 회고 기록
├── core/
│   ├── collector.py       # pytrends + SerpAPI + BeautifulSoup
│   ├── predictor.py       # 선형회귀 / Chronos 예측
│   ├── scorer.py          # gap_score 0~100 계산
│   └── generator.py       # Claude API 콘텐츠 생성
├── colab/
│   └── timesfm_server.ipynb  # Chronos 예측 서버 (Google Colab)
├── wiki/                  # LLM-Wiki (Karpathy 패턴)
├── posts/                 # 생성된 마크다운 포스트
└── raw/trends/            # pytrends 수집 JSON
```

---

## 자주 쓰는 명령어
```bash
# Windows에서 python 대신 py 사용
py main.py "camping chairs" --lang en
py main.py "마그네슘 효능" --lang ko
py core/collector.py
py core/predictor.py raw/trends/camping_chairs_US.json
py core/scorer.py
py core/generator.py
py config.py              # 설정 확인
py wiki_agent.py query "키워드"
```

---

## 주의사항
- **Windows**: `python` 아닌 `py` 사용
- **인코딩**: 터미널 cp949 → print 시 `.encode("ascii", errors="replace").decode("ascii")`
- **urllib3**: v2 호환 안 됨 → `pip install "urllib3<2.0"` 유지
- **dotenv**: `load_dotenv(dotenv_path=...)` 명시 경로 필수
- **DRY_RUN_MODE**: `.env`에서 `false`로 설정 시 실 API 호출
- **날짜**: 이 프로젝트에서 날짜는 항상 dayjs를 사용할 것

---

## 현재 상태 (2026-04-18)
- ✅ 전체 파이프라인 코드 완성
- ✅ LIVE 모드 실 API 연동 (pytrends, SerpAPI, Claude)
- ✅ ngrok 계정 / 토큰 발급 완료
- ❌ Chronos 서버 predict() API 호환 문제 미해결
- ❌ gap_score 60+ 달성 미완료

## 다음 할 일
1. Colab Cell 3 `context=context` → `context` 수정 + Ctrl+S 저장
2. Chronos 서버 정상화 후 키워드 3개 LIVE 재테스트
3. 티스토리 Search Console 인증
4. GSC 서비스 계정 세팅

---

## Colab 서버 세팅 순서 (매 세션)
```
1. Colab 열기 → Cell 3 context= 수정 확인 → Ctrl+S
2. Cell 2 실행 → "Chronos model loaded." 확인
3. Cell 3 실행 → "Flask app defined." 확인
4. Cell 4 — NGROK_AUTH_TOKEN = '3CW1zuL2mJMuAcnmYg11ABWzLN1_4M3g1zh4Ujwkp9nBhiUeY'
5. Cell 4 실행 → ngrok URL 복사
6. .env COLAB_PREDICTOR_URL 업데이트
7. Cell 5 실행 → forecast 숫자 출력 확인
```

---

## Gap Score 공식
```
gap_score = demand_growth(0.4) + decay_prob(0.3) + competition_gap(0.2) + timing_advantage(0.1)
GENERATE_NOW  : 80+
GENERATE_SOON : 60~79
QUEUE         : 40~59
MONITOR       : 0~39
```
