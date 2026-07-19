# STEP41_ADMIN_FOUNDATION.md

## 1. 목표

`D:\Projects\stock-platform` FastAPI 백엔드를 운영하기 위한 관리자 웹 프로젝트의 기본 골격을 구축한다.

STEP41 완료 범위:

- Next.js 관리자 프로젝트 생성
- TypeScript Strict Mode
- Ant Design 공통 테마
- 공통 레이아웃
- Sidebar/Header
- 다크·라이트·시스템 테마
- Axios 공통 API Client
- TanStack Query
- Zustand
- 인증 기본 구조
- FastAPI 연결 확인
- 공통 오류 처리
- Dashboard 기본 화면
- 테스트 및 README

STEP41에서는 실제 계좌, 주문, AI 추천, 리스크, 백테스트 기능을 구현하지 않는다.

---

## 2. 프로젝트 경로

```text
D:\Projects
└── stock-platform
    ├── src
    ├── frontend
    ├── tests
    ├── database
    ├── alembic
    └── docs
```

관리자 웹 경로:

```text
D:\Projects\stock-platform\frontend
```

백엔드 소스나 가상환경을 관리자 프로젝트에 복사하지 않는다.

---

## 3. 작업 전 백엔드 조사

Cursor는 구현 전에 반드시 기존 프로젝트를 조사한다.

```text
D:\Projects\stock-platform\src
D:\Projects\stock-platform\tests
D:\Projects\stock-platform\docs
D:\Projects\stock-platform\alembic
D:\Projects\stock-platform\database
```

확인 항목:

1. FastAPI 앱 import 경로
2. 실행 포트
3. API prefix
4. 등록된 Router
5. OpenAPI 주소
6. 인증/JWT API 존재 여부
7. 현재 사용자 조회 API
8. Health/System Status API
9. CORS 설정
10. WebSocket 엔드포인트
11. 공통 응답 및 오류 DTO

API 경로를 추측하지 말고 실제 소스와 OpenAPI를 기준으로 한다.

---

## 4. 개발 원칙

- Windows PowerShell 기준
- Docker 사용 금지
- 기존 FastAPI API 우선 사용
- Entity, Repository, Service, DTO, Router 중복 생성 금지
- STEP41에서는 DB 테이블과 Alembic Migration 추가 금지
- Mock은 백엔드 API가 없을 때만 사용
- Mock 사용 시 `TODO(STEP42)` 주석 필수
- TypeScript `any` 사용 금지
- Server State는 React Query
- UI State는 Zustand
- 환경변수는 Zod 검증
- 비밀번호, Secret, API Key를 `NEXT_PUBLIC_*`에 저장 금지

---

## 5. 기술 스택

| 영역 | 기술 |
|---|---|
| Framework | Next.js 15 이상 |
| UI | React 19 |
| Language | TypeScript |
| UI Library | Ant Design 5 |
| Icons | @ant-design/icons |
| Server State | @tanstack/react-query |
| Client State | Zustand |
| HTTP | Axios |
| Validation | Zod |
| Date | dayjs |
| Test | Vitest + Testing Library |
| Lint | ESLint |
| Format | Prettier |

AG Grid와 차트 라이브러리는 STEP42 이후 실제 사용 시 설치한다.

---

## 6. 프로젝트 생성

PowerShell:

```powershell
Set-Location D:\Projects\stock-platform

npx create-next-app@latest frontend `
  --typescript `
  --eslint `
  --app `
  --src-dir `
  --import-alias "@/*" `
  --use-npm

Set-Location D:\Projects\stock-platform\frontend
```

선택 기준:

```text
TypeScript       Yes
ESLint           Yes
Tailwind CSS     No
src directory    Yes
App Router       Yes
Turbopack        Yes
Import alias     @/*
```

패키지 설치:

```powershell
npm install antd @ant-design/icons
npm install axios
npm install @tanstack/react-query @tanstack/react-query-devtools
npm install zustand zod dayjs clsx
npm install -D prettier vitest jsdom
npm install -D @testing-library/react @testing-library/jest-dom @testing-library/user-event
```

---

## 7. 환경변수

`.env.local`:

