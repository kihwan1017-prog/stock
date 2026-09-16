# README_STEP65 — User Account Ownership Foundation

## 목적

일반 사용자 영역의 **회원별 계좌 관리·소유권·거래내역 account_id** 기반을 완성한다.

이번 STEP에서 구현하지 않는 항목:

- 포트폴리오 자산 변화 차트
- 관심종목
- 사용자용 AI / 공시 AI 요약
- 알림 인박스
- 사용자 개인 설정

---

## 기존 문제

1. User Web `거래내역`이 `account_id` 없이 `/orders` 호출 → `account_id가 필요합니다.`
2. `/executions`가 계정 스코프 없이 전역 조회 (IDOR 위험)
3. `내 계좌` / `내정보`에 UnimplementedNotice · JWT 일부 노출
4. 회원별 Broker 연결 테이블 없음 (서버 공용 Kiwoom sync만 존재, 일부 무인증)
5. Paper 기본 계좌 Unique 미보장

---

## 계좌 도메인 구조

| 유형 | 저장 | 거래 account_id |
|------|------|-----------------|
| PAPER | `trading.paper_account` (+ `is_default`, `is_active`) | `paper_account.account_id` |
| KIWOOM / UPBIT | `trading.user_broker_account` (해시·마스킹만) | 연결 ID (주문 스코프는 Paper만) |

공통 응답 (`UserAccountView`):

```json
{
  "account_id": 10,
  "user_id": 3,
  "account_type": "PAPER",
  "broker_code": "PAPER",
  "account_name": "기본 모의계좌",
  "masked_account_number": null,
  "currency_code": "KRW",
  "is_default": true,
  "is_active": true,
  "connection_status": "CONNECTED",
  "created_at": "...",
  "updated_at": "...",
  "last_synced_at": null
}
```

**절대 응답/저장하지 않음:** 평문 계좌번호, 비밀번호, Client Secret, Access Token.

### 키움 공용 인증 문서화

현재 Kiwoom OpenAPI는 **서버 공용 credential** 을 사용한다.

- 관리자: `POST /api/v1/broker/kiwoom/account/sync` (require_admin)
- 회원: `POST /api/v1/user/accounts` 로 **소유권 매핑만** 관리
- 회원 `.../sync` 는 `last_synced_at` 메타 갱신 (공용 Secret 미노출)

---

## 사용자 계좌 API

모두 JWT + `trading:read` / `trading:write`.  
`user_id` 는 요청 body로 받지 않으며 JWT에서만 결정.

| Method | Path |
|--------|------|
| GET | `/api/v1/user/accounts` |
| POST | `/api/v1/user/accounts` |
| GET | `/api/v1/user/accounts/{account_id}` |
| PATCH | `/api/v1/user/accounts/{account_id}` |
| DELETE | `/api/v1/user/accounts/{account_id}` |
| POST | `/api/v1/user/accounts/{account_id}/set-default` |
| POST | `/api/v1/user/accounts/{account_id}/connect` |
| POST | `/api/v1/user/accounts/{account_id}/disconnect` |
| POST | `/api/v1/user/accounts/{account_id}/sync` |

Paper 보강: `PATCH/DELETE /paper-accounts/{id}`, `/me` lazy 생성 + 기본 계좌 보장.

---

## 소유권 정책

- `assert_paper_account_access` / `assert_trading_account_access` / `assert_broker_account_access` / `assert_account_access`
- 주문·체결 list: 비admin은 `account_id` 필수 + 소유권 검사
- paper-orders list: 비admin은 소유권 확인 후 **빈 목록** (테이블에 account_id 컬럼 없음 — 전역 노출 방지)
- 일반 사용자에게 `settings:*` / admin 권한 부여하지 않음

---

## 거래내역 account_id 처리

Frontend:

1. `GET /user/accounts` → Paper 기본 계좌 자동 선택
2. `enabled: accountId !== null && accountId > 0`
3. `GET /orders?account_id=` / `GET /executions?account_id=`

계좌 없음 Empty State → `/user/account` 안내.

---

## Database 변경

Migration: `e5f6a7b8c9d0_step65_user_account_ownership.py`  
(revises `d4e5f6a7b8c9`)

- `paper_account.is_default`, `is_active`
- partial unique `uq_paper_account_user_default`
- `trading.user_broker_account` + partial unique default per broker

운영 DB 자동 적용 금지. 로컬:

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\alembic.exe upgrade head
```

---

## Frontend 변경

- `user/account/page.tsx` — 실구현 (UnimplementedNotice 제거)
- `user/trades/page.tsx` — 계좌 선택·필터·pagination·enabled
- `user/profile/page.tsx` — `/user/accounts` · JWT 표시 제거
- `userApi.ts` — UserAccount / TradeOrder 타입
- dashboard / trading / portfolio — executions·paper-orders에 account_id

---

## 보안 검증

- [x] 타 사용자 Paper/Broker IDOR → 403
- [x] executions account 스코프
- [x] 계좌번호 마스킹·해시만 저장
- [x] Kiwoom sync admin 보호
- [x] Access Token UI 미표시
- [x] user_id 요청 조작 불가 (JWT 고정)

---

## 테스트 결과

- Backend: `pytest tests/test_step65_user_accounts.py` — pass
- Frontend: `vitest src/features/user/account/accountSelection.test.ts` — pass
- Frontend: `npm run typecheck` — pass
- Alembic head: `e5f6a7b8c9d0`
- FastAPI OpenAPI: `/api/v1/user/accounts*` 등록 확인

---

## 수동 검증 방법

1. 일반 사용자 로그인
2. `/user/account` — Paper 생성, 기본 지정, Broker 연결(번호 마스킹 확인)
3. `/user/trades` — 기본 계좌 자동 선택, account_id 오류 없음
4. 다른 사용자 account_id로 `/orders` 호출 시 403
5. 프로필에 JWT/토큰 미표시, 본인 계좌만 표시

---

## 남은 사용자 기능

- 포트폴리오 자산 변화 차트
- 관심종목
- 사용자용 AI
- 공시 AI 요약
- 알림 인박스
- 사용자 개인 설정
