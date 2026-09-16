# STEP NUMBER MAPPING — 2026-07-31

**규칙:** 같은 숫자라도 네임스페이스가 다르면 **절대 합치지 않는다.**

---

## 1. 네임스페이스 3종 (+α)

| NS ID | 이름 | 위치 | 의미 |
|-------|------|------|------|
| NS-MAIN | 메인 빌드 시퀀스 | `docs/archive/steps/README_STEP16–75` | 제품 연대기 |
| NS-AUDIT21 | 21단계 코드 감사 | `docs/audit/STEP01–21` | 2026-07 감사 체크리스트 |
| NS-SUB | 활성 서브시리즈 | development/ai/tests | 현재 개발 단위 |
| NS-ROOT | 루트 README_STEP5x | 루트 | 릴리스 마일스톤 서술 |

---

## 2. 충돌 표 (동일 숫자 ≠ 동일 기능)

| Label | NS-AUDIT21 | NS-MAIN/Archive | NS-SUB (Canonical) |
|-------|------------|-----------------|---------------------|
| STEP8 | Risk/Kill 감사 | (해당 약함) | **STEP8-x 브로커/계좌/LIVE** `docs/development/` |
| STEP10 | Kiwoom 감사 | — | **STEP10-x Runtime/Ops/Telegram** `docs/operations/` |
| STEP11 | Upbit 감사 | — | **STEP11-x AI Provider→Lifecycle** `docs/ai/` |
| STEP12 | Paper Trading 감사 | — | **STEP12-x Strategy Request→Readiness** tests/code (docs 부재) |
| STEP13 | Market/strategy 감사 | STEP33 market engine (제거) | **미배정** — 신규는 `STEP13-*` 접두 명확화 |
| STEP28 | — | Kiwoom REST | 코드에 흡수 |
| STEP32 | — | Engine overlay | deprecated/tombstone |
| STEP33 | — | Market overlay | removed STEP56 |
| STEP60 | — | Windows deploy | ops/INSTALL |
| STEP62 | — | Security harden | middleware + tests |

---

## 3. Canonical Step ID 제안

형식: `{SERIES}-{MAJOR}[-{MINOR}]` + 문서 경로 고정.

| Historical | Canonical ID | SoT 문서/코드 |
|------------|--------------|---------------|
| Audit STEP08 | `AUDIT21-08` | `docs/audit/STEP08_*.md` |
| Dev STEP8-5-22 | `DEV-8.5.22` | `docs/development/README_STEP8_*` |
| AI STEP11-13 | `AI-11.13` | `docs/ai/STEP11_13_*` |
| Strategy STEP12-20 | `STRAT-12.20` | `tests/test_step12_20_*` + future docs |
| Archive STEP28 | `HIST-28` | archive only |
| Root STEP62 | `REL-62` | SECURITY docs |

신규 작업 시 **이슈/커밋/폴더에 Canonical ID를 병기**.

---

## 4. STEP12 (Strategy) 세부 맵 (워킹트리)

| Sub | 제목 | 상태 | Migration/Test |
|-----|------|------|----------------|
| 12-1 | Strategy Request | WIP uncommitted | bfc6… / test_step12_1 |
| 12-1a | Request review gate | WIP | |
| 12-2-1 | Draft domain | WIP | 5b999… |
| 12-2-2 | Draft generation | WIP | 89de… |
| 12-2-3 | Draft review | WIP | |
| 12-3 | Draft approval | WIP | 6d736… |
| 12-4…12-15 | Snapshot…Decision | WIP | 다수 |
| 12-16/16r | Promotion commit/state | WIP | |
| 12-17 | Activation | WIP | |
| 12-18 | Runtime registration | WIP | |
| 12-19 | Deployment readiness | WIP | |
| 12-20 | Operation readiness | WIP | a7f3… head |

**과거 Audit STEP12 (Paper)** 와 혼동 금지 → Canonical `AUDIT21-12` vs `STRAT-12.x`.

---

## 5. 앞으로 번호 배정 규칙 (제안)

1. 새 기능은 기존 활성 시리즈에만 붙인다 (DEV-8 / AI-11 / STRAT-12).  
2. 시리즈가 끝나면 **새 시리즈 이름**을 쓰고 숫자만 재사용하지 않는다.  
3. Audit21 번호는 신규 개발에 재사용 금지.  
4. `STEP_MASTER_STATUS.md` (PHASE2)가 유일한 상태 SoT.

---

## 6. 문서 보존

| 유형 | 보존 |
|------|------|
| NS-SUB docs | ACTIVE |
| NS-AUDIT21 | HISTORICAL (수정 최소화) |
| NS-MAIN archive | HISTORICAL |
| 완료보고 | `docs/archive/completion-reports/` (PHASE3 이동) |
