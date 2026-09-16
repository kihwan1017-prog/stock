# Paper 계좌 수정 (UPDATE)

## 기존 구현 상태

| 기능 | 상태 |
|------|------|
| 생성 `POST /paper-accounts` | 있음 |
| 목록 `GET /paper-accounts` | 있음 |
| Soft Delete `DELETE /paper-accounts/{id}` | 있음 (변경 없음) |
| 수정 `PATCH /paper-accounts/{id}` | **본 작업에서 Service/검증/감사/FE 모달로 보강** |

조사 결과 `trading.paper_account`에는 **설명/메모, 전략 연결, 계좌별 위험관리** 컬럼이 없다.  
임의 컬럼을 만들지 않았고, 실제 존재하는 필드만 수정 대상으로 확정했다.

## 수정 가능·불가능 필드

### 수정 가능

| 필드 | 조건 |
|------|------|
| `account_name` | 필수 아님(PATCH), 공백 금지, max 100, 전역 unique |
| `is_active` | 사용 여부. 비활성화 시 `is_default=false` |
| `is_default` | 기본 계좌. 비활성 계좌는 기본 지정 불가 |
| `initial_cash` | **주문·체결·보유(수량>0) 이력이 없을 때만**. 변경 시 `available_cash`도 동일 값으로 맞춤 |

### 수정 불가 (API로 받지 않음)

- `account_id`, `user_id`, 계좌 유형(PAPER 고정)
- `created_at`, `available_cash`(직접), `realized_profit_loss`
- 주문·체결·포지션·평가손익
- Soft-deleted (`deleted_at IS NOT NULL`) 계좌 전체

## API 명세

```http
PATCH /api/v1/paper-accounts/{account_id}
Authorization: Bearer <JWT>
Content-Type: application/json

{
  "account_name": "새이름",
  "is_active": true,
  "is_default": false,
  "initial_cash": 10000000
}
```

- 부분 수정: `exclude_unset` — 전달되지 않은 필드는 유지
- 빈 PATCH(`{}`) → **400** `수정할 필드가 없습니다.`
- 없음/삭제됨 → **404** (소유권 검사에서 soft-deleted도 404)
- 타인 계좌 → **403**
- 검증 실패 → **400**
- 권한: `trading:write` (admin은 RBAC 우회)

성공 시 계좌 dict + `has_trading_history`, `can_edit_initial_cash`.

## 권한·소유권

1. `require_permission("trading:write")`
2. `assert_paper_account_access` — DB에서 `user_id` 재검증 (admin은 전체)
3. JWT의 user_id만으로 UPDATE 하지 않음

## 초기 자산 정책

`PaperAccountRepository.has_trading_activity`:

- `paper_order` 존재 OR
- `paper_trade` 존재 OR
- `paper_position.quantity > 0`

→ 하나라도 있으면 `initial_cash` 변경 **400**.  
프론트는 `can_edit_initial_cash=false` 시 입력 비활성 + 사유 표시.

## 감사 로그

`PAPER_ACCOUNT_UPDATE`

```json
{
  "actor_user_id": 1,
  "account_id": 12,
  "changed_fields": ["account_name", "is_active"],
  "changes": [
    {"field": "account_name", "before": "A", "after": "B"}
  ]
}
```

민감정보·전체 객체 dump 없음.

## 수정한 파일

### Backend
- `trading/account_repository.py` — `has_trading_activity`, `find_by_account_name`, `clear_defaults_for_user`, `persist_account`
- `trading/account_service.py` — `update_account`
- `api/v1/paper_accounts.py` — PATCH Service/Audit, GET edit meta
- `tests/test_paper_account_update.py`

### Frontend
- `admin/accounts/page.tsx` — 수정 버튼·모달
- `admin/accounts/paperAccountUpdate.ts` (+ test)
- `admin/api/adminApi.ts` — `updatePaperAccount`
- `lib/query/queryKeys.ts` — `paperAccount`

### Docs
- `docs/trading/README_PAPER_ACCOUNT_UPDATE.md` (본 문서)
- `docs/trading/README.md`, `docs/README.md` 링크

## 테스트 결과

| 명령 | 결과 |
|------|------|
| `pytest tests/test_paper_account_update.py` (+ soft delete/service/step65) | **통과** |
| `npm run test -- src/features/admin/accounts/` | **통과** (8 tests) |
| `npm run typecheck` / `npm run build` | **통과** (`e2e`·`playwright.config.ts` 는 tsconfig exclude — 기존 Playwright 미설치 이슈) |
| `npm run lint` (accounts 관련) | **문제 없음** (레포 내 다른 파일 기존 warning/error 존재) |

## 남아 있는 제한사항

- 설명/메모·전략·위험관리 UI는 **스키마 부재**로 미구현
- 계좌명 unique는 사용자 단위가 아니라 **전역** (`uq_paper_account_account_name`)
- 낙관적 잠금 전용 버전 컬럼은 없음 — `updated_at` onupdate만 사용
- Soft Delete API/동작은 변경하지 않음
