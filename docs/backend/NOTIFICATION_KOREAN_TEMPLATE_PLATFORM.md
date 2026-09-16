# Notification Korean Template Platform

**최종 갱신:** 2026-08-21

## Overview

정형 운영/자동매매 알림은 **LLM 없이** DB Message Template + Code Dictionary + Formatter로
즉시 한글 메시지를 생성한다. 원본 JSON은 보존하며 Telegram 본문에는 기본으로 dump하지 않는다.

Toss **송신기(sender)는 현재 저장소에 없음** — 템플릿 채널 `TOSS`와 short body만 준비.

## Architecture

```text
Domain Event
  → NotificationPublisher
  → NotificationService
      → Template Pipeline (normalize → code dict → render)
      → Composite Sender (Telegram / Slack / Discord)
      → channel_delivery_log (rendered + original JSON)
```

## LLM Policy

| 대상 | LLM |
|------|-----|
| ORDER / FILL / RISK / AI code / LIVE / Kill / Runtime / Scanner candidate | **금지** |
| NEWS / DISCLOSURE / 장문 비정형 (향후) | optional + fallback |

## Tables (`notification` schema)

- `message_template`
- `code_translation`
- `channel_delivery_log`
- `notification` additive: `rendered_*`, `locale`, `template_*`, `original_payload_json`

## Admin UI

경로: **관리자 → 알림 관리** (`/admin/notifications`)

- 템플릿 목록 / 편집 / Preview / Seed
- 전송 이력 + 원본 JSON 펼치기

API:

- `GET/POST /api/v1/admin/notification-templates`
- `POST .../preview`
- `POST .../seed`
- `GET .../delivery-logs`

## Dedupe / Spam

- 기존 channel Dedup TTL 300s 유지
- AI recommendation 무변경 suppress
- Scanner HOLD 반복 15분 suppress
- TICK/HEARTBEAT 알림 금지

## Fallback

DB/template 실패 시 builtin 템플릿. UNKNOWN → generic 한글. 알림 자체는 버리지 않음.

## Migration

`n1t2f3k4m5p6_notification_korean_templates.py` (merge 3 heads + additive tables)
