# GapHunter — Retro Notes

---

## 2026-04-18

### 오늘 한 것
- GapHunter 전체 파이프라인 완성 (collect → predict → score → generate → wiki)
- DRY_RUN_MODE 검증 완료
- LIVE 모드 전환 후 실 API 연동 확인 (pytrends, SerpAPI)
- Colab 예측 서버 구축 시도 (TimesFM → Chronos 전환)
- ngrok 터널 연동 시도

### 배운 것

| 이슈 | 원인 | 해결 |
|------|------|------|
| `python` 명령 안 됨 | Windows PATH 미등록 | `py` 사용 |
| dotenv 키 안 읽힘 | `load_dotenv()` 경로 미지정 | `dotenv_path=__file__/../.env` 명시 |
| cp949 UnicodeError | Windows 터미널 인코딩 | `.encode("ascii", errors="replace")` |
| pytrends 충돌 | urllib3 v2 호환 안 됨 | `pip install "urllib3<2.0"` |
| TimesFM 설치 실패 | lingvo Python 3.11 미지원 | Amazon Chronos로 교체 |
| rich 테이블 깨짐 | cp949 특수문자 | plain `print()` 로 교체 |
| gap_score 낮음 (44~51) | GSC 데이터 없음 + 선형 예측 | Chronos 서버로 개선 예정 |

**Chronos API 미해결**
- `ChronosPipeline.predict()` — `context=` 키워드 인자 거부
- 근본 원인: Colab 런타임 삭제 시 저장 전 코드로 롤백됨
- 수정 후 반드시 **Ctrl+S 저장** 필요

### 실수
1. ngrok 토큰 따옴표 없이 붙여넣음 → `SyntaxError: invalid decimal literal`
2. Cell 3 수정 후 재실행 안 하고 Cell 5 바로 실행 → 구버전 Flask 응답
3. "세션 다시 시작" ≠ "런타임 연결 해제 및 삭제" 혼동 → 포트 5000 충돌 반복
4. 런타임 삭제 후 토큰 초기화된 것 모르고 Cell 4 실행 → ngrok 인증 실패
5. Cell 변경사항 Ctrl+S 저장 안 하고 런타임 삭제 → 수정 내용 소실 반복

### 현재 상태
- ✅ 전체 파이프라인 코드 완성
- ✅ LIVE 모드 실 API 연동 (pytrends, SerpAPI, Claude)
- ✅ ngrok 계정 / 토큰 발급 완료
- ✅ `.env` COLAB_PREDICTOR_URL 업데이트
- ❌ Chronos 서버 predict() API 호환 문제 미해결
- ❌ gap_score 60+ 달성 미완료

### 다음 할 일
1. Colab Cell 3 `context=context` → `context` 수정 + Ctrl+S 저장
2. Chronos 서버 정상화 후 키워드 3개 LIVE 재테스트
3. 티스토리 Search Console 인증
4. GSC 서비스 계정 세팅
5. Amazon Associates 가입 (트래픽 생기면)
