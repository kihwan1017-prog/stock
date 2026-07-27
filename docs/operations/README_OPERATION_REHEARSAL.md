# Operation Rehearsal Automation (STEP 8-6-1 / 8-6-1A)

운영 환경과 동일한 시나리오를 **자동 실행**하여 준비 상태를 검증한다.  
Business Logic / DB Schema / Alembic 변경 없음.

`--full` / `--risk` 실행 시 **STEP 8-8 `live_protection` suite**가 포함된다
(ARM 만료·슬리피지·루프·Broker Down·Position Mismatch — 실주문 없음).

## 실행 방법

```powershell
python scripts/run_operation_rehearsal.py --full --telegram=dry-run
python -m stock_platform.operations.rehearsal --full --telegram=dry-run
```

## 상태 의미

| 상태 | 의미 |
|------|------|
| PASS | 검증 성공 |
| FAIL | 필수 항목 실패 (exit non-zero) |
| WARNING | 선택 항목 저하·주의 (exit 0 가능) |
| NOT_APPLICABLE | 의도적 비활성/범위 외 |
| SKIPPED | (레거시) 실행 생략 |

### 필수 vs 선택

- **필수**: PostgreSQL, Backend health routes, Scheduler(설정 ON일 때)
- **선택**: Ollama, Telegram, Live Trading(OFF가 RC 정상), Kiwoom/Upbit REST 부가 상태
- 필수 장애 → **FAIL** (WARNING으로 숨기지 않음)
- `DISABLED`(의도) ≠ `DEGRADED`(성능/부분장애)

## CLI Exit Code

| 조건 | Exit |
|------|------|
| 전체 PASS / WARNING / NOT_APPLICABLE만 | `0` |
| 필수 FAIL | `1` |
| 잘못된 CLI 옵션 | `2` (argparse) |
| 보고서 생성 실패 / 예기치 않은 예외 | `1` 또는 `2` |

## report-only

**의미 (확정 B):** 가장 최근(또는 `--from-json`) Operation Rehearsal JSON을 읽어 MD/HTML을 재생성한다.

- Broker / DB mutation / 주문 / Scheduler mutation **없음**
- 신규 검증 suite를 다시 돌리지 않음

```powershell
python scripts/run_operation_rehearsal.py --report-only
python scripts/run_operation_rehearsal.py --report-only --from-json E:\StockTrading\reports\operation_rehearsal\operation_rehearsal_YYYYMMDD_HHMMSS.json
```

## Paper mutation 정책

- 심볼: `RH` + run_id 축약 (`RH…`) — 운영 종목과 구분
- buy→value→sell 왕복 후 **포지션 0** 및 cash delta 기록
- 중간 실패 시 잔량 sell cleanup 시도
- `--no-paper-mutation`: mutation NOT_APPLICABLE
- 체결 이력(PaperTrade)은 감사 추적용으로 DB에 남을 수 있음 → 심볼/`run_id`로 구분, 필요 시 해당 심볼 거래만 정리

## run_id / correlation_id

형식: `operation-rehearsal-YYYYMMDD-HHMMSS-<uuid8>`

Audit `run_id` / `request_id` / detail.correlation_id 에 기록.

## Audit 검증

1. Audit 저장소 접근
2. 이번 실행 필수 이벤트 emit + run_id로 조회
3. Actor=`OPERATION_REHEARSAL`, timestamp, 민감정보 미포함 확인
4. 필수 이벤트 누락 → **FAIL** (최근 50건 존재만으로 PASS 금지)

## Telegram 실제 발송 점검 (STEP 8-6-1B)

### 중요

- Operation Rehearsal의 `--telegram=live` 는 **의도적으로 차단**된다 (`safety.live_order_gate`).
- 이 안전장치를 **해제하지 말 것**.
- 리허설 dry-run은 실전송을 하지 않는다.

### 전용 단독 테스트 (권장)

주문·Broker·Scheduler·DB mutation 없이 Telegram 메시지 **1건만** 보낸다.

```powershell
python scripts/test_telegram_notification.py
```

성공 예:

```text
TELEGRAM_TEST_OK
message_sent=true
test_id=tg-test-...
getMe=ok
getChat=ok
```

실패 시 (예: 403) Token/Chat ID는 출력하지 않고 description·error_code만 표시:

```text
TELEGRAM_TEST_FAIL
error_code=bot_was_blocked_by_the_user
description=Forbidden: bot was blocked by the user
reason=...
getMe=ok
getChat=fail
```

사전 점검: `getMe`(토큰) → `getChat`(Chat ID 접근) → `sendMessage`.  
구분 코드: `bot_was_blocked_by_the_user` / `chat_not_found` / `bot_is_not_a_member_of_the_group_chat` / `not_enough_rights` / `invalid_token`.

Exit: 성공 0 / 설정·API 실패 1 / 예외 2.

전제:

- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` 설정
- `APP_ENV` 가 `local`/`dev`/`development` 이거나 `TELEGRAM_STANDALONE_TEST_ALLOWED=true`

참고: 인증된 API `POST /api/v1/notification/test` 도 존재하나, 서버 기동·권한·Publisher 경로가 필요하므로 **CLI 단독 점검에는 위 스크립트를 사용**한다.

## Restore 현재 상태 (2026-07-26)

| 항목 | 상태 |
|------|------|
| Empty Upgrade | PASS |
| Alembic Single Head | PASS (`k8b9c0d1e2f3`) |
| Backup Checksum | PASS |
| Official Restore | **PASS** |
| Restore Row Count | PASS (`auth.user` 등) |
| DB Release Blocker | **0** |
| Paper | APPROVED |
| 소액 LIVE | APPROVED (로컬/VPN) |
| 공개망 | 범위 제외 |

`PGPASSWORD_ADMIN`은 검증 시에만 사용하며 상시 보관하지 않는다.

## 옵션

| 옵션 | 설명 |
|------|------|
| `--full` | 전체 suite |
| `--paper` / `--kiwoom` / `--upbit` / `--risk` / `--scheduler` / `--recovery` | 개별 suite |
| `--telegram=dry-run\|off\|live` | live는 Fail Closed |
| `--report-only` / `--from-json` | 보고서 재생성만 |
| `--no-paper-mutation` | Paper fill 생략 |
| `--report-dir` | 보고서 디렉터리 |

## 결과 파일

`E:\StockTrading\reports\operation_rehearsal\`

- `operation_rehearsal_YYYYMMDD_HHMMSS.json`
- `operation_rehearsal_YYYYMMDD_HHMMSS.md`
- `operation_rehearsal_YYYYMMDD_HHMMSS.html`
