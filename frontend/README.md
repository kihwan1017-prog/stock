# KIKI AI Trading Platform — Admin Frontend (STEP41)

FastAPI 백엔드 운영을 위한 Next.js 관리자 웹의 기초 골격입니다.

- 스펙: [../docs/roadmaps/STEP41_ADMIN_FOUNDATION.md](../docs/roadmaps/STEP41_ADMIN_FOUNDATION.md)
- 전체 문서 목차: [../docs/README.md](../docs/README.md)

STEP41 범위: 레이아웃, 테마, API Client, React Query, Zustand, 인증 골격, Dashboard 골격.

계좌/주문/AI/리스크/백테스트 실기능은 STEP42 이후에서 연결합니다.

## 요구 사항

- Node.js 20 이상 권장
- npm 10 이상
- 로컬 FastAPI (`http://127.0.0.1:8000`)

## 설치

```powershell
Set-Location D:\Projects\stock-platform\frontend
npm install
```

## 환경변수

`.env.example`을 참고해 `.env.local`을 구성합니다.

| 변수 | 설명 |
|---|---|
| `NEXT_PUBLIC_APP_NAME` | 앱 표시 이름 |
| `NEXT_PUBLIC_API_BASE_URL` | FastAPI base URL (`http://127.0.0.1:8000`) |
| `NEXT_PUBLIC_API_PREFIX` | API prefix (`/api/v1`) |
| `NEXT_PUBLIC_WS_BASE_URL` | WebSocket base URL |
| `NEXT_PUBLIC_ENABLE_REACT_QUERY_DEVTOOLS` | React Query Devtools (`true`/`false`) |
| `NEXT_PUBLIC_AUTH_MODE` | `backend` 또는 `disabled` |

비밀번호, Secret, Admin API Key는 `NEXT_PUBLIC_*`에 넣지 않습니다.

로컬 기본값:

```dotenv
NEXT_PUBLIC_AUTH_MODE=disabled
NEXT_PUBLIC_ENABLE_REACT_QUERY_DEVTOOLS=true
```

## FastAPI 실행

```powershell
Set-Location D:\Projects\stock-platform
$env:PYTHONPATH = "D:\Projects\stock-platform\src"
.\.venv\Scripts\python.exe -m uvicorn stock_platform.api.main:app `
  --reload `
  --app-dir src `
  --host 127.0.0.1 `
  --port 8000
```

- OpenAPI: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/health (API prefix 밖)

## Admin 실행

```powershell
Set-Location D:\Projects\stock-platform\frontend
npm run dev
```

접속:

- Admin: http://localhost:3000
- FastAPI docs: http://127.0.0.1:8000/docs

## 인증 모드

현재 백엔드에 JWT `/login`, `/me`가 없으므로 `NEXT_PUBLIC_AUTH_MODE=disabled`를 사용합니다.

- 로그인 화면의 **개발 모드로 입장** 버튼으로 로컬 세션 생성
- 세션 사용자: `{ id: 'dev', username: 'dev', roles: ['admin'] }`
- 토큰: `dev-disabled` (sessionStorage `kiki-admin-token`)
- Header에 `AUTH DISABLED` 표시
- 실제 인증은 `TODO(STEP50)`

`X-Admin-API-Key`는 STEP41 로그인에 사용하지 않습니다.

## 폴더 구조

```text
frontend/src
├── app/                 # App Router 페이지
├── components/          # common, layout, providers
├── config/              # env, routes, menu
├── features/            # auth, dashboard
├── hooks/
├── lib/                 # api, query, storage
├── stores/
├── styles/
├── types/
└── utils/
```

## 스크립트

```powershell
npm run dev
npm run build
npm run start
npm run lint
npm run test
npm run test:watch
npm run typecheck
npm run format
npm run format:check
```

## 테스트

```powershell
npm run test
```

포함 테스트:

- themeStore / layoutStore
- tokenStorage
- apiError mapper
- StatusBadge / LoginForm / AppSidebar

## 빌드

```powershell
npm run typecheck
npm run build
```

## 알려진 제한사항 (STEP41)

- Dashboard는 골격만 제공 (실제 자산/손익/AI 미연결)
- Health probe만 `GET /health`로 API 연결 상태 표시
- Coming Soon 페이지: market, ai, trading, orders, positions, risk, strategies, news, disclosures, backtests, operations, settings
- AG Grid / 차트 미설치
- WebSocket 본격 연동 없음

## STEP42 안내

다음 문서: `STEP42_ADMIN_DASHBOARD.md`

예정 연결:

- 총 자산, 예수금, 평가금액, 오늘 손익
- 보유 종목, 미체결 주문
- AI 추천
- PostgreSQL/Kiwoom/Upbit/Ollama/Scheduler 상태
- React Query polling
