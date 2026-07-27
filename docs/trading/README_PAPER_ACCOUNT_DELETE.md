# Paper 계좌 Soft Delete

## 목적

관리자 화면(`/admin/accounts`)에서 모의계좌(paper-account)를 **Soft Delete** 한다.  
주문·체결 이력이 있는 계좌도 목록에서 숨길 수 있으며, **Hard Delete(행 물리 삭제)는 하지 않는다.**

## 정책 요약

| 항목 | 내용 |
|------|------|
| 방식 | `trading.paper_account.deleted_at` 설정 + `is_active=false` |
| Hard Delete | **금지** (이력 유무와 무관하게 `DELETE FROM` 미사용) |
| 목록 | `deleted_at IS NULL` 만 반환 |
| 권한 | **관리자만** (`require_admin_user`) |
| 감사 | `operation.audit_event` / `PAPER_ACCOUNT_SOFT_DELETE` |

이력(주문 `paper_order` 또는 체결 `paper_trade`)이 있어도 Soft Delete는 허용한다.  
이력이 있는 계좌에 대해 Hard Delete를 시도하면 FK(`paper_order.account_id` RESTRICT) 등으로 막히며, 본 API는 Hard Delete 경로 자체를 제공하지 않는다.

## API

```http
DELETE /api/v1/paper-accounts/{account_id}
Authorization: Bearer <admin JWT>
```

성공 응답 예:

```json
{
  "deleted": true,
  "account_id": 12,
  "mode": "soft_delete",
  "deleted_at": "2026-07-22T00:00:00+00:00",
  "has_trading_history": true,
  "hard_delete_allowed": false
}
```

| 상태 | 의미 |
|------|------|
| 401 | 미인증 |
| 403 | 관리자 아님 |
| 404 | 계좌 없음 |
| 400 | 이미 Soft Delete 됨 |

목록:

```http
GET /api/v1/paper-accounts
```

→ Soft Delete된 행은 포함되지 않는다.

## DB

마이그레이션: `m9a0b1c2d3e4_paper_account_deleted_at.py`

```sql
ALTER TABLE trading.paper_account ADD COLUMN deleted_at TIMESTAMPTZ NULL;
-- 기존 is_active=false 행은 deleted_at 백필
```

Soft Delete 시:

1. `deleted_at = now()`
2. `is_active = false`, `is_default = false`
3. `account_name` 에 `__deleted_{account_id}` 접미 (unique 충돌 방지)

적용:

```bash
alembic upgrade head
```

## 레이어

| 레이어 | 위치 |
|--------|------|
| Model | `trading/account_models.py` — `PaperAccount.deleted_at` |
| Repository | `PaperAccountRepository.soft_delete_account`, `has_order_or_trade_history`, `list_accounts(include_deleted=False)` |
| Service | `PaperAccountService.soft_delete_account` |
| API | `api/v1/paper_accounts.py` — `DELETE` + Audit |
| Frontend | `/admin/accounts` 삭제 버튼 + 확인 모달 · `adminApi.deletePaperAccount` |

## Frontend

1. 목록 행에 **삭제** 버튼 (admin role)
2. 확인 모달 (`Soft Delete` / Hard Delete 하지 않음 안내)
3. 성공 시 목록 invalidate

헬퍼: `frontend/src/features/admin/accounts/paperAccountDelete.ts`

## 테스트

```bash
# backend
pytest tests/test_paper_account_soft_delete.py -q

# frontend
cd frontend && npm run test -- src/features/admin/accounts/paperAccountDelete.test.ts
```

## Audit

`AuditLogService.record(event_type="PAPER_ACCOUNT_SOFT_DELETE", ...)`

`detail` 예: `account_id`, `mode`, `has_trading_history`, `hard_delete_allowed=false`, `deleted_at`
