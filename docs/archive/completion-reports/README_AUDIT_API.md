# README_AUDIT_API.md — API 전체 감사 보고서

| 항목 | 내용 |
|------|------|
| **감사일** | 2026-07-21 |
| **범위** | FastAPI `src/stock_platform/api` · Service/Repository/DTO/Entity · Frontend API 클라이언트 대조 |
| **원칙** | **코드 수정 없음.** 라이브 코드·라우터 등록 근거만 사용 |
| **앱 버전** | `settings.app_version` (릴리즈 1.1.0 계열) |
| **진입점** | `api/main.py` → `create_app()` → `api_router` + exception handlers + middleware |

---

## 0. 인벤토리 요약

| 계층 | 수량 | 근거 |
|------|------|------|
| v1 Router 파일 | **98** | `api/v1/*.py` |
| `_ROUTER_GROUPS` 등록 | **98** router 객체 | `settings`+`ollama` 포함, 모듈 **97** import |
| 미등록 Router | **1** | `indicator_router.py` (의도적 STEP56) |
| Endpoint (데코레이터) | **~327** | GET 154 · POST 143 · PUT 9 · PATCH 5 · DELETE 16 |
| Service 파일 | **~90** | `*service*.py` |
| Repository 파일 | **~41** | `*repositor*.py` |
| API DTO (BaseModel in v1) | **~107** | router 내 요청/응답 모델 |
| ORM Entity (`__tablename__`) | **81** | 도메인 모델 |
| FE userApi exports | **138** | `features/user/api/userApi.ts` |
| FE adminApi exports | **99** | `features/admin/api/adminApi.ts` |

### 인증 없는 mutate POST (공개 auth 제외)

**46개** — Critical/High 다수 (§권한·중복·미사용 참고)

### Rate Limit 적용 라우터

`auth`, `notifications`, `telegram_ops`, `user_profile` — **4파일만**

---

## 1. 모든 Router (등록 현황)

### 1.1 등록됨 (`router.py` import + `_ROUTER_GROUPS`)

도메인별 대표 prefix:

| 영역 | Prefix 예 | Auth 패턴 |
|------|-----------|-----------|
| Health/Version | `/health`, `/version` | 공개 |
| Auth/RBAC | `/api/v1/auth`, `/users`, `/roles` | 혼합/권한 |
| User STEP65–73 | `/api/v1/user/*` | JWT + permission |
| Trading/Orders | `/api/v1/orders*`, `order-execution`, `paper-*`, `broker*` | permission/admin |
| Risk | `/api/v1/risk/*`, kill-switch, policies | 혼재(일부 무인증) |
| Market/Sync | `/api/v1/market*`, `/sync`, `/upbit`, `/prices` | **대부분 무인증** |
| AI/Backtest/WF | `/api/v1/ai-*`, `backtest*`, `walk-forward*` | **대부분 무인증** |
| Strategy | deployments/runtime/leaderboard/… | 혼재 |
| Ops | `/monitoring`, `/ops`, `/settings`, `/jobs`, `/audit` | admin/permission |
| Notify | `/notification`, `/telegram`, `/user/notifications` | permission/admin |
| Legacy | `/api/v1` (`step32_router`) | **무인증** |

### 1.2 미등록

| Router | Prefix | 상태 |
|--------|--------|------|
| `indicator_router.py` | `/api/v1/indicator` | deprecated tombstone, STEP56 등록 해제 |

---

## 2. Endpoint · Service · Repository · DTO · Entity

### 2.1 Endpoint 분포

| Method | Count | 비고 |
|--------|------:|------|
| GET | 154 | 조회·상태·대시보드 |
| POST | 143 | 생성·실행·sync·분석 (무인증 다수) |
| PUT | 9 | 전체 갱신 |
| PATCH | 5 | 부분 갱신 (user settings/profile 등) |
| DELETE | 16 | 삭제/해제 |
| **합계** | **~327** | `GET /` root는 api_router 밖 |

### 2.2 Service / Repository

| 계층 | 역할 | 관찰 |
|------|------|------|
| Service (~90) | 비즈니스 규칙·오케스트레이션 | 도메인별 분리 양호. User/Paper/Order/AI 등 |
| Repository (~41) | SQLAlchemy 세션 접근 | 핵심 도메인 커버. 일부 라우터가 세션/서비스 직접 호출 |
| 갭 | — | 레거시 step32가 Service 계약을 깨뜨림(`PaperAccountService(session)` 버그 — DB 감사와 동일) |

### 2.3 DTO