```dotenv
NEXT_PUBLIC_APP_NAME=KIKI AI Trading Platform
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_API_PREFIX=/api/v1
NEXT_PUBLIC_WS_BASE_URL=ws://127.0.0.1:8000
NEXT_PUBLIC_ENABLE_REACT_QUERY_DEVTOOLS=true
NEXT_PUBLIC_AUTH_MODE=backend
```

`.env.example`:

```dotenv
NEXT_PUBLIC_APP_NAME=KIKI AI Trading Platform
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_API_PREFIX=/api/v1
NEXT_PUBLIC_WS_BASE_URL=ws://127.0.0.1:8000
NEXT_PUBLIC_ENABLE_REACT_QUERY_DEVTOOLS=false
NEXT_PUBLIC_AUTH_MODE=disabled
```

주의:

- 실제 포트와 prefix는 기존 FastAPI 코드를 확인한 뒤 수정한다.
- 인증 API가 없으면 `NEXT_PUBLIC_AUTH_MODE=disabled`를 사용한다.
- `.env.local`은 Git에 커밋하지 않는다.

---

## 8. 목표 폴더 구조

```text
stock-platform/frontend
├── public
├── src
│   ├── app
│   │   ├── (auth)
│   │   │   └── login
│   │   │       └── page.tsx
│   │   ├── (main)
│   │   │   ├── dashboard
│   │   │   │   └── page.tsx
│   │   │   └── layout.tsx
│   │   ├── error.tsx
│   │   ├── global-error.tsx
│   │   ├── layout.tsx
│   │   ├── loading.tsx
│   │   ├── not-found.tsx
│   │   └── page.tsx
│   ├── components
│   │   ├── common
│   │   │   ├── AppLoading.tsx
│   │   │   ├── EmptyState.tsx
│   │   │   ├── PageContainer.tsx
│   │   │   ├── StatusBadge.tsx
│   │   │   └── index.ts
│   │   ├── layout
│   │   │   ├── AppHeader.tsx
│   │   │   ├── AppSidebar.tsx
│   │   │   ├── MainLayout.tsx
│   │   │   ├── SidebarMenu.tsx
│   │   │   └── index.ts
│   │   └── providers
│   │       ├── AntdProvider.tsx
│   │       ├── AppProviders.tsx
│   │       └── QueryProvider.tsx
│   ├── config
│   │   ├── env.ts
│   │   ├── menu.tsx
│   │   └── routes.ts
│   ├── features
│   │   ├── auth
│   │   │   ├── api/authApi.ts
│   │   │   ├── components/LoginForm.tsx
│   │   │   ├── hooks/useAuth.ts
│   │   │   ├── store/authStore.ts
│   │   │   └── types/auth.ts
│   │   └── dashboard
│   │       ├── components/DashboardWelcome.tsx
│   │       ├── components/FoundationChecklist.tsx
│   │       └── components/SystemStatusPlaceholder.tsx
│   ├── hooks
│   │   ├── useHydrated.ts
│   │   └── useThemeMode.ts
│   ├── lib
│   │   ├── api
│   │   │   ├── apiClient.ts
│   │   │   ├── apiError.ts
│   │   │   ├── apiTypes.ts
│   │   │   └── interceptors.ts
│   │   ├── query
│   │   │   ├── queryClient.ts
│   │   │   └── queryKeys.ts
│   │   └── storage/tokenStorage.ts
│   ├── stores
│   │   ├── layoutStore.ts
│   │   └── themeStore.ts
│   ├── styles
│   │   ├── globals.css
│   │   └── theme.ts
│   ├── types/common.ts
│   └── utils
│       ├── format.ts
│       └── logger.ts
├── .env.example
├── .env.local
├── package.json
├── tsconfig.json
├── vitest.config.ts
└── README.md
```

---

## 9. 라우팅

