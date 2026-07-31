# README_FINAL_AUDIT.md — 증권사 납품 기준 최종 평가

| 항목 | 내용 |
|------|------|
| **평가일** | 2026-07-21 |
| **평가 기준** | **실제 증권사에 납품** (Live 주문·고객자산·감사·규제 대응 가정) |
| **평가자 관점** | Senior Software Architect / Security & Trading Systems |
| **코드 수정** | **없음** (관찰·점수만) |
| **근거 문서** | `README_AUDIT_01.md`, `README_AUDIT_DB.md`, `README_AUDIT_API.md`, `README_AUDIT_TEST.md`, `PROJECT_FINAL_AUDIT.md`, 릴리즈 v1.1.0 산출물 |

---

## 총평

| 지표 | 결과 |
|------|------|
| **종합 점수 (가중)** | **51 / 100** |
| **단순 평균** | **48 / 100** |
| **납품 판정** | **NO-GO (부적합)** — Live·다중고객·대외망 납품 불가 |
| **조건부 가능 범위** | 내부망 · Paper 전용 · 단일 운영자 데모 (별도 계약/면책) |
| **한 줄** | 제품 골격·User/Admin·주문 가드·문서화는 있으나, **무인증 mutate API·DB 무결성 구멍·CI/커버리지 부재**로 증권사 납품 기준을 충족하지 못한다. |

### 가중치 (증권사 납품 RFP 가정)

| 항목 | 가중 | 점수 | 기여 |
|------|-----:|-----:|-----:|
| 보안 | 15% | 28 | 4.2 |
| 테스트 | 12% | 35 | 4.2 |
| 아키텍처 | 10% | 62 | 6.2 |
| DB | 10% | 55 | 5.5 |
| API | 10% | 40 | 4.0 |
| 운영 | 10% | 50 | 5.0 |
| 성능 | 8% | 48 | 3.8 |
| 유지보수 | 8% | 52 | 4.2 |
| 확장성 | 7% | 45 | 3.2 |
| 예외처리 | 5% | 58 | 2.9 |
| 가독성 | 5% | 70 | 3.5 |
| CI/CD | 5% | 15 | 0.8 |
| 문서화 | 5% | 72 | 3.6 |
| **합계** | **100%** | — | **≈ 51** |

### 등급 해석

| 점수대 | 의미 (납품) |
|--------|-------------|
| 90–100 | 즉시 납품 가능 (잔여 Low만) |
| 75–89 | 조건부 납품 (P0 해소 후 UAT) |
| 60–74 | PoC/파일럿만 |
| **50 미만** | **납품 거부** |

본 프로젝트는 **51점 → 경계선 하위**. P0 전량 해소 전에는 증권사 인수 테스트(UAT/보안성 검토) 통과를 기대하기 어렵다.

---

## 항목별 평가

각 항목: **점수 / 감점 이유 / 위험도 / 우선순위**

위험도: Critical · High · Medium · Low  
우선순위: P0–P3 (항목 대표 우선순위; 세부 조치는 하단 Backlog)

---

### 1. 아키텍처 — **62 / 100**

| 필드 | 내용 |
|------|------|
| **점수** | 62 |
| **감점 이유** | FastAPI·스키마 분리·Service/Repository 골격은 양호. 그러나 `broker`/`brokers`, `market`/`markets` 이중 스택, `broker↔order` 등 순환 의존, deprecated `step32`가 본선과 동일 prefix에 공존, Realtime/Admin `account_id=1` 하드코딩, AutomaticScheduler vs lifecycle 역할 불명확. |
| **위험도** | High |
| **우선순위** | P1 (구조 부채) / P0에 step32 제거 포함 |

**잘된 점:** 도메인 스키마(auth/trading/operation…) · Outbox·Kill Switch·User ownership(STEP65+) · ExitMonitor lifecycle 연결.

---

### 2. 보안 — **28 / 100**

| 필드 | 내용 |
|------|------|
| **점수** | 28 |
| **감점 이유** | 증권사 납품에서 **실격 수준**. 무인증 mutate POST **약 46개**(step32 paper fill, pipelines, sync, strategy-runtime-switch, upbit/dart/news sync, risk plan 등). FE 토큰 localStorage, Next middleware 부재, Rate limit 4파일만, CSRF 없음(Bearer 전제). DEV_OPEN 제거·order-execution 인증·JWT 코어는 개선됐으나 **공격면이 열려 있으면 무의미**. |
| **위험도** | **Critical** |
| **우선순위** | **P0** |

