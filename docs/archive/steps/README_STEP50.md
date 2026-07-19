# README_STEP50 — OpenClaw & Telegram

> **DEPRECATED / OUT OF SCOPE:**  
> OpenClaw integration was removed from the active project scope. (STEP57-1)  
> Telegram·알림 카탈로그는 `/admin/telegram` · `features/admin/notifications/opsCatalog.ts` 로 유지.

## 1. 목표

Admin 운영 화면에서 **OpenClaw**·**Telegram**·**알림 이벤트**·**운영 명령**을 정리하고,  
기존 Backend API에 연결한다.

**Discord 관련 기능은 구현하지 않는다.** (송신 스택에 있어도 STEP50 UI/문서에서 제외)

STEP50은 **OpenClaw/Telegram 수신·슬래시 명령용 신규 Backend API를 만들지 않는다.**

---

## 2. 구현 범위

### OpenClaw

| 항목 | 상태 | 소스 |
|------|------|------|
| Gateway 상태 | 준비 구조 | FE ops snapshot stub |
| Agent 상태 | 준비 구조 | STEP47 `OpenClawBridge.getStatus` |
| Workspace / Memory / Skill / Tool | 준비 구조 | FE 카탈로그 + stub |
| Ollama 연결 상태 | 연결 | `GET /ollama/status` · `/models` |

### Telegram

| 항목 | 상태 | 소스 |
|------|------|------|
| Bot 연결·상태 | 연결 | `GET /notification/status` (TELEGRAM 채널) |
| Chat ID 관리 | 연결(설정) | `SettingsEditor` category=`environment` (`telegram_*`) |
| 알림 설정 | 부분 | env 설정 + 테스트 `POST /notification/test` |
| Bot 수신·슬래시 | TODO | Backend webhook/getUpdates 없음 |

### 알림 이벤트 카탈로그

주문 완료 · 체결 · 손절 · 익절 · Kill Switch · 서버 시작/종료 · Broker 실패 · Scheduler 오류 · AI 분석 완료 · 일일 리포트  
→ **UI 카탈로그 + 현재 Backend 지원 여부 표시** (대부분 planned, Kill Switch 일부 partial)

### 운영 명령

`/status` `/portfolio` `/orders` `/health` `/ai` `/report`  
→ **명령 카탈로그 + REST 매핑 안내** (Telegram 핸들러 TODO)

---

## 3. 규칙

1. 기존 Backend API만 사용한다.
2. 없는 기능은 `UnimplementedApiPanel` / `UnimplementedNotice` + TODO.
3. Discord UI·설정을 STEP50에서 추가하지 않는다.
4. OpenClaw FastAPI 라우터를 추측으로 만들지 않는다.

---

## 4. 화면

| 경로 | 역할 |
|------|------|
| `/admin/openclaw` | OpenClaw ops · Telegram · 알림 이벤트 · 운영 명령 (신규) |
| `/admin/notifications` | 채널 상태·테스트 + OpenClaw 페이지 링크 |
| `/user/notifications` | 이벤트 카탈로그(조회) · 채널 상태 · 테스트 |
| `/user/ai` | 기존 OpenClaw Agent 슬롯 (STEP47) |

---

## 5. 주요 파일

```text
README_STEP50.md
frontend/src/app/(admin)/admin/openclaw/page.tsx
frontend/src/features/admin/openclaw/opsCatalog.ts
frontend/src/features/user/ai/openClawTypes.ts
frontend/src/features/user/ai/openClawBridge.ts
frontend/src/app/(admin)/admin/notifications/page.tsx
frontend/src/app/(user)/user/notifications/page.tsx
```

---

## 6. TODO (후속)

- [ ] `GET/POST /api/v1/openclaw/*` (gateway/agent/workspace/memory/skills/tools)
- [ ] Telegram webhook · 슬래시 명령 라우터
- [ ] 알림 이벤트 구독/필터 API
- [ ] 주문·체결·리포트 등 이벤트별 발송 훅

---

## 7. 완료 체크리스트

- [x] README 초안
- [x] Admin OpenClaw & Telegram 페이지
- [x] 알림·명령 카탈로그
- [x] Discord 미구현 명시
- [x] lint / test / build
- [x] README 최종

---

## 8. 구현 결과

| 항목 | 내용 |
|------|------|
| Admin | `/admin/openclaw` — OpenClaw stub · Ollama · Telegram · 이벤트 · 명령 |
| 카탈로그 | `opsCatalog.ts` (+ test) |
| Bridge | `getOpsSnapshot()` 추가 |
| Discord | UI 제외 |
| 검증 | lint · test · build |

다음: STEP51+
