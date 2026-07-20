# README_STEP71 — User Notification Center

## 목적

운영용 Telegram/Slack 알림과 별도로, 사용자가 **본인 알림 Inbox**를
읽음·보관·중요·삭제·구독 관리할 수 있는 Notification Center를 제공한다.

Telegram은 Inbox Dispatcher를 거쳐 발송 대상으로 표시되며,
사용자 이벤트에 `user_id`가 없으면 기존 ops 채널만 유지한다.

---

## 기존 구조 (분석)

| 영역 | 상태 (STEP71 이전) |
|------|-------------------|
| `NotificationPublisher` → Telegram/Slack | 운영 알림 존재 |
| 사용자 Inbox 테이블 | 없음 |
| `/user/notifications` FE | UnimplementedNotice |
| Header unread badge | 없음 |

---

## DB

Schema: `notification`

### `notification`

| Column | 설명 |
|--------|------|
| notification_id | PK |
| event_type | 이벤트 타입 |
| title / message | 표시 문구 |
| payload_json | JSONB |
| severity | INFO~CRITICAL |
| dedupe_key | 중복 방지 |
| created_by / created_at / expires_at | 메타 |

### `user_notification`

| Column | 설명 |
|--------|------|
| user_id + notification_id | 소유 링크 |
| is_read / is_archived / is_deleted / is_starred | 상태 |
| *_at | 타임스탬프 |
| delivery_status | WEB_DELIVERED / TELEGRAM_QUEUED 등 |

### `notification_subscription`

| Column | 설명 |
|--------|------|
| user_id + event_type | 구독 키 |
| enabled / telegram_enabled / web_enabled / email_enabled | 채널 |
| quiet_time_start / quiet_time_end | 조용한 시간 (확장용) |

Migration: `e1f2a3b4c5d6_step71_user_notification_center.py`  
(revises `d0e1f2a3b4c5`)

---

## API

Prefix: `/api/v1/user/notifications`  
권한: `trading:read` + JWT `user_id` (본인만)

| Method | Path |
|--------|------|
| GET | `/` |
| GET | `/unread-count` |
| GET | `/subscriptions` |
| PUT | `/subscriptions` |
| POST | `/read-all` |
| GET | `/{id}` |
| POST/DELETE | `/{id}/read` |
| POST/DELETE | `/{id}/archive` |
| POST/DELETE | `/{id}/star` |
| DELETE | `/{id}` |

---

## Dispatcher

```
Event (Publisher)
  → detail.user_id / user_ids 있으면
  → NotificationDispatcher
  → notification + user_notification
  → 구독: WEB / TELEGRAM_QUEUED
```

- `dedupe_key`로 중복 생성 방지
- 구독 없으면 웹 기본 ON, 텔레그램 기본 OFF
- `user_id` 없는 ops 이벤트는 Inbox 생략 (기존 Telegram 경로 유지)

---

## Telegram 연계

- 사용자 Inbox: **직접 Telegram 호출 금지** → Dispatcher → `TELEGRAM_QUEUED`
- 운영 채널(Telegram/Slack)은 기존 `NotificationService` 유지
- Email / WebPush 컬럼은 구독 테이블에 준비됨 (발송 워커는 후속)

---

## Frontend

- `/user/notifications` — Inbox, 필터, 검색, 페이지, Drawer 상세, 구독
- `AppHeader` — 미읽음 Badge, 30초 폴링 (user 영역)
- React Query keys: `queryKeys.user.notifications.*`

---

## 보안

- 본인 `user_notification`만 조회/수정
- payload에서 secret/token/password 키 제거
- Admin settings 권한 불필요

---

## 이벤트 훅 (현재)

| 이벤트 | Inbox |
|--------|-------|
| AI 추천 완료 (`AI_ANALYSIS_COMPLETE` + user_id) | ✅ |
| 뉴스/공시/주문/Kill Switch 등 | 후속 (Publisher detail에 user_id 추가) |

---

## 테스트

```bash
pytest tests/test_step71_user_notifications.py -q
```

커버: OpenAPI, 401, 읽음/전체읽음/보관/중요/삭제, 구독, Dispatcher, 시크릿 마스킹

---

## 남은 기능

- 뉴스·공시·주문·리스크 이벤트에 `user_id` 일괄 연결
- Telegram 실제 발송 워커 (QUEUED → SENT/FAILED + retry/DLQ)
- Email / WebPush 발송
- 감사 로그 테이블 전용 기록 (현재 subscription은 애플리케이션 로그)
- WebSocket 실시간 badge (현재 30~45초 폴링)
