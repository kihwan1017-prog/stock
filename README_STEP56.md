# README_STEP56 — Technical Debt Cleanup

## 1. 목적

`PROJECT_REFACTOR_PLAN.md`(STEP55) Critical/High 항목을 **안전하게** 정리한다.

- 신규 기능 없음
- 대규모 rewrite 없음 (`broker`/`brokers` 병합 안 함)
- API 경로는 유지하되 **Deprecated** 표시 + Paper 백엔드로 교체
- 기존 테스트 통과

---

## 2. 제거·변경 요약

### Critical — RiskService 복구
- `risk/service.py` → DB `create_policy` / `create_and_save_position_plan` 복구
- `risk/legacy_gate.py` → 구 step32 `evaluate` (`InMemoryRiskGate`)

### Legacy step32
- InMemory `PositionRepository` / `PositionService` / `PortfolioService` **삭제**
- `step32_router` 유지하되:
  - `deprecated=True`
  - GET → Paper DB 조회
  - POST executions → `PaperAccountService.apply_fill`
  - `/risk/check` → `InMemoryRiskGate`
- FE Admin/User API를 Paper · `admin-summary`로 이전

### Dead packages 삭제
| 삭제 | 대체 |
|------|------|
| `market/` | `markets/` |
| `indicator/` | `indicators/simple.py` |
| `strategies/` | `strategy_deployment/` |
| `strategy/base.py`, `momentum.py` | (stub 제거) |
| `dashboard/` (empty) | — |
| `position/repository.py`, `service.py` | ExitMonitor·lot_rounding 유지 |
| `portfolio/service.py` | — |

### Duplicate API
- `/api/v1/indicator` 라우터 **등록 해제** (파일은 deprecated stub 잔존)
- step32 paths는 deprecated + prefer 안내

### Broken Route
- 메뉴 "데이터" → `/admin/monitoring`
- `/admin/data`, `/admin/market` redirect 유지

### Packages 문서화 (미병합)
- `broker/` = 주문·계좌·WS
- `brokers/` = 시세 REST
- `risk/` vs `risk_engine/` 역할 `__init__`에 명시

### README
- `README_STEP42`~`55` → `docs/archive/steps/`
- 본 파일 `README_STEP56.md`는 루트 유지

---

## 3. Deprecated API (호환 유지)

| Path | Prefer |
|------|--------|
| `GET /positions` | `/paper-accounts/{id}/positions` |
| `GET /portfolio/summary` | `/dashboard/admin-summary` |
| `GET /dashboard/summary` | `/dashboard/admin-summary` |
| `POST /positions/executions` | paper-orders / order-execution |
| `POST /risk/check` | `/risk` · risk_engine |
| `/api/v1/indicator/*` | `/api/v1/indicators` (unregister) |

---

## 4. 삭제된 주요 파일

- `src/stock_platform/market/**`
- `src/stock_platform/indicator/**`
- `src/stock_platform/strategies/**`
- `src/stock_platform/dashboard/**`
- `src/stock_platform/position/repository.py`
- `src/stock_platform/position/service.py`
- `src/stock_platform/portfolio/service.py`
- `src/stock_platform/strategy/base.py`, `momentum.py`

---

## 5. 주의사항

- step32 **URL은 아직 존재**한다. 다음 릴리스에서 unregister 가능.
- step33 in-memory market 테스트는 `pytest.skip`.
- `broker`/`brokers` 물리 병합은 후속 STEP (rewrite 범위).
- Alembic `step32_*` revision id는 삭제하지 않음.

---

## 6. 검증

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\python.exe -m pytest -q

cd frontend
npm run lint
npm run typecheck
npm run test
npm run build
```

---

## 7. 완료 체크리스트

- [x] RiskService 복구
- [x] step32 InMemory 제거 + deprecated Paper 호환
- [x] Dead package 제거
- [x] FE 이전 · admin/data 메뉴
- [x] STEP README archive
- [x] lint / typecheck / build / test
