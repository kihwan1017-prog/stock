# README_STEP51 — Operation Center

## 1. 목표

Admin 전용 **운영센터(Operation Center)** 를 구현한다.

Scheduler · Broker · PostgreSQL · System Monitor · Batch · Environment ·  
Log Viewer · Backup · Restore · Health Check 를 한곳에서 조망하고,  
기존 Admin 상세 화면으로 연결한다.

STEP51은 **신규 Backend API를 만들지 않는다.**  
기존 페이지를 재작성하지 않고 **허브 + live status** 로 묶는다.

---

## 2. 구현 범위

| 기능 | 상태 | 허브 연결 / API |
|------|------|-----------------|
| Scheduler | 연결 | `/admin/scheduler` · `GET /jobs` · history |
| Broker | 연결 | `/admin/kiwoom` · `/admin/upbit` · broker/kiwoom API |
| PostgreSQL | 연결 | `/admin/db` · `GET /ops/db/status` · migration · tables |
| System Monitor | 연결 | `/admin/monitoring` · system/dashboard · risk |
| Batch | 연결 | `/admin/batch` · jobs · pipelines · daily-reports |
| Environment | 연결 | `/admin/env-settings` · `/admin/system-settings` |
| Log Viewer | 부분 | `/admin/logs` = 감사 로그 · 앱 로그 테일 TODO |
| Backup | 부분 | `GET /ops/backup/status` · 웹 dump 실행 TODO |
| Restore | TODO | 웹 restore API 없음 → CLI 안내 |
| Health Check | 연결 | `GET /health` · `/version` |

---

## 3. 규칙

1. 기존 Backend API만 사용한다.
2. 없는 기능은 `UnimplementedApiPanel` + TODO.
3. Admin 전용 (`AuthGuard` admin/operator).
4. 기존 상세 페이지를 허브로 흡수하지 않는다.

---

## 4. 화면

| 경로 | 역할 |
|------|------|
| `/admin/operations` | 운영센터 허브 (redirect 해제 후 구현) |
| 기존 `/admin/scheduler` 등 | 상세 운영 화면 유지 |

메뉴: **리스크·운영 › 운영센터** (`menu:scheduler`)

---

## 5. 주요 파일

```text
README_STEP51.md
frontend/src/app/(admin)/admin/operations/page.tsx
frontend/src/features/admin/operations/operationCenterTiles.ts
frontend/src/config/routes.ts
frontend/src/config/menu.tsx
```

---

## 6. TODO (후속)

- [ ] 앱 로그 파일 테일 API
- [ ] 웹 Backup dump / Restore 실행 API
- [ ] 웹 Alembic migrate 실행 API

---

## 7. 완료 체크리스트

- [x] README 초안
- [x] `/admin/operations` 허브
- [x] Admin 메뉴 등록
- [x] lint / test / build
- [x] README 최종

---

## 8. 구현 결과

| 항목 | 내용 |
|------|------|
| 허브 | `/admin/operations` — live status + 10개 기능 타일 |
| 메뉴 | 리스크·운영 › 운영센터 |
| 검증 | lint · test · build |

다음: STEP52+
