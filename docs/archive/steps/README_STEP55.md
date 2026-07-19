# README_STEP55 — Project Cleanup & Refactoring (Analysis Only)

> **Note (STEP57-1):** OpenClaw Backend 후속 항목은 프로젝트 범위에서 제외됨.

## 1. 목적

`PROJECT_FINAL_AUDIT.md`에서 지적된 Legacy / Dead / Duplicate / Broken Route / Architecture Debt를 **분석**하고, 제거·복구 계획을 `PROJECT_REFACTOR_PLAN.md`로 남긴다.

- 새로운 기능 구현 없음  
- 대규모 삭제·리팩토링 없음  
- 코드 수정 최소화 (문서·로드맵만)

---

## 2. 산출물

| 파일 | 내용 |
|------|------|
| `PROJECT_REFACTOR_PLAN.md` | Dead / Legacy / Duplicate / Broken / Architecture / Priority |
| `README_STEP55.md` | 본 작업 요약 |
| `docs/reference/ROADMAPS_README.md` | STEP55 반영 |

---

## 3. 분석 요약

### Dead Code
- `market/`, `indicator/`, `strategies/`, empty `dashboard/`, unused `strategy` stubs → 제거 후보
- ExitMonitor / Notification / AutomaticScheduler → **사용 중** (감사 outdated)
- **`risk/service.py`**: step32 `evaluate`만 남아 DB API 호출부와 **불일치 (Critical)**

### Legacy (step32)
- `step32_router` 인메모리 positions/portfolio/risk/dashboard — 등록됨
- Admin/User API 일부가 아직 호출 → **FE 이전 전 삭제 금지**

### Duplicate Packages
- `broker`/`brokers`, `market`/`markets`, `indicator`/`indicators`, `strategy`/`strategies`/`strategy_deployment`, `risk`/`risk_engine`
- 단기: dead 단수 패키지 삭제 · risk는 역할 문서화 + Service 복구

### Duplicate API / Repository
- Paper DB vs step32 인메모리 이중 표면이 핵심
- Orders/Risk/AI는 prefix 분산 (의도적 분리 + 문서 부채)

### Broken Route
- `/admin/logs`: **페이지 존재** (감사 로그) — 감사 문서의 404는 outdated
- `/admin/data`: **redirect → monitoring** — 404는 해소, 메뉴 라벨 soft-broken
- Soft: OpenClaw BE, channel CRUD, backup, user watchlist/inbox 등

### Architecture Debt
- Bounded context 중복, step32 혼재, README 위치 규칙 불일치, 감사 문서 드리프트

---

## 4. Refactoring Priority (요약)

| 등급 | 항목 |
|------|------|
| Critical | RiskService DB 복구 · FE step32 이전 |
| High | step32 제거 · dead packages · `/admin/data` 라벨 · 감사 재스코어링 |
| Medium | deprecated indicator router · paper adapter · brokers 이동 · README 이관 |
| Low | API 카탈로그 · unused import · 신기능 백로그 분리 |

상세: `PROJECT_REFACTOR_PLAN.md`

---

## 5. 이번 STEP에서 하지 않은 것

- 패키지/라우터/서비스 **삭제**
- 자동매매·ExitMonitor·Telegram Ops **동작 변경**
- OpenClaw Backend 등 **신규 기능**

---

## 6. 테스트 / 검증

분석 전용 — 회귀 방지를 위해 기존 검증만 수행.

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\python.exe -m pytest tests/test_telegram_ops_step54.py tests/test_position_exit_monitor_step53.py tests/test_application_lifecycle.py -q

cd frontend
npm run lint
npm run typecheck
npm run test
npm run build
```

---

## 7. 완료 체크리스트

- [x] Dead / Legacy / Duplicate / Broken / Architecture 분석
- [x] `PROJECT_REFACTOR_PLAN.md`
- [x] `README_STEP55.md`
- [x] lint / typecheck / build / test
- [x] 코드 삭제 없음