| 위치 | 내용 |
|------|------|
| `api/v1/*.py` 내 `BaseModel` | ~107 — Request/Response가 라우터에 인라인 |
| 공통 응답 Envelope | **성공 응답 통일 스키마 없음** (dict/모델 혼재) |
| 에러 Envelope | `{code,message,detail,request_id}` — exception_handlers |

### 2.4 Entity

| 위치 | 내용 |
|------|------|
| `*models.py` / `*entities.py` | ORM 81 테이블 매핑 |
| API Entity 분리 | 없음 — ORM/Entity를 서비스가 직접 사용, API는 DTO 변환 |

---

# 확인사항

각 항목: **위치 / 문제 / 영향도 / 수정방법**  
영향도: Critical · High · Medium · Low

---

## 3. 404

### 3.1 정상 404 (의도)

| 항목 | 내용 |
|------|------|
| **위치** | `account_ownership.py`, `user_*`, `paper_accounts`, `market_data_router` 등 `HTTP_404_NOT_FOUND` |
| **문제** | 없음 — 리소스 부재/소유권 위장 시 404·403 사용 |
| **영향도** | — |
| **수정방법** | 소유권 실패는 403 vs 404 정책을 문서에 고정 (현재 혼재). |

### 3.2 라우트 미존재 → FastAPI 기본 404

| 항목 | 내용 |
|------|------|
| **위치** | 미등록 경로 · `indicator` 미마운트 |
| **문제** | 기본 `{"detail":"Not Found"}` — 통일 error envelope와 불일치 가능 |
| **영향도** | Low |
| **수정방법** | 404도 `HTTPException` 핸들러 경로로 맞추는지 확인(Starlette 기본과의 차이 문서화). |

### 3.3 501로 위장한 “죽은” 엔드포인트

| 항목 | 내용 |
|------|------|
| **위치** | `market_data_router.py` `POST /market/sync/upbit|kiwoom/day/{symbol}` → **501 NOT_IMPLEMENTED** |
| **문제** | OpenAPI에 살아 있으나 항상 501. 클라이언트 혼란. |
| **영향도** | Medium |
| **수정방법** | 제거하거나 302/문서 링크만 남기고 deprecate. |

---

## 4. 500

| 항목 | 내용 |
|------|------|
| **위치** | `exception_handlers` bare `Exception` → `INTERNAL_ERROR` / 500 · `paper_accounts` 일부 명시 500 · 무인증 파이프라인/sync 예외 미포장 |
| **문제** | DomainError 미사용 경로에서 스택이 500으로만 보임. prod는 메시지 일반화(양호). |
| **영향도** | Medium |
| **수정방법** | 서비스 예외를 DomainError/NotFound/Conflict로 승격. 라우터 `except Exception` 남용 금지. |

### 4.1 step32 런타임 500

| 항목 | 내용 |
|------|------|
| **위치** | `step32_router.apply_execution` → `PaperAccountService(session)` (생성자 불일치) |
| **문제** | 호출 시 AttributeError → 500 |
| **영향도** | Critical (해당 API) |
| **수정방법** | 라우터 제거가 최선. |

---

## 5. 예외처리

| 항목 | 내용 |
|------|------|
| **위치** | `api/exception_handlers.py` |
| **문제** | DomainError·Broker/Kiwoom/Upbit/Dart/Ollama/Naver·Validation·HTTP·Exception 커버. 다만 라우터는 `HTTPException(detail=str)` 남발로 `code=HTTP_4xx`만 부여. Rate limit도 HTTP 429 → `HTTP_429`. |
| **영향도** | Medium |
| **수정방법** | 도메인별 `code` 상수 사용. `AuthError` 등도 DomainError 계열로 통일. |

### 공통 Error Envelope (현재)

```json
{
  "code": "STRING",
  "message": "sanitized",
  "detail": null,
  "request_id": "..."
}
```

---

## 6. JWT

| 항목 | 내용 |
|------|------|
| **위치** | `auth/deps.get_current_user` · `JwtTokenService` · Bearer `HTTPBearer` |
| **문제** | Access JWT 검증·활성 유저 확인은 견고. Refresh 로테이션은 auth 서비스. 다만 **대량 라우터가 JWT 자체를 요구하지 않음**. |
| **영향도** | Critical (표면) / Low (구현 품질) |
| **수정방법** | 기본 deny: 라우터 그룹 단위 `dependencies=[Depends(get_current_user|require_admin)]`. |

### JWT 관련 설정

| 항목 | 내용 |
|------|------|
| **위치** | `settings.jwt_*`, `JWT_DEV_AUTO_SECRET` |
| **문제** | prod는 secret 필수. local auto-secret 가능. |
| **영향도** | Medium |
| **수정방법** | 운영 체크리스트 유지. |

---

## 7. 권한 (RBAC / Admin Key)

