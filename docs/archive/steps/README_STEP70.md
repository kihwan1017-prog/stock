# README_STEP70 — User AI Recommendation & Ollama Permission Separation

## 목적

일반 사용자가 관리자 권한 없이 AI 종목 추천을 생성·조회한다.  
AI 결과로 실제 주문은 실행하지 않는다.

---

## 기존 문제

- 사용자 AI 화면이 관리자 Ollama/Settings API에 의존 (`settings:read` 등)
- 개인화 추천 API·테이블 부재
- 공용 `/ai-analysis/*` 결과를 사용자 UI가 그대로 사용

---

## 사용자 AI와 관리자 AI 분리

| 구분 | 경로 | 권한 |
|------|------|------|
| 사용자 | `/api/v1/user/ai/*` | `trading:read` |
| 관리자 | `/api/v1/ollama/*`, `/settings` | `settings:*` / `system:read` |

사용자 응답에 Host/Port/내부 URL/모델 경로를 포함하지 않는다.

---

## 사용자 AI API

| Method | Path |
|--------|------|
| GET | `/api/v1/user/ai/status` |
| POST | `/api/v1/user/ai/recommendations` |
| GET | `/api/v1/user/ai/recommendations` |
| GET | `/api/v1/user/ai/recommendations/latest` |
| GET | `/api/v1/user/ai/recommendations/{id}` |
| POST/DELETE | `.../bookmark` |
| POST | `.../hide` |
| POST | `.../feedback` |

---

## 추천 생성 흐름

1. JWT 인증
2. account_id 소유권 검증 (Paper)
3. source_type별 후보 수집 (최대 15)
4. input_hash 중복/재사용 검사
5. Rate Limit
6. Ollama 구조화 호출
7. 후보 외 Symbol·rank·score 검증
8. 결과 저장 (COMPLETED/FAILED)

---

## 후보 종목 생성

- `WATCHLIST` — `ai_enabled` 관심종목
- `PORTFOLIO` — 소유 계좌 보유종목
- `WATCHLIST_AND_PORTFOLIO` — 합집합
- `MARKET_CANDIDATES` — 공용 최신 AI 분석 상위

임의 대량 Symbol 입력 불가.

---

## Prompt 및 Injection 방어

- System/데이터 분리
- 뉴스·공시 지시를 명령으로 취급하지 않음
- Secret·JWT·계좌번호 Ollama 미전달
- `AI_RECOMMENDATION_PROMPT_VERSION`

---

## 구조화 응답 검증

Pydantic + 후보 Allowlist, Action Enum, score 범위, rank 중복 차단.

---

## Database 변경

Migration: `d0e1f2a3b4c5` (revises `c9d0e1f2a3b4`)

- `ai.recommendation_request`
- `ai.recommendation_result`
- `ai.user_recommendation_state`

운영 DB 자동 적용 금지.

---

## Rate Limit

- 동일 input_hash Cooldown
- 분당 요청 한도 → 429

---

## Frontend

`/user/ai`

- 관리자 Ollama UI/`settings:*` 안내 제거
- 추천 조건·생성·결과·최근 목록·공시 요약 연계
- 투자 참고 안내 고정 표시
- 주문 버튼 없음

---

## 테스트

```powershell
D:\Projects\stock-platform\.venv\Scripts\python.exe -m pytest tests/test_step70_user_ai_recommendation.py -q
```

---

## 수동 검증

1. `alembic upgrade head`
2. 관심종목 `ai_enabled` 등록
3. `/user/ai`에서 추천 생성 (Ollama 가동 시)
4. settings:read 오류 없이 status/목록 조회
5. 타 계정 recommendation_id 접근 불가 확인

---

## 남은 사용자 기능

- 알림 인박스
- 알림 읽음
- 알림 구독
- 사용자 개인 설정
- 내정보 최종 보완
- User 통합 테스트