**잘된 점:** JWT/Refresh 로테이션, RBAC 시드, prod JWT_SECRET/ADMIN_API_KEY fail-closed, kill-switch·broker_orders admin 게이트, live+mock 교차 검증.

---

### 3. DB — **55 / 100**

| 필드 | 내용 |
|------|------|
| **점수** | 55 |
| **감점 이유** | 스키마 83테이블·timestamptz 일관·Alembic head 일치는 양호. **FK 50개로 논리 `*_id` 대비 대량 누락**(전략 배포 그래프, preference default, trading_order 참조). **`paper_order`에 account_id 자체 부재** — 멀티계좌 격리 불가. instrument/user CASCADE 파괴력, comment/audit 컬럼 희소, 빈 `broker`/`common` 스키마. |
| **위험도** | Critical (`paper_order`) · High (FK/CASCADE) |
| **우선순위** | **P0** (account_id/FK) · P1 (CASCADE·인덱스) |

---

### 4. API — **40 / 100**

| 필드 | 내용 |
|------|------|
| **점수** | 40 |
| **감점 이유** | Endpoint ~327·User API는 성숙. 그러나 인증 불균일, paper vs step32 이중 경로, 501 alias 잔존, 성공 응답 Envelope 부재, Error code `HTTP_*` 남발, OpenAPI securitySchemes 미정비. 증권사 관점 “API 보안=제품 보안”. |
| **위험도** | **Critical** |
| **우선순위** | **P0** (auth gate) · P1 (규격 통일) |

---

### 5. 예외처리 — **58 / 100**

| 필드 | 내용 |
|------|------|
| **점수** | 58 |
| **감점 이유** | 공통 `{code,message,detail,request_id}` + sanitize는 강점. DomainError 계층 존재. 다만 라우터 HTTPException 남발, Rate limit/Auth가 `HTTP_429`/`HTTP_401`로만 표기, 도메인 코드 카탈로그·버전 관리 없음, 일부 경로 bare 500. |
| **위험도** | Medium |
| **우선순위** | P2 |

---

### 6. 성능 — **48 / 100**

| 필드 | 내용 |
|------|------|
| **점수** | 48 |
| **감점 이유** | 무인증 고비용 POST(backtest/AI/sync) DoS 가능, market limit 5000급, sync Session in async 루프 블로킹, 인메모리 rate limit(멀티워커 무효), 부하/성능 테스트·풀 사이즈 운영 가이드 약함. |
| **위험도** | High |
| **우선순위** | P1 (auth+rate limit) · P2 (부하측정) |

---

### 7. 테스트 — **35 / 100**

| 필드 | 내용 |
|------|------|
| **점수** | 35 |
| **감점 이유** | 441 collect·FE 55 PASS는 양적 자산. **pytest-cov 미설치·커버리지 게이트 0**. 진짜 DB integration 부재, step40 “E2E”는 Mock, 무인증 API 보안 테스트 없음, Race/동시성 0, FE 페이지/Playwright 0, MagicMock 과다(STEP68–73). 증권사는 **증적 가능한 품질**을 요구. |
| **위험도** | High |
| **우선순위** | **P0** (cov+보안테스트) · P1 (DB integration/E2E) |

---

### 8. 유지보수 — **52 / 100**

| 필드 | 내용 |
|------|------|
| **점수** | 52 |
| **감점 이유** | STEP 아카이브·매뉴얼은 강점. 이중 패키지·dead `indicator_router`·FE orphan API·레거시 alembic overlay·미구현 UI 배너 혼재로 인지 부하. 신규 인력 온보딩 시 “어느 길이 본선인가” 불명확. |
| **위험도** | Medium |
| **우선순위** | P2 |

---

### 9. 확장성 — **45 / 100**

| 필드 | 내용 |
|------|------|
| **점수** | 45 |
| **감점 이유** | Outbox SKIP LOCKED 설계는 수평 확장 힌트나 **동시성 미검증**. Rate limit 단일 프로세스, ENV/backup 경로 머신 고정(`E:\StockTrading\...`), Docker/compose 없음, 멀티테넌시(증권 고객사 N) 모델 미정. |
| **위험도** | High |
| **우선순위** | P1–P2 |