| URL | 설명 | STEP41 |
|---|---|---|
| `/` | `/dashboard`로 이동 | 구현 |
| `/login` | 로그인 | 구현 |
| `/dashboard` | 기본 Dashboard | 구현 |
| `/market` | 시장 | Coming Soon |
| `/ai` | AI Center | Coming Soon |
| `/trading` | 자동매매 | Coming Soon |
| `/orders` | 주문 | Coming Soon |
| `/positions` | 포지션 | Coming Soon |
| `/risk` | 리스크 | Coming Soon |
| `/strategies` | 전략 | Coming Soon |
| `/news` | 뉴스 | Coming Soon |
| `/disclosures` | 공시 | Coming Soon |
| `/backtests` | 백테스트 | Coming Soon |
| `/operations` | 운영 | Coming Soon |
| `/settings` | 설정 | Coming Soon |

미구현 메뉴는 404가 아니라 공통 `ComingSoon` 화면을 표시한다.

---

## 10. 레이아웃 요구사항

```text
┌──────────────────────────────────────────────────────────────┐
│ Header                                                       │
├───────────────┬──────────────────────────────────────────────┤
│ Sidebar       │ Page Content                                 │
│               │                                              │
└───────────────┴──────────────────────────────────────────────┘
```

### Sidebar

- 펼침 240px
- 접힘 72px
- Ant Design `Layout.Sider`
- 접힘 상태 Zustand 저장
- 새로고침 후 상태 유지
- 현재 URL 메뉴 선택
- 아이콘 표시
- 하단 버전 표시
- 모바일에서는 Drawer

메뉴:

```text
Dashboard
Market
AI Center
Trading
Orders
Positions
Risk
Strategy
News
Disclosure
Backtest
Operations
Settings
```

### Header

왼쪽:

- 페이지 제목
- Sidebar 토글

오른쪽:

- API 연결 상태
- 자동매매 상태 Placeholder
- 테마 전환
- 사용자 메뉴
- 로그아웃

---

## 11. 테마

지원 모드:

```ts
type ThemeMode = "light" | "dark" | "system";
```

기본값:

```text
system
```

저장 키:

```text
kiki-admin-theme
```

Ant Design의 다음 algorithm을 사용한다.

```ts
theme.defaultAlgorithm
theme.darkAlgorithm
```

화면별 색상 하드코딩을 금지하고 공통 token은 `src/styles/theme.ts`에서 관리한다.

---

## 12. 환경변수 검증

`src/config/env.ts`에서 Zod로 검증한다.

```ts
import { z } from "zod";

const envSchema = z.object({
  NEXT_PUBLIC_APP_NAME: z.string().min(1),
  NEXT_PUBLIC_API_BASE_URL: z.string().url(),
  NEXT_PUBLIC_API_PREFIX: z.string().startsWith("/"),
  NEXT_PUBLIC_WS_BASE_URL: z.string().min(1),
  NEXT_PUBLIC_ENABLE_REACT_QUERY_DEVTOOLS: z
    .enum(["true", "false"])
    .transform((value) => value === "true"),
  NEXT_PUBLIC_AUTH_MODE: z.enum(["backend", "disabled"]),
});
```

환경변수 오류를 숨기지 말고 시작 단계에서 명확히 실패시킨다.

---

## 13. Axios API Client

`src/lib/api/apiClient.ts`

요구사항:

- `baseURL = API_BASE_URL + API_PREFIX`
- timeout 15초
- JSON 요청
- Access Token 자동 첨부
- 오류를 공통 `ApiError`로 변환
- 화면마다 Axios 인스턴스 중복 생성 금지

토큰 헤더:

```http
Authorization: Bearer {accessToken}
```

401 처리:

- 토큰 제거
- Auth Store 초기화
- `/login` 이동
- 무한 redirect 방지

공통 오류 타입:

```ts
export interface ApiErrorPayload {
  status: number;
  code?: string;
  message: string;
  details?: unknown;
  requestId?: string;
}
```

백엔드의 `detail`, `message`, 문자열 오류 등 실제 응답 형태를 확인하여 안전하게 변환한다.

---

## 14. React Query

기본값:

```ts
{
  queries: {
    staleTime: 30_000,
    gcTime: 5 * 60_000,
    retry: 1,
    refetchOnWindowFocus: false,
  },
  mutations: {
    retry: 0,
  },
}
```

Query Key Factory:

