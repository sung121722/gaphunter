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
