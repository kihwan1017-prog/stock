# Product Manual Set — Verification Notes

작성일: 2026-07-19  
기준: 코드·OpenAPI·DB information_schema·Admin STEP41 소스

## 검증 결과

| 검사 | 결과 |
|------|------|
| `docs/manual/` 상대 링크 | 깨진 링크 0건 |
| OpenAPI path 수 | 201 paths → API사용매뉴얼 반영 |
| Admin UI | Dashboard만 구현, 나머지 Coming Soon으로 명시 |
| JWT 로그인 | 미구현으로 명시 |
| Docker / Redis | 미사용으로 명시 |
| 백업 전용 스크립트 | 없음 → `pg_dump` 절차로 문서화 |

## 의도적으로 문서화하지 않은 것

- Admin Coming Soon 화면의 가상 워크플로
- OpenAPI에 없는 Request 필드 예시 값 날조
- 존재하지 않는 Redis/Docker 절차