```ts
export const queryKeys = {
  auth: {
    all: ["auth"] as const,
    me: () => ["auth", "me"] as const,
  },
  system: {
    all: ["system"] as const,
    status: () => ["system", "status"] as const,
  },
  dashboard: {
    all: ["dashboard"] as const,
    summary: () => ["dashboard", "summary"] as const,
  },
};
```

화면마다 문자열 Query Key를 직접 작성하지 않는다.

---

## 15. Zustand Store

### themeStore

```ts
interface ThemeState {
  mode: "light" | "dark" | "system";
  setMode: (mode: ThemeState["mode"]) => void;
}
```

### layoutStore

```ts
interface LayoutState {
  sidebarCollapsed: boolean;
  mobileMenuOpen: boolean;
  setSidebarCollapsed: (collapsed: boolean) => void;
  setMobileMenuOpen: (open: boolean) => void;
  toggleSidebar: () => void;
}
```

### authStore

```ts
interface AuthUser {
  id: string;
  username: string;
  displayName?: string;
  roles: string[];
}

interface AuthState {
  accessToken: string | null;
  user: AuthUser | null;
  authenticated: boolean;
  setSession: (token: string, user: AuthUser) => void;
  clearSession: () => void;
}
```

토큰 정책:

- 백엔드가 HttpOnly Cookie를 지원하면 Cookie 우선
- 아니면 sessionStorage 또는 memory 사용
- JWT를 localStorage에 영구 저장하지 않는다

---

## 16. 인증 처리

기존 FastAPI에서 다음 키워드를 검색한다.

```text
/login
/token
/auth
/jwt
/oauth2
/current_user
/me
refresh_token
Authorization
Bearer
```

### 인증 API가 존재할 때

- 기존 Request/Response DTO 사용
- 로그인 성공 후 Token/User 저장
- `/dashboard` 이동

### 인증 API가 없을 때

백엔드 인증을 STEP41에서 새로 만들지 않는다.

```dotenv
NEXT_PUBLIC_AUTH_MODE=disabled
```

동작:

- 로그인 화면에 `개발 모드로 입장` 버튼
- Dashboard 접근 허용
- Header에 `AUTH DISABLED` 경고 표시
- STEP50 보안 작업 TODO 기록

---

## 17. Dashboard 기본 화면

STEP41에서는 골격만 구현한다.

```text
┌──────────────────────────────────────────────────────────────┐
│ KIKI AI Trading Platform                                    │
│ FastAPI 운영 관리자                                          │
├──────────────────┬──────────────────┬────────────────────────┤
│ API 연결 상태     │ 인증 상태         │ 현재 모드              │
├──────────────────┴──────────────────┴────────────────────────┤
│ STEP42에서 계좌, 손익, AI 추천, 주문, 시스템 상태를 연결합니다. │
└──────────────────────────────────────────────────────────────┘
```

컴포넌트:

- `DashboardWelcome`
- `SystemStatusPlaceholder`
- `FoundationChecklist`

FoundationChecklist:

- Next.js 실행
- Ant Design 적용
- Theme 전환
- Sidebar 동작
- FastAPI 연결
- React Query 동작
- 인증 모드 확인

---

## 18. FastAPI 연결 확인

기존 FastAPI에서 다음을 확인한다.

- `FastAPI(...)`
- `include_router`
- `/docs`
- `/openapi.json`
- health/status API
- CORS middleware
- uvicorn 실행 명령

Health API가 있으면 반드시 기존 API를 사용한다.

가능한 예시 경로:

```text
/health
/healthz
/api/v1/health
/api/v1/system/health
```

정확한 경로는 소스에서 확인한다.

Health API가 정말 없을 때만 최소 Endpoint 추가를 검토한다.

```json
{
  "status": "ok",
  "service": "stock-platform",
  "timestamp": "2026-07-18T10:00:00+09:00"
}
```

조건:

- 기존 대체 API 없음
- DB 테이블 추가 없음
- 기존 Router 구조 준수
- 테스트 추가

---

## 19. CORS

개발 허용 Origin:

```text
http://localhost:3000
http://127.0.0.1:3000
```

기존 CORS 설정을 먼저 확인한다.

없을 때만 추가한다.

