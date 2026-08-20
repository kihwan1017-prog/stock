# Documentation Index — stock-platform

> v1.0.0 · Docker 미사용 · PostgreSQL Windows 서비스  
> 루트 포털: [../README.md](../README.md) · AI SoT: [../AGENTS.md](../AGENTS.md)

## Canonical Source of Truth (PHASE 2)

| 문서 | 역할 |
|------|------|
| [CURRENT_WORK.md](CURRENT_WORK.md) | 현재 작업만 |
| [PROJECT_IMPLEMENTATION_STATUS.md](PROJECT_IMPLEMENTATION_STATUS.md) | 구현 현황 SoT |
| [STEP_MASTER_STATUS.md](STEP_MASTER_STATUS.md) | STEP 상태 SoT |
| [ROADMAP.md](ROADMAP.md) | P0–P5 잔여 작업 |
| [DECISION_LOG.md](DECISION_LOG.md) | 장기 설계 결정 |
| [AI_PROJECT_CONTEXT.md](AI_PROJECT_CONTEXT.md) | AI 프로젝트 컨텍스트 |
| [AI_ARCHITECTURE.md](AI_ARCHITECTURE.md) | 실행 흐름·GAP |
| [AI_DEVELOPMENT_WORKFLOW.md](AI_DEVELOPMENT_WORKFLOW.md) | 개발 Gate |
| [AI_CODING_RULE.md](AI_CODING_RULE.md) | 코딩 규칙 |
| [AI_DB_RULE.md](AI_DB_RULE.md) | DB/Alembic |
| [AI_TEST_RULE.md](AI_TEST_RULE.md) | 테스트 |
| [AI_SECURITY_RULE.md](AI_SECURITY_RULE.md) | 보안 |
| [AI_TRADING_SAFETY.md](AI_TRADING_SAFETY.md) | LIVE/PAPER 안전 |
| [architecture/STRATEGY_LIFECYCLE_STEP12.md](architecture/STRATEGY_LIFECYCLE_STEP12.md) | Strategy STEP12 |
| [audit/PHASE2_DOCUMENTATION_STANDARDIZATION_REPORT_20260731.md](audit/PHASE2_DOCUMENTATION_STANDARDIZATION_REPORT_20260731.md) | PHASE 2 완료보고 |

운영: UPBIT UBA1380 24x7 **COMPLETED** (controlled session) · 플랫폼 LIVE: P0·KIWOOM 잔여로 **NOT APPROVED**. 상세는 IMPLEMENTATION_STATUS.

## Domain folders

| Folder | Purpose |
|--------|---------|
| [manual/](manual/) | **운영·사용자 매뉴얼** (제품 사용 시작점) |
| [architecture/](architecture/) | 시스템 아키텍처·도메인 맵 |
| [backend/](backend/) | FastAPI API 개요 |
| [frontend/](frontend/) | Admin 웹 문서 포인터 |
| [database/](database/) | ERD·DB 규칙·Alembic |
| [deployment/](deployment/) | 설치·설정·릴리스 |
| [development/](development/) | STEP 테스트·DB 변경 계획 |
| [release/](release/) | v1.0 RC 검증·릴리즈 체크리스트 |
| [operations/](operations/) | LIVE 활성화·장애·백업 검증 |
| [security/](security/) | Secret Rotation · KI-SEC |
| [trading/](trading/) | 운영·모의·실전·장애 |
| [ai/](ai/) | AI 관련 문서 인덱스 |
| [reference/](reference/) | 로드맵·문서 인벤토리 |
| [archive/](archive/) | 과거 STEP 로그·obsolete |
| [audit/](audit/) | 전체 코드 감사·단계별 수정 산출물 |

## Quick links

