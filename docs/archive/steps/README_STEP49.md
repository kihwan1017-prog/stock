# README_STEP49 — Authentication

## 1. 목표

User/Admin Web **인증·인가**를 정리하고 기존 Backend Auth/RBAC API에 연결한다.

- 회원가입 · 로그인 · JWT · Refresh Token · 로그아웃  
- My Page · 비밀번호 변경  
- RBAC: **viewer / trader / admin** 권한 적용  

STEP49는 **신규 Backend Auth 엔드포인트를 만들지 않는다.**

---

## 2. Backend 역할 매핑

시드·검증 역할은 **`admin` / `operator` / `viewer`** 이다.  
요청 스펙의 **`trader`는 Backend `operator`에 매핑**한다 (FE 표시명·가드에서 trader로 취급).

| 제품 역할 | Backend role code | 포털 | 요약 |
|-----------|-------------------|------|------|
| viewer | `viewer` | User | 조회 중심 (매매·자동매매·전략·백테스트 메뉴 제한) |
| trader | `operator` (+ 향후 `trader`) | User + Admin(권한 범위 내) | 매매·전략 등 실행 가능 |
| admin | `admin` | Admin + User | 전체 권한 |

---

## 3. 구현 범위

| 기능 | 상태 | 데이터 소스 |
|------|------|-------------|
| 회원가입 | 연결 | `POST /auth/signup` |
| 로그인 | 연결 | `POST /auth/login` |
| JWT access | 연결 | Bearer + `tokenStorage` |
| Refresh Token | 연결 | `POST /auth/refresh` + axios 인터셉터 |
| 로그아웃 | 연결 | `POST /auth/logout` + 세션 클리어 |
| My Page | 연결 | `GET /auth/me` · 역할/권한 표시 |
| 비밀번호 변경 | 연결 | `POST /auth/change-password` |
| Admin RBAC | 강화 | Admin 진입: `admin`·`operator`만 · 메뉴 permission |
| User RBAC | 신규 | 메뉴·경로 가드 (trader=`operator`) |

---

## 4. 규칙

1. 기존 Backend API만 사용한다.
2. `trader` 역할 시드/마이그레이션을 임의 추가하지 않는다 → `operator` 매핑.
3. 없는 self-service(프로필 수정·preferences)는 TODO.
4. UI는 기존 Auth 페이지 + `UserPageShell` (My Page) 패턴.

---

## 5. 주요 파일

```text
README_STEP49.md
frontend/src/features/auth/utils/roles.ts
frontend/src/features/auth/utils/roles.test.ts
frontend/src/features/auth/hooks/useAuth.ts
frontend/src/components/layout/AuthGuard.tsx
frontend/src/components/layout/AppHeader.tsx
frontend/src/app/(user)/layout.tsx
frontend/src/app/(admin)/layout.tsx
frontend/src/app/(user)/user/profile/page.tsx
frontend/src/config/menu.tsx
```

---

## 6. TODO (후속)

- [ ] Backend `trader` 역할 시드 (`ALLOWED_ROLES` + migration)
- [ ] `GET/PUT /api/v1/user/preferences`
- [ ] 프로필 self-update (display_name 등)
- [ ] 회원↔계좌 소유권
- [ ] Next.js middleware 서버 사이드 가드

---

## 7. 완료 체크리스트

- [x] README 초안
- [x] 회원가입·로그인·JWT·Refresh·로그아웃 확인/정리
- [x] My Page · 비밀번호 변경
- [x] viewer / trader(operator) / admin 가드
- [x] lint / test / build
- [x] README 최종 업데이트

---

## 8. 구현 결과

| 항목 | 내용 |
|------|------|
| 역할 헬퍼 | `roles.ts` — trader↔operator 매핑 · 포털/경로 가드 |
| Admin | `requiredRoles=["admin","operator"]` — viewer는 User로 |
| User 메뉴 | 매매·자동매매·전략·백테스트 = `minAccess: trader` |
| 헤더 | My Page · 설정 · Admin 링크 · 로그아웃 · 역할 Tag |
| My Page | `/user/profile` — me · JWT 일부 · 비밀번호 변경 |
| 검증 | lint · test · build |

다음: STEP50+
