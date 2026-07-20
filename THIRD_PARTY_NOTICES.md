# Third-Party Notices — stock-platform v1.0.0

이 프로젝트는 아래를 포함한 오픈소스 구성요소에 의존합니다.  
각 라이선스는 해당 패키지 배포본을 따릅니다. 전체 목록은 설치 환경의
`pip list` / `npm ls` 및 패키지 메타데이터를 확인하세요.

## Backend (대표)

| 패키지 | 용도 | 대표 라이선스 |
|--------|------|----------------|
| FastAPI / Starlette | HTTP API | MIT |
| Uvicorn | ASGI 서버 | BSD-3-Clause |
| SQLAlchemy | ORM | MIT |
| Alembic | Migration | MIT |
| Pydantic / pydantic-settings | 설정·검증 | MIT |
| Psycopg | PostgreSQL | LGPL-3.0 (바이너리 휠) |
| APScheduler | 스케줄러 | MIT |
| httpx / requests | HTTP 클라이언트 | BSD / Apache-2.0 |
| PyJWT / python-jose (해당 시) | JWT | MIT |
| pytest | 테스트 | MIT |

## Frontend (대표)

| 패키지 | 용도 | 대표 라이선스 |
|--------|------|----------------|
| Next.js | Admin UI | MIT |
| React / React DOM | UI | MIT |
| Ant Design | 컴포넌트 | MIT |
| TanStack Query | 데이터 페칭 | MIT |
| Axios | HTTP | MIT |
| Zod | 스키마 | MIT |
| Zustand | 상태 | MIT |
| Vitest / ESLint / TypeScript | 품질 | MIT / Apache-2.0 |

## 외부 서비스 (코드 비포함)

- 키움증권 Open API / REST — 증권사 이용약관
- Upbit API — 거래소 이용약관
- Telegram Bot API — Telegram Terms
- Ollama / 모델 가중치 — 각 모델 라이선스

운영자는 배포 전 의존성 라이선스 준수 여부를 자체 검토해야 합니다.
