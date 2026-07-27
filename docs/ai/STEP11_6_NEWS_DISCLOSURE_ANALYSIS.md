# STEP 11-6 — News · Disclosure AI Analysis Pipeline

## 최종 원칙

- AI 분석 결과는 **참고 정보**이며 매매 신호·주문 지시가 아니다.
- 뉴스/공시 **수집과 AI 실행을 분리**한다. 수집만으로 외부 AI 호출 0.
- 기본 Provider는 **Mock**. EXTERNAL은 관리자 `confirm=true`만.
- Trading Signal / Candidate / Strategy / Order / Runtime / Scheduler에 **연결하지 않는다**.
- STEP 11-7은 본 STEP 완료 전 시작하지 않는다.

## Architecture

```
News/Disclosure Source
  → Eligibility → Sanitizer → Normalizer → Chunk plan
  → AnalysisRequest (create ≠ execute)
  → AIExecutionService / Runner (DRY_RUN | MOCK | EXTERNAL)
  → Schema/Policy validation
  → ai.document_analysis Safe Result
  → Admin UI / Dashboard / Telegram (read-only)
```

금지 경로: Analysis → Signal / Candidate / Strategy / Order / LIVE / ARM / Scheduler.

## Source of Truth

| 영역 | 테이블 | 문서 키 | 종목 연결 | 원문 | 중복 | 정정 |
|------|--------|---------|-----------|------|------|------|
| 뉴스 | `news.news_article` | `content_hash` | `symbol` + `news_article_symbol` M:N | title/description/`raw_data` (전문 본문 없음) | `uq_news_article_content_hash` | N/A |
| 공시 | `disclosure.dart_disclosure` | `receipt_no` | `corp_code` / `stock_code` | 메타 + `raw_data` (HTML 전문 없음) | `uq_dart_disclosure_receipt_no` | 별도 row (`is_correction`, `related_receipt_no`) |

분석 키 예:

- NEWS: `news:{content_hash}:{version}:{prompt}:{schema}:{provider}:{model}`
- DISCLOSURE: `disclosure:{receipt_no}:{revision}:{prompt}:{schema}:{provider}:{model}`

## Document Identity / Revision

- 동일 analysis_key는 중복 실행하지 않는다.
- 재분석은 `force_new_version`으로 **새 row**를 만들고 이전을 `SUPERSEDED` 한다. 덮어쓰기 금지.
- 정정 공시는 원 공시를 삭제하지 않는다.

## Normalization / Chunking

- HTML script/style/광고/면책/제어문자 제거 (`sanitizer.py`).
- 자동 웹 크롤링 금지. 본문 없으면 제목·요약 기반 + warning.
- Chunk: 최대 문서 40k chars, chunk 8k, **max 4 chunks**, overlap 200. Map-Reduce 무제한 금지.
- 이번 STEP 소스는 메타 중심이라 대부분 단일 청크. Chunk별 Provider 호출은 execution_run으로 추적(다청크 시 상한 내).

## Prompt Injection

- `<UNTRUSTED_NEWS_DOCUMENT>` / `<UNTRUSTED_DISCLOSURE_DOCUMENT>` delimiter.
- 문서 내 지시·주문·system prompt 요청·encoded instruction 탐지.
- Tool call / Secret / LIVE·ARM 요청 차단은 Core Policy + injection_guard.

## Data Classification → Provider

| 등급 | 허용 |
|------|------|
| PUBLIC | Mock, Ollama, 승인 외부 |
| INTERNAL | Mock, Ollama, 명시 허용 외부 |
| CONFIDENTIAL | Mock, Ollama |
| RESTRICTED | Mock만 |

내부 메모 결합 시 PUBLIC → INTERNAL 재평가.

## Output Schema

- `NEWS_ANALYSIS_RESULT_V1` — sentiment/importance/market_relevance/summary/… (buy/sell/target_price 금지)
- `DISCLOSURE_ANALYSIS_RESULT_V1` — event_importance/executive_summary/… (주문·전략 활성화 필드 금지)

Seed Prompt(`NEWS_ANALYSIS_BASE`, `DISCLOSURE_ANALYSIS_BASE`)는 **DRAFT**. 운영자 ACTIVE 전 실행 금지.

## Citation / Entity

- Citation은 분석 대상 문서 내부 근거만. 발췌 장기 저장 대신 hash/위치.
- AI `related_symbols`는 보조. 자동 Master 생성 없음. unmatched → `unresolved_entities`.

## API

- `POST/GET /api/v1/admin/ai/document-analyses`
- `POST .../{id}/dry-run|execute|cancel|reanalyze`
- `POST .../batches` (confirm, explicit IDs, Mock≤100 / External≤10)
- `GET .../dashboard`, `POST .../compare`

## Frontend

Admin → AI → **문서 분석** (`/admin/ai/document-analyses`).
목록/생성/Dry-run/Execute confirm/상세/비교. 매수·매도·전략·후보 버튼 없음.

## Dashboard / Telegram

- Dashboard: `ai_document_analyses` 블록 (조회 시 외부 호출 0).
- Telegram: `/ai_news`, `/ai_disclosures` 조회만.

## Retention

- 보존: Safe Result, hash, version meta, token/cost, validation, citation meta, audit.
- 미보존: Raw Prompt, Raw Response, 전체 입력 복사본.
- Source 삭제 시 `source_missing` 표시 가능 (자동 연쇄 삭제 없음 — link FK RESTRICT).

## Migration

- Revision: **`x4e5f6a7b8c9`** (revises `w3d4e5f6a7b8`)
- Tables: `ai.document_analysis` (+ topic/entity/citation/history/news_link/disclosure_link)
- Rollback: `alembic downgrade -1` 후 re-upgrade 가능.

## 운영 / 장애

1. Prompt DRAFT면 ACTIVE로 승격 후 재시도.
2. EXTERNAL 실패 시 자동 재호출 없음. 수동 재분석.
3. Budget/Policy block은 Dashboard·History로 확인.
4. 실제 외부 Provider: Credential VERIFIED + confirm + 데이터 등급 통과.

## 테스트 (외부 AI 0)

```bash
pytest tests/test_step11_6_news_disclosure_analysis.py -q
pytest -q  # 전체 회귀
```

`live_ai` Marker 테스트만 실 Provider 허용.

## STEP 11-7 연결 원칙

11-7에서 후보/차트 등으로 확장하더라도 **주문·LIVE·Scheduler 자동 연결 금지**를 유지한다. 11-6 Safe Result는 참고 계층으로만 import.