---

### 10. 가독성 — **70 / 100**

| 필드 | 내용 |
|------|------|
| **점수** | 70 |
| **감점 이유** | 한글 주석·명확한 변수명·도메인 용어가 대체로 일관. 감점: 라우터 인라인 DTO 과다, 셸/Alert 컴포넌트 중복, 일부 거대 page.tsx. |
| **위험도** | Low |
| **우선순위** | P3 |

---

### 11. 운영 — **50 / 100**

| 필드 | 내용 |
|------|------|
| **점수** | 50 |
| **감점 이유** | 설치/운영/장애/DB/관리자/사용자 매뉴얼 존재, Kill Switch·monitoring·audit 일부·Telegram ops. 웹 Backup dump/Restore·앱 로그 테일 미구현, Quiet Time 등은 개선. 증권 운영(장애등급·RTO/RPO·교대 런북)에는 추가 공백. |
| **위험도** | High |
| **우선순위** | P1 (백업/복구 공식화) · P2 (로그 테일) |

---

### 12. CI/CD — **15 / 100**

| 필드 | 내용 |
|------|------|
| **점수** | 15 |
| **감점 이유** | 레포 내 **GitHub Actions / Jenkins / Dockerfile / compose 0건**. 테스트·린트·마이그레이션·이미지 빌드 자동화 증적 없음. 증권사 납품 시 “재현 가능한 빌드·배포 파이프라인”이 필수. |
| **위험도** | **Critical** (납품 프로세스) |
| **우선순위** | **P0** |

---

### 13. 문서화 — **72 / 100**

| 필드 | 내용 |
|------|------|
| **점수** | 72 |
| **감점 이유** | `docs/manual/*`, STEP README, CHANGELOG/Release, 감사 문서가 풍부 — **최고 점수 구간**. 감점: 구감사와 현행(STEP65–75) 불일치 잔존, ERROR_CODES 카탈로그 없음, OpenAPI를 계약서로 쓰기엔 security 표기 부족. |
| **위험도** | Low–Medium |
| **우선순위** | P2 (동기화) · P3 (카탈로그) |

---

## 항목 점수 한눈에

```
보안      ████░░░░░░  28  Critical  P0
CI/CD     ██░░░░░░░░  15  Critical  P0
테스트    ███░░░░░░░  35  High      P0
API       ████░░░░░░  40  Critical  P0
확장성    ████░░░░░░  45  High      P1
성능      ████░░░░░░  48  High      P1
운영      █████░░░░░  50  High      P1
유지보수  █████░░░░░  52  Medium    P2
DB        █████░░░░░  55  Critical  P0
예외처리  ██████░░░░  58  Medium    P2
아키텍처  ██████░░░░  62  High      P1
가독성    ███████░░░  70  Low       P3
문서화    ███████░░░  72  Low       P2
────────────────────────────────
가중 종합              51  NO-GO
```

---

## P0 / P1 / P2 / P3 Backlog

증권사 납품 전 **반드시** 아래 순서로 해소.

### P0 — 납품 차단 (해소 전 UAT/보안성 검토 불가)

| ID | 주제 | 근거 | 완료 조건(증적) |
|----|------|------|-----------------|
| P0-1 | 무인증 mutate API 전면 차단 | API 감사 46 POST · step32 fill | `require_admin`/`require_permission` + 보안 pytest 401 행렬 PASS |
| P0-2 | `step32_router` 언마운트 | 본선 paper/order 우회 · 런타임 버그 | router 미등록 · OpenAPI에 경로 없음 |
| P0-3 | `paper_order.account_id` + FK | DB 감사 Critical | 마이그레이션 + ownership 테스트 |
| P0-4 | 전략/주문/preference 핵심 FK | orphan ID 위험 | FK+인덱스 적용 · orphan 정리 |
| P0-5 | CI 파이프라인 | Actions/Docker 0 | PR마다 lint+pytest(+cov 최소)+typecheck |
| P0-6 | pytest-cov + 보안 테스트 | coverage 도구 없음 | CI fail-under + Critical API 401 테스트 |
| P0-7 | Live 주문 이중 게이트 증적 | 설정 실수 위험 | Live 체크리스트 서명 + mock/live 교차 테스트 |

### P1 — 납품 직전 필수 (인수 전 완료)

