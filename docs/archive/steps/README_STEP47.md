# README_STEP47 — AI

> **DEPRECATED / OUT OF SCOPE:**  
> OpenClaw integration was removed from the active project scope. (STEP57-1)

## 1. 목표

User Web **AI** 화면을 구현·정리하고 기존 Backend API에 연결한다.

AI 추천·분석·뉴스 요약·공시 요약·AI 의견·Ollama 모델 선택을 제공한다.  
**OpenClaw Agent** 연동은 제품 API가 없으므로 **준비 구조(types / bridge stub / UI 슬롯)** 만 추가한다.

STEP47은 **신규 Backend API를 만들지 않는다.** (OpenClaw 서버/엔드포인트 추측 금지)

---

## 2. 구현 범위

| 기능 | 상태 | 데이터 소스 |
|------|------|-------------|
| AI 추천 종목 | 연결 | `GET /candidates/top/{exchange}` |
| AI 종목 분석 | 연결 | `GET /ai-analysis/latest/{exchange}` · runs |
| 뉴스 요약 | 연결 | `GET /news/{ex}/{symbol}` · `POST /news/summarize` |
| 공시 요약 | 부분 | `GET /dart/disclosures` — AI 요약 API 없음 → TODO |
| AI 의견 | 연결 | `GET /ai-analysis/runs/{id}/candidates/{symbol}` (reasons/risks/rationale/action) |
| Ollama 모델 선택 | 연결(권한 의존) | `GET /ollama/status` · `/models` · `PUT /settings` (`ollama_model`) |
| OpenClaw Agent | **준비 구조** | FE bridge stub + UI 슬롯 · Backend 연동 TODO |

### 권한 참고

- `/ollama/*` 는 `settings:read` / `system:read` 등이 필요할 수 있음
- 모델 변경 `PUT /settings` 는 `settings:write`
- 권한 없으면 UI에서 안내 (임의 API 우회 금지)

---

## 3. OpenClaw 준비 구조

```text
frontend/src/features/user/ai/
  openClawTypes.ts      # Agent 이벤트/요청 타입
  openClawBridge.ts     # 연동 인터페이스 + NotConfigured stub
  openClawBridge.test.ts
```

- `OpenClawBridge` 인터페이스: `getStatus` / `sendEvent` / `requestOpinion`
- 기본 구현: `NotConfiguredOpenClawBridge` (연결 전 상태)
- UI: "OpenClaw Agent" 카드에서 status 표시 + TODO 배너
- 실제 HTTP/WebSocket 엔드포인트는 Backend 제공 후 구현

---

## 4. 규칙

1. 기존 Backend API만 사용한다.
2. 없는 기능은 `UnimplementedNotice` + TODO로 남긴다.
3. OpenClaw용 FastAPI 라우터를 추측으로 만들지 않는다.
4. UI는 `UserPageShell` 패턴 (STEP42~46과 동일).

---

## 5. 작업 순서

```
1. README_STEP47.md 작성
2. OpenClaw bridge stub + userApi(Ollama)
3. /user/ai 화면 확장
4. README 완료 체크리스트 업데이트
5. lint · test · build
```

---

## 6. TODO (후속)

- [ ] `POST /api/v1/dart/summarize` — AI 공시 요약
- [ ] User용 Ollama 모델 선택 권한/전용 API (viewer도 가능하도록)
- [ ] OpenClaw Backend: agent status / event ingest / opinion
- [ ] OpenClawBridge 실구현 연결

---

## 7. 완료 체크리스트

- [x] README 초안
- [x] 추천·분석·뉴스·공시·의견·Ollama
- [x] OpenClaw 준비 구조
- [x] lint / test / build
- [x] README 최종 업데이트

---

## 8. 구현 결과

| 항목 | 경로 / 내용 |
|------|-------------|
| AI 화면 | `frontend/src/app/(user)/user/ai/page.tsx` |
| OpenClaw types | `frontend/src/features/user/ai/openClawTypes.ts` |
| OpenClaw bridge | `frontend/src/features/user/ai/openClawBridge.ts` (+ test) |
| API | `userApi.getOllamaStatus` / `listOllamaModels` / `updateAppSettings` |
| 검증 | lint 0 errors · test 30 passed · build OK |

공시 AI 요약·OpenClaw Backend는 TODO로 남김. 다음: STEP48+