```py
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

운영 환경에서 `allow_origins=["*"]`와 `allow_credentials=True`를 함께 사용하지 않는다.

---

## 20. 공통 컴포넌트

### PageContainer

```ts
interface PageContainerProps {
  title: string;
  description?: string;
  extra?: React.ReactNode;
  children: React.ReactNode;
}
```

### StatusBadge

```ts
type StatusType =
  | "healthy"
  | "warning"
  | "error"
  | "disabled"
  | "unknown";
```

### AppLoading

- Ant Design Spin
- 전체 화면/영역 로딩 구분

### EmptyState

- 데이터 없음
- 미구현
- 검색 결과 없음

상태를 구분한다.

---

## 21. 메뉴 설정

메뉴를 Sidebar 컴포넌트에 직접 하드코딩하지 않는다.

`src/config/menu.tsx`:

```ts
export interface AppMenuItem {
  key: string;
  label: string;
  path: string;
  icon: React.ReactNode;
  enabled: boolean;
}
```

후속 권한 제어를 추가할 수 있는 구조로 만든다.

---

## 22. 공통 페이지

- `/` → `/dashboard` redirect
- `not-found.tsx` → 안내 + Dashboard 이동
- `error.tsx` → 재시도 버튼
- `global-error.tsx` → Root 오류 처리
- `loading.tsx` → 공통 로딩

운영 환경에서는 Stack Trace를 사용자에게 노출하지 않는다.

---

## 23. 테스트

최소 단위 테스트:

```text
themeStore
layoutStore
tokenStorage
apiError mapper
StatusBadge
LoginForm
AppSidebar
```

검증 항목:

- Sidebar 접기/펼치기
- 테마 전환
- 메뉴 이동
- Login validation
- API 오류 표시
- 모바일 메뉴 열기/닫기

최종 명령:

```powershell
npm run typecheck
npm run lint
npm run test
npm run build
```

모두 성공해야 한다.

---

## 24. package.json Script

```json
{
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "eslint .",
    "test": "vitest run",
    "test:watch": "vitest",
    "typecheck": "tsc --noEmit",
    "format": "prettier --write .",
    "format:check": "prettier --check ."
  }
}
```

Next.js 설치 버전에 맞춰 lint 명령을 조정한다.

---

## 25. README 필수 내용

- 프로젝트 설명
- Node.js 요구 버전
- 설치 방법
- 환경변수
- FastAPI 실행 방법
- Admin 실행 방법
- 인증 모드
- 폴더 구조
- 테스트
- 빌드
- 알려진 제한사항
- STEP42 안내

실행 예:

```powershell
# Terminal 1 - Backend
Set-Location D:\Projects\stock-platform
$env:PYTHONPATH = "D:\Projects\stock-platform\src"
.\.venv\Scripts\python.exe -m uvicorn stock_platform.api.main:app `
  --reload `
  --app-dir src `
  --host 127.0.0.1 `
  --port 8000

# Terminal 2 - Admin
Set-Location D:\Projects\stock-platform\frontend
npm run dev
```

접속:

```text
Admin   http://localhost:3000
FastAPI http://127.0.0.1:8000/docs
```

실제 import path와 포트는 프로젝트 조사 후 수정한다.

---

## 26. 완료 기준

### 프로젝트

- [ ] `D:\Projects\stock-platform\frontend` 생성
- [ ] Next.js App Router
- [ ] TypeScript Strict
- [ ] ESLint 성공
- [ ] Typecheck 성공
- [ ] Production Build 성공

### UI

- [ ] 로그인 화면
- [ ] Dashboard
- [ ] Sidebar
- [ ] Header
- [ ] Sidebar 접기/펼치기
- [ ] 모바일 Drawer
- [ ] 라이트/다크/시스템 테마
- [ ] 404
- [ ] Error
- [ ] Loading

### 상태/API

- [ ] Theme Store
- [ ] Layout Store
- [ ] Auth Store
- [ ] React Query Provider
- [ ] Axios Client
- [ ] 공통 오류 변환
- [ ] FastAPI 연결 확인
- [ ] 인증 모드 표시
- [ ] 401 처리

### 문서/테스트

- [ ] `.env.example`
- [ ] README
- [ ] 핵심 테스트
- [ ] `npm run test` 성공
- [ ] `npm run build` 성공

---

## Monorepo 개발 규칙

- Backend와 Frontend는 하나의 Git 저장소에서 관리한다.
- Frontend는 `stock-platform/frontend`에 생성한다.
- Cursor는 항상 `D:\Projects\stock-platform` 루트를 연다.

---

## 27. STEP41 제외 범위

다음은 STEP42 이후 구현한다.

- 계좌 자산
- 예수금
- 오늘 손익
- 보유 종목
- 실시간 주문
- 미체결 주문
- AI 후보 10개
- AI 최종 추천 5개
- 뉴스/공시 요약
- 전략 배포
- Kill Switch 제어
- 백테스트 차트
- Scheduler 제어
- 운영 로그 Grid
- Telegram/Discord 설정
- 사용자/권한 관리
- AG Grid
- ECharts
- 실시간 WebSocket 본격 연동

---

## 28. Cursor 실행 지시문

아래 내용을 Cursor Agent에 그대로 전달한다.

```text
D:\Projects\stock-platform과
D:\Projects\stock-platform\frontend을 함께 확인하세요.