| 항목 | 내용 |
|------|------|
| **위치** | `require_permission`, `require_admin`, `require_authenticated`, `X-Admin-API-Key` |
| **문제** | (1) **46개 무인증 POST** (2) User mutate 다수가 `trading:read`만 요구 (watchlist/settings/notifications/profile) (3) DEV_OPEN은 제거됨(양호) |
| **영향도** | **Critical** / Medium(RBAC 왜곡) |
| **수정방법** | mutate → `trading:write` 또는 세분 permission. 운영 API는 `require_admin`. |

### Critical 무인증 mutate (발췌)

| Method Path | Router |
|-------------|--------|
| `POST /api/v1/positions/executions` | step32 |
| `POST /api/v1/strategy-runtime-switch` | strategy_runtime_switch |
| `POST /api/v1/pipelines/daily-strategy` | pipelines |
| `POST /api/v1/guarded-pipelines/daily-strategy` | guarded_pipeline |
| `POST /api/v1/sync/kiwoom/daily` | sync |
| `POST /api/v1/upbit/*/sync*` | upbit |
| `POST /api/v1/dart/sync`, `/corps/sync` | dart |
| `POST /api/v1/news/sync`, `/summarize` | news |
| `POST /api/v1/realtime-quotes/upbit/start\|stop` | realtime_quotes |
| `POST /api/v1/risk/position-plan`, `/exit-decision` | risk |
| AI / backtest / walk-forward / indicators compute | 다수 |

보호 양호 예: `order_execution`(`trading:write`+ownership), `kill_switch`(admin), `broker_orders`(admin), User STEP65–73(JWT).

---

## 8. Rate Limit

| 항목 | 내용 |
|------|------|
| **위치** | `common/rate_limit.py` 인메모리 슬라이딩 윈도우 · IP 키 |
| **문제** | 적용: login/refresh/change-password, notification test, telegram webhook, profile 민감 변경. **주문·sync·backtest·AI·signup 미적용**. 멀티 워커 시 카운터 공유 안 됨. |
| **영향도** | High |
| **수정방법** | 고비용/공개 POST에 일괄 적용. Redis 등 공유 스토어 검토. |

---

## 9. Logging

| 항목 | 내용 |
|------|------|
| **위치** | `RequestContextMiddleware` (structlog `request_id`/`path`/`method`) · `lifecycle` · `exception_handlers` 500 시 `logger.exception` · AuditLogService(부분) |
| **문제** | 요청 access log 미들웨어는 컨텍스트만. 전 엔드포인트 감사 로그 아님. kill/settings/auth/telegram/profile 등만 audit.record. |
| **영향도** | Medium |
| **수정방법** | mutate admin API에 audit 필수. access log( status/latency ) 옵션. |

---

## 10. Swagger

| 항목 | 내용 |
|------|------|
| **위치** | `main.py` `docs_url=/docs`, `redoc_url=/redoc` — **production에서는 None** |
| **문제** | non-prod만 노출(양호). 커스텀 Swagger UI 설정 없음. |
| **영향도** | Low |
| **수정방법** | 현행 유지. 스테이징에서만 필요 시 Basic Auth. |

---

## 11. OpenAPI

| 항목 | 내용 |
|------|------|
| **위치** | `/openapi.json` (non-prod) · `collect_duplicate_operation_ids()`는 **정의만 있고 create_app 미호출** · `custom_openapi`/security scheme 명시 없음 |
| **문제** | Bearer/Admin-Key가 스키마에 일관 표기되지 않을 수 있음. operationId 중복 검사 미가동. |
| **영향도** | Medium |
| **수정방법** | OpenAPI securitySchemes 추가. 기동/CI에서 duplicate operationId assert. |

---

## 12. 응답 규격

| 항목 | 내용 |
|------|------|
| **위치** | 성공: 라우터별 dict/`response_model` 혼재 · 에러: 공통 envelope · 204 logout/change-password |
| **문제** | 성공 응답에 `code`/`request_id` 없음. 목록 페이징 필드명 불통일 가능(`items`/`total` 등). |
| **영향도** | Medium |
| **수정방법** | 성공 Envelope 또는 최소 `request_id` 헤더(이미 X-Request-ID) 문서화. 목록 스키마 표준화. |

---

## 13. Error Code

| Code | 출처 |
|------|------|
| `DOMAIN_ERROR`, `VALIDATION_ERROR`, `NOT_FOUND`, `CONFLICT`, `EXTERNAL_API_ERROR`, `PERMISSION_DENIED` | `common.exceptions.DomainError` 계열 |
| `BROKER_ERROR`, `KIWOOM_API_ERROR`, `UPBIT_API_ERROR`, `DART_API_ERROR`, `OLLAMA_API_ERROR`, `NAVER_API_ERROR` | exception_handlers |
| `INTERNAL_ERROR` | bare Exception |
| `HTTP_{status}` | HTTPException 일괄 |

