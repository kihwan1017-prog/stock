# PERFORMANCE_REPORT_STEP74

## 측정 범위

이번 STEP에서는 부하 생성기(k6/locust) **미실행**.  
다음은 스모크·코드 리뷰 결과이다.

## 스모크

| 항목 | 결과 |
|------|------|
| STEP65–74 pytest 89건 | ~10–12s (로컬) |
| Vitest 55건 | ~16s |
| `next build` | ~40s, exit 0 |
| OpenAPI 생성 | 성공 (297 paths) |

## API별 P95

**미측정.** 운영 전 권장:

| API | 권장 P95 |
|-----|----------|
| unread-count | ≤200ms |
| 단순 목록 | ≤500ms |
| 복합 목록 | ≤1s |
| AI 생성 등록 | ≤1s (실제 Ollama는 별도) |

## 병목·관찰

- 알림/뉴스/공시: join + pagination 패턴 (STEP68–71)
- Portfolio 이력: 기간 필터 — 대량 시 total_count 비용 주의
- N+1: 핵심 목록은 batch/join 위주이나 부하 재검증 필요

## 수정

성능 Critical 결함으로 확인된 코드 변경 없음.