STEP41_ADMIN_FOUNDATION.md 요구사항을 구현하세요.

작업 전 필수 조사:
1. 기존 FastAPI 앱 실행 경로와 포트를 확인합니다.
2. API prefix와 등록 Router를 확인합니다.
3. 인증/JWT API 존재 여부를 확인합니다.
4. Health/System Status API를 확인합니다.
5. CORS 설정을 확인합니다.
6. 기존 오류 응답 DTO를 확인합니다.
7. 기존 API를 우선 사용합니다.

개발 규칙:
- Windows PowerShell 기준입니다.
- Docker를 사용하지 마세요.
- Entity, Repository, Service, Router, DTO, DB Table을 중복 생성하지 마세요.
- STEP41에서는 DB Migration을 만들지 마세요.
- API 경로를 추측하지 말고 소스에서 확인하세요.
- 인증 API가 없으면 NEXT_PUBLIC_AUTH_MODE=disabled로 구현하세요.
- 백엔드 변경은 CORS 또는 최소 Health Endpoint가 꼭 필요한 경우만 허용합니다.
- TypeScript strict 오류를 남기지 마세요.
- any 타입을 사용하지 마세요.
- Ant Design을 사용하세요.
- Server State는 React Query, UI State는 Zustand로 관리하세요.
- 환경변수는 Zod로 검증하세요.
- 공통 API Client를 재사용하세요.
- 실행 가능한 README를 작성하세요.

완료 후 반드시 실행:
npm run typecheck
npm run lint
npm run test
npm run build

최종 보고서에 포함:
1. 생성/수정 파일 목록
2. 확인한 FastAPI API 목록
3. 인증 적용 방식
4. CORS 변경 여부
5. Mock 데이터 사용 여부
6. 테스트 결과
7. 빌드 결과
8. 남은 TODO
9. STEP42에서 연결할 실제 Dashboard API 목록
```

---

## 29. Cursor 완료 보고서 형식

```markdown
# STEP41 완료 보고서

## 1. 구현 요약

## 2. 생성 파일

## 3. 수정 파일

## 4. 기존 FastAPI 조사 결과
- API prefix:
- OpenAPI:
- 인증:
- Health:
- CORS:
- WebSocket:

## 5. Admin 실행 방법

## 6. 인증 방식

## 7. 테스트 결과
- typecheck:
- lint:
- test:
- build:

## 8. Mock/TODO

## 9. 발견한 백엔드 문제

## 10. STEP42 권장 작업
```

---

## 30. 다음 단계

STEP41 완료 후:

```text
STEP42_ADMIN_DASHBOARD.md
```

STEP42 범위:

- 총 자산
- 예수금
- 평가금액
- 오늘 손익
- 실현/평가 손익
- 보유 종목
- 미체결 주문
- AI 추천
- PostgreSQL/Kiwoom/Upbit/Ollama/Scheduler 상태
- 최근 Job과 오류
- React Query Polling
- 실제 FastAPI API 연결