| 항목 | 내용 |
|------|------|
| **위치** | 위 + 라우터 문자열 detail |
| **문제** | 카탈로그/버전 관리 문서 없음. HTTP_* 남발로 클라이언트 분기 어려움. User AI/Disclosure는 429/503을 HTTPException으로 직접. |
| **영향도** | Medium |
| **수정방법** | `docs/ERROR_CODES.md` + DomainError 우선. 429 → `RATE_LIMITED` 코드. |

---

## 14. 중복 API

| 중복 | 위치 | 영향도 | 수정방법 |
|------|------|--------|----------|
| Paper 체결 이중 경로 | 인증 `paper-*`/`order-execution` vs 무인증 `POST /positions/executions` (step32) | **Critical** | step32 제거 |
| Sync 이중 | `/api/v1/sync/kiwoom/daily` vs `/market/sync/kiwoom/day/{symbol}`(501) vs upbit sync 다수 | High | 단일 sync API로 수렴 |
| Pipeline 이중 | `/pipelines/daily-strategy` vs `/guarded-pipelines/daily-strategy` | High | 하나로 통합 + auth |
| Risk 표면 분열 | `/risk/*` 무인증 vs `/risk/kill-switch` 인증 vs `/risk-policies` admin | High | 라우터 단위 인증 |
| Orders prefix 공유 | `orders`, `order_cancel_replace`, `order_dispatch`, `order_states` | Low | 문서화(경로 분리면 OK) |
| Notification | `/notification` vs `/user/notifications` | Low | 역할 문서화 |
| Indicator | `/indicator`(미등록) vs `/indicators` | Low | 파일 삭제 |
| Dashboard | `/dashboard`, `/dashboard/risk`, strategy dashboards | Medium | 무인증 GET 잠금 |

---

## 15. 미사용 API

| 항목 | 내용 |
|------|------|
| **위치** | `indicator_router` 미등록 · `market` sync alias 501 · FE `userApi` 고아 ~24 · Admin 일부 export 미연결 · step32 deprecated나 **등록·호출 가능** |
| **문제** | OpenAPI/공격면에 죽은·위험한 엔드포인트 잔존. FE 미사용 ≠ 서버 미노출. |
| **영향도** | High (step32/무인증) / Low (FE orphan) |
| **수정방법** | 서버에서 unmount. FE orphan은 클라이언트 정리. “planned”는 docs만. |

### FE 관점 미사용 (참고)

이전 FE 감사: `userApi` 미사용 예 — `getHealth`, `syncNews`, `summarizeNews`, `getRealtimeQuotesStatus`, `testNotification` 등. 서버 API는 여전히 존재·일부 무인증.

---

## Router별 Auth 매트릭스 (요약)

| Auth | Router 예 |
|------|-----------|
| **공개(의도)** | health, version, auth signup/login/refresh/logout |
| **JWT permission** | user_*, orders(list), order_execution, paper(일부), notification |
| **Admin / API Key** | monitoring, broker_*, kiwoom config, kill-switch POST, jobs, settings write, many realtime_* |
| **NONE (문제)** | step32, sync, pipelines, guarded_pipeline, upbit, dart, news, indicators, ai_*, backtest*, walk_forward*, risk(일부), realtime_quotes, strategy_runtime_switch, strategy_selector/performance/leaderboard POST, market_data, prices, … |

---

## 우선순위 백로그

1. **P0** — step32 unmount · pipelines/sync/upbit/dart/runtime-switch/risk mutate에 `require_admin` · PaperAccountService 버그 경로 차단  
2. **P1** — 나머지 무인증 POST 인증 · Rate limit 확대 · User mutate permission을 write로 교정  
3. **P2** — Error code 카탈로그 · OpenAPI securitySchemes · audit 범위 확대 · 501 alias 제거  
4. **P3** — 성공 응답 규격 · FE orphan API · indicator_router 삭제 · duplicate operationId CI  

---

## 결론

API **코어(Auth·User STEP65–73·Order Execution·Kill Switch·Admin 다수)** 는 JWT/RBAC가 동작한다.  
출시 차단 수준 이슈는 **등록된 채 남아 있는 무인증 mutate 표면(~46 POST)** 과 **step32 paper fill 우회**, **Rate limit/감사 로그 편중**, **성공·에러 코드 규격 불균일**이다.

본 문서는 감사 전용이며 **코드 변경을 포함하지 않는다.**
