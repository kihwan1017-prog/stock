# README_STEP57_1_REMOVE_OPENCLAW.md

## 작업 목적

주식 자동매매 시스템에서 **OpenClaw 연동을 프로젝트 범위에서 제외**하고,  
관련 코드·화면·메뉴·Stub·TODO를 안전하게 제거한다.

- Telegram / Ollama / Notification / 자동매매 / 인증 / 운영센터는 **유지**
- 신규 기능 없음 · 관련 없는 대규모 리팩터 없음

---

## 분석 결과

| 구분 | 결과 |
|------|------|
| Backend (`src/`) | OpenClaw **0건** (Router/Service/Entity 없음) |
| Backend tests | **0건** |
| `.env.example` / Settings | `OPENCLAW_*` **없음** |
| DB 테이블 | OpenClaw 전용 **없음** |
| Frontend | Stub·페이지·메뉴·브리지만 존재 |
| 공유 코드 | `opsCatalog` = Telegram/알림 카탈로그 (OpenClaw 전용 아님) |

### 분류

1. **OpenClaw 전용 (삭제)** — bridge/types/tests, Admin OpenClaw stub UI, User AI OpenClaw 슬롯
2. **Telegram 공유 (이동·유지)** — `opsCatalog`, Telegram 상태·명령·설정 UI
3. **Ollama 공유 (유지)** — User/Admin Ollama API·화면
4. **Notification 공유 (유지)** — Publisher / Service / TelegramSender
5. **문서 이력 (보존 + DEPRECATED 배너)** — STEP47/50/54/55 archive

---

## 삭제한 Backend 항목

없음. (구현·Stub·의존성 모두 부재)

---

## 삭제한 Frontend 항목

| 항목 | 처리 |
|------|------|
| `features/user/ai/openClawBridge.ts` | 삭제 |
| `features/user/ai/openClawTypes.ts` | 삭제 |
| `features/user/ai/openClawBridge.test.ts` | 삭제 |
| `features/admin/openclaw/opsCatalog.ts` | → `features/admin/notifications/opsCatalog.ts` |
| `app/(admin)/admin/openclaw/page.tsx` | 삭제 (redirect는 next.config) |
| User `/user/ai` OpenClaw 카드·의견 stub | 제거 |
| 메뉴 `OpenClaw · Telegram` | → `Telegram 운영` |
| `queryKeys.user.openClawStatus` | 삭제 |

### 추가

- `/admin/telegram` — Telegram·이벤트·명령·설정 (구 openclaw 페이지의 Telegram 부분)
- `next.config.ts` — `/admin/openclaw` → `/admin/telegram` permanent redirect

---

## 삭제한 설정 및 환경변수

- `OPENCLAW_*` 환경변수: 원래 없음
- `.gitignore`의 `openclaw-workspace-state.json` 항목 제거
- `AGENTS.md` / `IDENTITY.md`의 OpenClaw 문구 일반화

Telegram (`TELEGRAM_*`) · Ollama (`OLLAMA_*`) 유지.

---

## DB 변경 여부

**DB 변경 없음.**  
OpenClaw 전용 테이블/컬럼/설정 키 없음. Alembic Migration 불필요.  
운영 DB에 자동 적용한 작업 없음.

---

## 삭제한 의존성

없음. (OpenClaw 전용 npm/pip 패키지 없음)

---

## 수정한 메뉴와 Route

| Before | After |
|--------|-------|
| `adminRoutes.openclaw` = `/admin/openclaw` | `adminRoutes.telegram` = `/admin/telegram` |
| 메뉴: OpenClaw · Telegram | 메뉴: Telegram 운영 |
| `/admin/notifications` → openclaw 링크 | → telegram 링크 |

---

## Telegram 유지 확인

- `TelegramSender` / `NotificationPublisher` / `NotificationService` — 미변경
- `/admin/telegram` · `/admin/notifications` · User notifications — 유지
- `TELEGRAM_OPS_COMMAND_CATALOG` · `NOTIFICATION_EVENT_CATALOG` — 유지
- Bot 명령·Kill Switch 알림 경로 — 미변경

---

## Ollama 유지 확인

- User AI Ollama 상태·모델 선택 — 유지
- Admin `/admin/ollama` — 유지
- AI 분석·뉴스 요약 — 유지 (OpenClaw 이벤트 훅만 제거)

---

## 테스트 결과

| 항목 | 결과 |
|------|------|
| Backend `from stock_platform.api.main import app` | OK |
| pytest | 통과 (skip 3) |
| FE lint | 통과 (기존 warning 2) |
| FE typecheck | 통과 (`.next` 캐시 정리 후) |
| FE vitest | 16 files / 37 tests 통과 (OpenClaw bridge 테스트 제거) |
| FE build | 통과 · `/admin/telegram` 포함 · `/admin/openclaw` 페이지 없음 |

---

## 남은 OpenClaw 문자열

| 위치 | 이유 |
|------|------|
| `frontend/next.config.ts` | OpenClaw redirect **제거** (활성 코드 0건) |
| `docs/archive/steps/README_STEP47/50/54/55` | 과거 이력 + DEPRECATED 배너 |
| `PROJECT_FINAL_AUDIT.md` / `PROJECT_REFACTOR_PLAN.md` | 감사 이력 문구 + STEP57-1 제외 명시 |
| `README_STEP57_1_REMOVE_OPENCLAW.md` | 본 문서 |

**활성 코드·메뉴·테스트·환경변수:** OpenClaw 제품 참조 **0건**.

---

## 주의사항

- OpenClaw 연동은 **향후 구현 예정으로 표시하지 않음** (범위 제외)
- Secret 값 출력·운영 DB migration 자동 적용 없음
- 빈 `admin/openclaw` 디렉터리가 남으면 수동 삭제 가능

---

## Rollback 방법

1. Git에서 본 STEP 커밋(또는 작업 트리) revert
2. 필요 시 `adminRoutes.openclaw`·bridge stub 복구
3. Telegram 카탈로그 경로가 `notifications/opsCatalog`로 바뀌었으므로 revert 시 import 경로 일치 확인

권장 커밋 메시지 (요청 시에만):

```
chore: remove OpenClaw integration
```