| ID | 주제 | 근거 |
|----|------|------|
| P1-1 | Rate limit을 고비용/공개 POST·주문에 확대 | DoS |
| P1-2 | FE middleware + httpOnly 쿠키(또는 동등 BFF) | XSS 토큰 |
| P1-3 | `account_id=1` 제거 (Admin/Realtime) | 오주문 |
| P1-4 | instrument/user CASCADE → RESTRICT + soft delete 정책 | 대량삭제 |
| P1-5 | 진짜 DB integration 스위트 | FK/트랜잭션 |
| P1-6 | Outbox SKIP LOCKED 동시성 테스트 | Race |
| P1-7 | Backup/Restore RTO 공식화 (CLI 절차 서명 또는 보호 API) | 운영 |
| P1-8 | 이중 패키지(`broker`/`brokers`) 통합 로드맵 착수 | 유지보수 |
| P1-9 | User mutate permission `trading:read` → write 교정 | RBAC |
| P1-10 | Docker/compose 또는 증권사 표준 배포 산출물 | 납품물 |

### P2 — 안정화·인수 후 1차

| ID | 주제 |
|----|------|
| P2-1 | Error code 카탈로그 · DomainError 통일 |
| P2-2 | 성공 응답/페이징 규격 |
| P2-3 | OpenAPI securitySchemes · duplicate operationId CI |
| P2-4 | Playwright E2E (login→계좌→주문) |
| P2-5 | realtime runner/WS 재연결 테스트 |
| P2-6 | 앱 로그 테일/운영센터 완성 |
| P2-7 | MagicMock STEP 테스트 → fake/DB 치환 |
| P2-8 | 감사 문서·구 PROJECT_FINAL_AUDIT 동기화 |
| P2-9 | 부하 테스트(시나리오·한계점 문서) |

### P3 — 품질·위생

| ID | 주제 |
|----|------|
| P3-1 | dead `indicator_router`·FE ComingSoon/orphan API 삭제 |
| P3-2 | DB COMMENT 배치 |
| P3-3 | 컴포넌트 셸 통합 · page 분할 |
| P3-4 | 미구현 UI 배너 숨김/스펙 고정 |
| P3-5 | alembic overlay 경로 “적용 금지” 명시 |
| P3-6 | Starlette TestClient deprecation 해소 |

---

## 납품 시나리오별 판정

| 시나리오 | 판정 | 조건 |
|----------|------|------|
| **증권사 Live 자동매매 · 대고객** | **NO-GO** | P0 전량 + 보안성 검토·모의침투·감사 로그 요건 추가 |
| **증권사 Paper/파일럿 · 폐쇄망** | **CONDITIONAL** | P0-1~P0-6 필수, Live 플래그 하드웨어/설정 잠금 |
| **내부 PoC · 데모** | **GO (제한)** | VPN + mock 전제, 면책 고지 |

---

## 강점 (유지할 자산)

1. User/Admin 풀스택와 STEP65–75 소유권·알림·설정·프로필  
2. Order execution + Outbox + Kill Switch + live/mock 게이트  
3. JWT/RBAC 코어 · prod secret fail-closed  
4. PostgreSQL 스키마 분리 · Alembic 단일 head · timestamptz  
5. 운영·설치·장애 매뉴얼 및 풍부한 STEP/감사 문서  
6. 단위 테스트 양(441+) · 브로커 매퍼 테스트 밀도  

---

## 최종 권고

1. **지금은 “납품 후보”가 아니라 “보안·무결성 보강 중인 플랫폼”**으로 위치시킬 것.  
2. **P0만 닫아도** 가중 점수 추정치 **~65–70** 구간(파일럿 가능)까지 상승 가능.  
3. 증권사 제출 시 첨부: 본 문서 + API/DB/TEST 감사 + Live 체크리스트 서명본 + CI 뱃지.  
4. **코드 변경은 본 평가에 포함하지 않았다.** 다음 단계는 P0 구현 스프린트.

---

## 서명란 (인수 시)

| 역할 | 성명 | 일자 | 판정 |
|------|------|------|------|
| 아키텍트 | | | |
| 보안 | | | |
| 인프라/CI | | | |
| 고객(증권사) | | | **합격 / 조건부 / 불합격** |

**현재 권고 판정: 불합격 (NO-GO) — P0 미해소.**
