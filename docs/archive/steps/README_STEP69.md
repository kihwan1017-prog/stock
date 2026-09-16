# README_STEP69 — User Watchlist Disclosures & AI Summary

## 목적

STEP67 관심종목 기반 공시 조회·읽음·북마크와  
사용자용 공시 AI 요약(Ollama)을 구현한다.  
종목 매수·매도 추천 알고리즘은 변경하지 않는다.

---

## 기존 문제

- 사용자 공시 화면이 포지션·공용 `/dart/*`에 의존
- UnimplementedNotice (관심종목 공시 / AI 요약)
- 사용자 AI 화면이 관리자 Ollama(`settings:read` 등) API 호출
- 공시 AI 요약 테이블·사용자 API 부재

---

## DART 공시 구조

재사용 테이블:

| 테이블 | 역할 |
|--------|------|
| `disclosure.dart_corp` | stock_code ↔ corp_code 매핑 |
| `disclosure.dart_disclosure` | 공용 공시 메타 (`receipt_no` Unique) |
| `disclosure.user_disclosure_state` | 사용자 읽음·북마크 |
| `disclosure.disclosure_ai_summary` | 공용 AI 요약 캐시 |

원문 HTML은 저장하지 않음. AI 입력은 메타데이터(보고서명·유형·비고 등).

---

## 종목·법인코드 매핑

- `DartCorpRepository.find_by_stock_code` (활성만)
- 관심종목 `market` ∈ KRX/KOSPI/KOSDAQ 만 공시 대상
- 종목명 문자열 매칭만으로 연결하지 않음

---

## 사용자 공시 API

권한: JWT + `trading:read` (admin/`settings:*` 불필요)

| Method | Path |
|--------|------|
| GET | `/api/v1/user/disclosures` |
| GET | `/api/v1/user/disclosures/unread-count` |
| GET | `/api/v1/user/disclosures/{id}` |
| POST/DELETE | `.../read`, `.../bookmark` |
| POST | `/api/v1/user/disclosures/read-all` |
| GET/POST | `.../ai-summary` |
| POST | `.../ai-summary/regenerate` |
| GET | `/api/v1/user/ai/status` |
| GET | `/api/v1/user/ai/disclosure-summaries/recent` |

---

## 읽음 및 북마크

뉴스(STEP68)와 동일 패턴. 원문 삭제 금지. Idempotent.

---

## AI 요약 구조

- 공용 캐시 Unique: `(disclosure_id, summary_type, model_name, prompt_version, source_text_hash)`
- 사용자마다 동일 요약 중복 생성 금지
- Pydantic `DisclosureSummaryPayload` 검증
- Prompt Injection 방어 system prompt
- 투자 권유 금지

---

## 사용자·관리자 AI 권한 분리

- 사용자: `/user/ai/status`, `/user/disclosures/.../ai-summary`
- 관리자: `/ollama/*`, `/settings` (사용자 화면에서 호출하지 않음)

---

## 캐시와 재생성

- 동일 hash/prompt/model → COMPLETED 재사용
- regenerate는 명시적 재생성, 실패 시 기존 COMPLETED 유지
- hash/prompt/model 불일치 시 STALE

---

## Ollama 장애 처리

- 생성 요청 → 503 + 사용자 친화 메시지
- 기존 COMPLETED 조회는 계속 가능
- Rate Limit → 429

---

## Frontend

- `/user/disclosures` — UnimplementedNotice 제거, watchlist 연동, Drawer+AI
- `/user/ai` — 관리자 Ollama 설정 제거, 최근 공시 요약 연계

---

## Database 변경

Migration: `c9d0e1f2a3b4` (revises `b8c9d0e1f2a3`)

```powershell
D:\Projects\stock-platform\.venv\Scripts\alembic.exe upgrade head
```

운영 DB 자동 적용 금지.

---

## 운영 설정

```
AI_DISCLOSURE_SUMMARY_MODEL=   # 비우면 OLLAMA_MODEL
AI_DISCLOSURE_SUMMARY_PROMPT_VERSION=v1
AI_DISCLOSURE_SUMMARY_COOLDOWN_SECONDS=30
AI_DISCLOSURE_SUMMARY_MAX_PER_MINUTE=10
DART_API_KEY=
```

Scheduler Job: `watchlist_disclosure_sync`

---

## 테스트

- `pytest tests/test_step69_user_disclosures.py`
- `vitest userDisclosureHelpers.test.ts`

---

## 수동 검증

1. alembic upgrade head
2. 관심종목 등록 (`disclosure_enabled`)
3. (선택) `watchlist_disclosure_sync` 또는 기존 DART sync
4. `/user/disclosures` 목록·읽음·북마크·AI 요약
5. `/user/ai`에서 settings:read 오류 없이 상태·최근 요약 확인

---

## 남은 사용자 기능

- 사용자 AI 종목 추천
- 알림 인박스
- 알림 구독
- 사용자 개인 설정
- 내정보 최종 보완
- User 통합 테스트