- **감사 STEP01:** [audit/STEP01_PROJECT_ANALYSIS.md](audit/STEP01_PROJECT_ANALYSIS.md)
- **감사 STEP02:** [audit/STEP02_TEST_BASELINE.md](audit/STEP02_TEST_BASELINE.md)
- **감사 STEP03:** [audit/STEP03_CONFIGURATION.md](audit/STEP03_CONFIGURATION.md)
- **감사 STEP04:** [audit/STEP04_AUTH_REPOSITORY.md](audit/STEP04_AUTH_REPOSITORY.md)
- **감사 STEP05:** [audit/STEP05_EXCEPTION_MAPPING.md](audit/STEP05_EXCEPTION_MAPPING.md)
- **감사 STEP06:** [audit/STEP06_BROKER_CONSOLIDATION.md](audit/STEP06_BROKER_CONSOLIDATION.md)
- **감사 STEP07:** [audit/STEP07_ORDER_EXECUTION.md](audit/STEP07_ORDER_EXECUTION.md)
- **감사 STEP08:** [audit/STEP08_RISK_KILL_SWITCH.md](audit/STEP08_RISK_KILL_SWITCH.md)
- **감사 STEP09:** [audit/STEP09_SCHEDULER_RUNTIME.md](audit/STEP09_SCHEDULER_RUNTIME.md)
- **감사 최종 보고서:** [audit/FINAL_AUDIT_REPORT.md](audit/FINAL_AUDIT_REPORT.md)
- **감사 전체 인덱스:** [audit/README.md](audit/README.md)
- **매뉴얼 포털:** [manual/README.md](manual/README.md)
- User Web: [manual/사용자매뉴얼.md](manual/사용자매뉴얼.md)
- 키움·업비트 통합 분석: [architecture/README_KIWOOM_UPBIT_INTEGRATION_ANALYSIS.md](architecture/README_KIWOOM_UPBIT_INTEGRATION_ANALYSIS.md)
- 사용자·관리자 아키텍처 감사: [architecture/README_USER_ADMIN_ARCHITECTURE_AUDIT.md](architecture/README_USER_ADMIN_ARCHITECTURE_AUDIT.md)
- 키움·업비트 Live GO/NO-GO: [trading/LIVE_KIWOOM_UPBIT_CHECKLIST.md](trading/LIVE_KIWOOM_UPBIT_CHECKLIST.md)
- STEP 8-1 실계좌 주문 격리: [development/README_STEP8_1_BROKER_ACCOUNT_ORDER_ISOLATION.md](development/README_STEP8_1_BROKER_ACCOUNT_ORDER_ISOLATION.md)
- STEP 8-2 회원·계좌 리스크 설정: [development/README_STEP8_2_USER_ACCOUNT_RISK_SETTINGS.md](development/README_STEP8_2_USER_ACCOUNT_RISK_SETTINGS.md)
- STEP 8-3 전략 소유권: [development/README_STEP8_3_STRATEGY_OWNERSHIP.md](development/README_STEP8_3_STRATEGY_OWNERSHIP.md)
- STEP 8-4 통합 Recovery Runtime: [development/README_STEP8_4_UNIFIED_RECOVERY_RUNTIME.md](development/README_STEP8_4_UNIFIED_RECOVERY_RUNTIME.md)
- STEP 8-5-2 Broker Credential Vault: [development/README_STEP8_5_2_BROKER_CREDENTIAL_VAULT.md](development/README_STEP8_5_2_BROKER_CREDENTIAL_VAULT.md)
- STEP 8-5-3 Recovery Scheduler: [development/README_STEP8_5_3_RECOVERY_SCHEDULER.md](development/README_STEP8_5_3_RECOVERY_SCHEDULER.md)
- STEP 8-5-4 Upbit Remote-only Manual Review: [development/README_STEP8_5_4_UPBIT_RECOVERY_MANUAL_REVIEW.md](development/README_STEP8_5_4_UPBIT_RECOVERY_MANUAL_REVIEW.md)
- STEP 8-5-5 Remove Global Runtime: [development/README_STEP8_5_5_REMOVE_GLOBAL_RUNTIME.md](development/README_STEP8_5_5_REMOVE_GLOBAL_RUNTIME.md)
- STEP 8-5-5-1 Backend Regression Fix: [development/README_STEP8_5_5_1_BACKEND_REGRESSION_FIX.md](development/README_STEP8_5_5_1_BACKEND_REGRESSION_FIX.md)
- STEP 8-5-6 Distributed Recovery Lock: [development/README_STEP8_5_6_DISTRIBUTED_RECOVERY_LOCK.md](development/README_STEP8_5_6_DISTRIBUTED_RECOVERY_LOCK.md)
- STEP 8-5-7 KRX Trading Calendar: [development/README_STEP8_5_7_KRX_TRADING_CALENDAR.md](development/README_STEP8_5_7_KRX_TRADING_CALENDAR.md)
- STEP 8-5-8 Upbit Rate Limit / Retry-After: [development/README_STEP8_5_8_UPBIT_RATE_LIMIT_RETRY_AFTER.md](development/README_STEP8_5_8_UPBIT_RATE_LIMIT_RETRY_AFTER.md)
- STEP 8-5-9 Realtime Scope Registry: [development/README_STEP8_5_9_REALTIME_SCOPE_REGISTRY.md](development/README_STEP8_5_9_REALTIME_SCOPE_REGISTRY.md)
- STEP 8-5-10 Frontend Lint Zero: [development/README_STEP8_5_10_FRONTEND_LINT_ZERO.md](development/README_STEP8_5_10_FRONTEND_LINT_ZERO.md)
- STEP 8-5-11 KRX Special Session Management: [development/README_STEP8_5_11_KRX_SPECIAL_SESSION_MANAGEMENT.md](development/README_STEP8_5_11_KRX_SPECIAL_SESSION_MANAGEMENT.md)
- STEP 8-5-12 Upbit Order Idempotency: [development/README_STEP8_5_12_UPBIT_ORDER_IDEMPOTENCY.md](development/README_STEP8_5_12_UPBIT_ORDER_IDEMPOTENCY.md)
- STEP 8-5-13 KRX Session Timeline: [development/README_STEP8_5_13_KRX_SESSION_TIMELINE.md](development/README_STEP8_5_13_KRX_SESSION_TIMELINE.md)
- STEP 8-5-14 Upbit Ambiguous Resolver Scheduler: [development/README_STEP8_5_14_UPBIT_AMBIGUOUS_RESOLVER_SCHEDULER.md](development/README_STEP8_5_14_UPBIT_AMBIGUOUS_RESOLVER_SCHEDULER.md)
- STEP 8-5-15 영속 Market Session Job: [development/README_STEP8_5_15_PERSISTENT_MARKET_SESSION_JOBS.md](development/README_STEP8_5_15_PERSISTENT_MARKET_SESSION_JOBS.md)
- STEP 8-5-16 EOD Account Settlement: [development/README_STEP8_5_16_EOD_ACCOUNT_SETTLEMENT.md](development/README_STEP8_5_16_EOD_ACCOUNT_SETTLEMENT.md)
- STEP 8-5-17 Snapshot Binding & Freshness: [development/README_STEP8_5_17_SNAPSHOT_BINDING_AND_FRESHNESS.md](development/README_STEP8_5_17_SNAPSHOT_BINDING_AND_FRESHNESS.md)
- STEP 8-5-18 Account Identity Hardening: [development/README_STEP8_5_18_ACCOUNT_IDENTITY_HARDENING.md](development/README_STEP8_5_18_ACCOUNT_IDENTITY_HARDENING.md)
- STEP 8-5-19 Legacy Account Schema Removal: [development/README_STEP8_5_19_LEGACY_ACCOUNT_SCHEMA_REMOVAL.md](development/README_STEP8_5_19_LEGACY_ACCOUNT_SCHEMA_REMOVAL.md)
- STEP 8-5-20 v1.0 RC Validation: [development/README_STEP8_5_20_V1_RC_VALIDATION.md](development/README_STEP8_5_20_V1_RC_VALIDATION.md)
- STEP 8-5-21 RC Blocker Removal: [development/README_STEP8_5_21_RC_BLOCKER_REMOVAL.md](development/README_STEP8_5_21_RC_BLOCKER_REMOVAL.md)
- STEP 8-5-22 LIVE Blocker Final: [development/README_STEP8_5_22_LIVE_BLOCKER_FINAL_REMOVAL.md](development/README_STEP8_5_22_LIVE_BLOCKER_FINAL_REMOVAL.md)
- STEP 8-5-22-DBA-FIX Bootstrap: [development/README_STEP8_5_22_DBA_BOOTSTRAP_FIX.md](development/README_STEP8_5_22_DBA_BOOTSTRAP_FIX.md)
- STEP 8-5-22 Restore auth.user: [development/README_STEP8_5_22_DBA_RESTORE_AUTH_TABLE_FIX.md](development/README_STEP8_5_22_DBA_RESTORE_AUTH_TABLE_FIX.md)
- STEP 8-7 LIVE 주문 안전 게이트: [development/README_STEP8_7_LIVE_ORDER_SAFETY_GATE.md](development/README_STEP8_7_LIVE_ORDER_SAFETY_GATE.md)
- STEP 8-8 LIVE 운영 보호: [development/README_STEP8_8_LIVE_PRODUCTION_PROTECTION.md](development/README_STEP8_8_LIVE_PRODUCTION_PROTECTION.md)
- STEP 8-8A Post-Fill 재검증: [development/README_STEP8_8A_POST_FILL_REVERIFY.md](development/README_STEP8_8A_POST_FILL_REVERIFY.md)
- STEP 8-9 업비트 소액 LIVE: [development/README_STEP8_9_UPBIT_LIVE_SMOKE.md](development/README_STEP8_9_UPBIT_LIVE_SMOKE.md)
- Operation Rehearsal: [operations/README_OPERATION_REHEARSAL.md](operations/README_OPERATION_REHEARSAL.md)
- v1.0 RC Final Approval: [release/V1_0_RC_FINAL_APPROVAL.md](release/V1_0_RC_FINAL_APPROVAL.md)
- KI-SEC: [security/KI_SEC_KNOWN_ISSUES.md](security/KI_SEC_KNOWN_ISSUES.md)
- KI-TRD: [trading/KI_TRD_KNOWN_ISSUES.md](trading/KI_TRD_KNOWN_ISSUES.md)
- LIVE 활성화 체크리스트: [operations/LIVE_TRADING_ACTIVATION_CHECKLIST.md](operations/LIVE_TRADING_ACTIVATION_CHECKLIST.md)
- STEP 11-1 AI Provider Framework: [ai/STEP11_1_AI_PROVIDER_ARCHITECTURE.md](ai/STEP11_1_AI_PROVIDER_ARCHITECTURE.md)
- STEP 11-2 AI Provider Integration: [ai/STEP11_2_AI_PROVIDER_INTEGRATION.md](ai/STEP11_2_AI_PROVIDER_INTEGRATION.md)
- STEP 11-3 AI Provider Management Vault: [ai/STEP11_3_AI_PROVIDER_MANAGEMENT_VAULT.md](ai/STEP11_3_AI_PROVIDER_MANAGEMENT_VAULT.md)
- STEP 11-4 AI Prompt Policy Schema: [ai/STEP11_4_AI_PROMPT_POLICY_SCHEMA.md](ai/STEP11_4_AI_PROMPT_POLICY_SCHEMA.md)
- STEP 11-5 AI Execution Cost Tracking: [ai/STEP11_5_AI_EXECUTION_COST_TRACKING.md](ai/STEP11_5_AI_EXECUTION_COST_TRACKING.md)
- STEP 11-6 News/Disclosure Analysis: [ai/STEP11_6_NEWS_DISCLOSURE_ANALYSIS.md](ai/STEP11_6_NEWS_DISCLOSURE_ANALYSIS.md)
- STEP 11-7 Chart/Market Analysis: [ai/STEP11_7_CHART_MARKET_ANALYSIS.md](ai/STEP11_7_CHART_MARKET_ANALYSIS.md)
- STEP 11-8 AI Review/Benchmark: [ai/STEP11_8_AI_REVIEW_BENCHMARK.md](ai/STEP11_8_AI_REVIEW_BENCHMARK.md)
- STEP 11-9 AI Candidate Assessment: [ai/STEP11_9_AI_CANDIDATE_ASSESSMENT.md](ai/STEP11_9_AI_CANDIDATE_ASSESSMENT.md)
- STEP 11-10 Multi-AI Candidate Consensus: [ai/STEP11_10_MULTI_AI_CANDIDATE_CONSENSUS.md](ai/STEP11_10_MULTI_AI_CANDIDATE_CONSENSUS.md)
- STEP 11-11 AI Candidate Recommendation Queue: [ai/STEP11_11_AI_CANDIDATE_RECOMMENDATION_QUEUE.md](ai/STEP11_11_AI_CANDIDATE_RECOMMENDATION_QUEUE.md)
- STEP 11-12 Candidate Promotion Gateway: [ai/STEP11_12_CANDIDATE_PROMOTION_GATEWAY.md](ai/STEP11_12_CANDIDATE_PROMOTION_GATEWAY.md)
- STEP 11-13 AI Candidate Lifecycle: [ai/STEP11_13_AI_CANDIDATE_LIFECYCLE_PROVENANCE.md](ai/STEP11_13_AI_CANDIDATE_LIFECYCLE_PROVENANCE.md)
- 모의계좌 Soft Delete: [trading/README_PAPER_ACCOUNT_DELETE.md](trading/README_PAPER_ACCOUNT_DELETE.md)
- 모의계좌 수정: [trading/README_PAPER_ACCOUNT_UPDATE.md](trading/README_PAPER_ACCOUNT_UPDATE.md)
- Install: [manual/설치매뉴얼.md](manual/설치매뉴얼.md) · [deployment/INSTALL.md](deployment/INSTALL.md)
- Ops: [manual/운영매뉴얼.md](manual/운영매뉴얼.md) · [trading/OPERATIONS_RUNBOOK.md](trading/OPERATIONS_RUNBOOK.md) · [trading/UPBIT_UBA1380_24X7_SESSION_RENEWAL.md](trading/UPBIT_UBA1380_24X7_SESSION_RENEWAL.md) · [trading/UPBIT_FULL_MARKET_DYNAMIC_AUTOTRADING.md](trading/UPBIT_FULL_MARKET_DYNAMIC_AUTOTRADING.md)
- API: [manual/API사용매뉴얼.md](manual/API사용매뉴얼.md)
- DB rules: [database/DB_DEVELOPMENT_RULES.md](database/DB_DEVELOPMENT_RULES.md)
- Admin: [../frontend/README.md](../frontend/README.md)
- Changelog: [../CHANGELOG.md](../CHANGELOG.md)

## Rules

1. 현재 유효 문서는 이 목차에 올린다.
2. **새 Markdown은 프로젝트 루트에 만들지 않는다.** `docs/` 하위 도메인 폴더에만 생성한다.
3. 새 문서를 만들면 **해당 폴더 `README.md`에 링크·한 줄 설명**을 추가한다. (주요 문서는 이 목차에도 반영)
4. STEP 작업 로그는 `archive/steps/`에만 둔다.
5. 삭제는 하지 않고 obsolete/notes로 이동한다.
6. API 상세는 OpenAPI `http://127.0.0.1:8000/docs` 우선.

루트 예외(포털/에이전트만): `README.md`, `CHANGELOG.md`, `PROJECT_STATUS.md`, `AGENTS.md` 등.  
상세 규칙: `.cursor/rules/documentation-structure.mdc`
