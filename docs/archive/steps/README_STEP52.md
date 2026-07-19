# README_STEP52 — Authentication & Account Ownership

## 1. 목적

`PROJECT_FINAL_AUDIT.md` Critical 3건을 해소한다.

1. 주문/매매 관련 API에 JWT + `trading:read` / `trading:write` 적용  
2. `require_admin`의 **DEV_OPEN 제거** · 운영에서 `ADMIN_API_KEY` 없으면 **기동 실패**  
3. User Web **`account_id = 1` 하드코딩 제거** · 로그인 사용자 Paper 계좌 소유권  

---

## 2. 권한 매핑

| Backend role | 제품 | trading:read | trading:write |
|--------------|------|--------------|---------------|
| viewer | viewer | ✅ | ❌ |
| operator | trader | ✅ | ✅ |
| admin | admin | ✅ (우회) | ✅ (우회) |

---

## 3. 변경 파일

### Backend
- `src/stock_platform/auth/deps.py` — DEV_OPEN 제거
- `src/stock_platform/common/settings.py` — `ensure_admin_api_key()`
- `src/stock_platform/auth/account_ownership.py` — Paper 소유권 검사
- `src/stock_platform/trading/account_models.py` — `user_id`
- `src/stock_platform/trading/account_repository.py` / `account_service.py`
- `src/stock_platform/api/v1/paper_accounts.py` — auth + `GET /me`
- `src/stock_platform/api/v1/paper_orders.py`
- `src/stock_platform/api/v1/order_execution.py`
- `src/stock_platform/api/v1/orders.py`
- `src/stock_platform/api/v1/order_cancel_replace.py`
- `src/stock_platform/api/v1/executions.py`
- `src/stock_platform/api/v1/order_outbox.py`
- `src/stock_platform/api/v1/notifications.py`
- `database/alembic/versions/c2d3e4f5a6b7_add_paper_account_user_id.py`
- `tests/test_auth_deps_step52.py` · `tests/test_step39_operations.py`
- `.env.example`

### Frontend
- `features/user/hooks/useMyPaperAccountId.ts`
- `features/user/api/userApi.ts` — `getMyPaperAccount`, account_id 필수
- User: dashboard / portfolio / trading / news / disclosures

---

## 4. 변경 API

| Method | Path | Auth |
|--------|------|------|
| GET | `/paper-accounts/me` | trading:read (+ lazy 생성) |
| GET/POST | `/paper-accounts…` | trading:read / write + ownership |
| POST | `/order-execution/submit` | trading:write + ownership |
| * | `/paper-orders…` | trading:read/write (+ create ownership) |
| * | `/orders…` (list/get/cancel/replace) | trading:read/write |
| GET | `/executions` | trading:read |
| * | `/order-outbox…` | trading:read/write |
| GET/POST | `/notification/status|test` | trading:read/write |

URL 경로는 유지. **Bearer JWT 필수** (호환: 클라이언트에 Authorization 헤더).

---

## 5. 변경 DB

```text
trading.paper_account.user_id BIGINT NULL
  FK → auth.user(user_id) ON DELETE SET NULL
  INDEX ix_paper_account_user_id
백필: account_id=1 → admin 사용자(roles @> ["admin"]) 있으면 배정
```

적용:

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\alembic.exe -c database/alembic.ini upgrade head
```

---

## 6. Repository / 관계 보고

| 관계 | 상태 |
|------|------|
| AuthUser → PaperAccount | ✅ STEP52 `user_id` FK 추가 |
| PaperAccount → Position/Trade | ✅ 기존 CASCADE FK |
| AuthUser → BrokerAccountSnapshot | 🔴 FK 없음 (스냅샷은 broker+account_number) |
| AuthUser → TradingOrder.account_id | 🟡 논리 참조만 (FK 없음 — 후속) |
| Portfolio 전용 테이블·회원 FK | 🔴 없음 (Paper valuation 기반) |

---

## 7. 영향 범위

- **변경 화면:** User dashboard/portfolio/trading/news/disclosures  
- **주의:** 무인증 스크립트의 주문/알림 호출 → **401**  
- **로컬:** DEV_OPEN 없음 → Admin 민감 API는 JWT admin 또는 `ADMIN_API_KEY`  
- **운영:** `APP_ENV=production|staging` + `ADMIN_API_KEY` 필수  

---

## 8. 테스트 방법

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\python.exe -m pytest tests/test_step39_operations.py tests/test_auth_deps_step52.py -q

cd frontend
npm run lint
npm run typecheck
npm run test
npm run build
```

---

## 9. 완료 체크리스트

- [x] README
- [x] 주문/매매 API 인증·권한
- [x] DEV_OPEN 제거 · 운영 ADMIN_API_KEY 기동 검증
- [x] account_id 하드코딩 제거 · `/paper-accounts/me`
- [x] lint / typecheck / test / build
- [x] ROADMAPS 갱신

---

## 10. 구현 결과

Critical 3건 해소. TradingOrder↔User FK·Broker 소유권은 후속(Medium).  
검증: pytest STEP39/52 통과 · frontend lint 0 errors · typecheck · test 41 · build OK.
