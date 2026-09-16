# README_STEP72 — User Preferences

## 목적

사용자 전용 환경설정(Preferences)을 구현하고  
관리자 Settings(`operation.app_setting`, `settings:read/write`)와 **완전히 분리**한다.

---

## 기존 문제

- `/user/settings` 가 UnimplementedNotice
- 관리자 Settings / Ollama API 의존 위험
- Theme는 FE Zustand 로컬만 저장

---

## 관리자 Settings vs 사용자 Preferences

| 구분 | 경로 | 권한 | 저장소 |
|------|------|------|--------|
| 관리자 | `/api/v1/settings` | `settings:read/write` | `operation.app_setting` |
| 사용자 | `/api/v1/user/settings` | `trading:read` | `auth.user_preference` |

사용자 API는 `settings:read`, `settings:write`, `system:read`를 요구하지 않는다.

---

## DB

Migration: `f2a3b4c5d6e7` (revises `e1f2a3b4c5d6`)

Table: `auth.user_preference`  
PK: `user_id` (FK → `auth.user`)

주요 컬럼: theme, language, timezone, date/number format, currency,  
default_market / default_account_id / default_watchlist_id / default_dashboard,  
items_per_page, AI 토글, 알림 채널 토글.

---

## API

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/v1/user/settings` | 조회(없으면 기본값 생성) |
| PUT | `/api/v1/user/settings` | 전체 교체(미지정 필드는 기본값) |
| PATCH | `/api/v1/user/settings` | 부분 수정 |
| POST | `/api/v1/user/settings/reset` | 기본값 초기화 |

---

## Validation

- Theme: `light` \| `dark` \| `system`
- Language: `KO` \| `EN`
- Timezone: `Asia/Seoul` \| `UTC`
- Number: `1,234.56` \| `1.234,56`
- Currency: `KRW` \| `USD`
- Market: `KRX` \| `NASDAQ` \| `UPBIT`
- Dashboard: Dashboard / Portfolio / Watchlist / News / AI / Notifications
- `default_account_id` — Paper 계좌 소유권 검증 + `is_default` 동기화
- `default_watchlist_id` — 본인 watchlist 행 소유권 검증
- 관리자 키(`ollama_host` 등) 거부

---

## Notification

채널 토글(web/telegram/email)은 Preferences에 저장.  
이벤트별 구독은 STEP71 `/user/notifications` 구독 UI로 링크.

---

## Frontend

`/user/settings` — General / Appearance / Portfolio / AI / Notification 카드  
저장 시 Theme를 `themeStore`에 반영.  
React Query: `queryKeys.user.settings.get`

---

## 보안

- JWT `user_id` 본인 행만
- Admin settings 권한 불필요·미사용
- 타 사용자 계좌/관심종목 ID 거부

---

## 테스트

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_step72_user_preferences.py -q
```

---

## 남은 기능

- Language 실제 i18n 번들 적용
- Quiet hours / Email·WebPush 발송
- 로그인 시 Preferences → Theme 자동 hydrate (전역 layout)
- 관심종목 **그룹** 테이블 (현재는 watchlist item 핀)
- Preferences와 STEP71 구독 채널 양방향 sync
