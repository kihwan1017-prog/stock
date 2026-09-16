# STEP 03 — 환경설정과 애플리케이션 초기화

> 작성일: 2026-07-22  
> 목표: env 로딩·이름 통일·테스트 격리·import 시점 부작용 축소

---

## 1. 분석 결과

### 1.1 확인 항목

| 항목 | 이전 상태 | 조치 |
|------|-----------|------|
| `JWT_SECRET` | 공식 필드 `jwt_secret` | 유지 |
| `JWT_SECRET_KEY` | 코드에 없음 | **호환 alias + deprecation 경고** |
| DB env (`DB_HOST` 등) | 필수 필드, env/파일 로드 | 유지. 테스트는 `_env_file=None` + 명시값 |
| env 파일 경로 | import 시 `ENV_FILE` 고정 + 레거시 `E:\…` | **호출 시 `resolve_env_file()`** |
| Settings 캐시 | `@lru_cache get_settings` | `clear_settings_cache()` 추가 |
| import 시 `get_settings()` | `notification/runtime.py`, `realtime/runtime.py` | **지연 초기화 / 기본값** |
| import 시 DB 연결 | `get_engine` lazy — 즉시 연결 없음 | 유지 |
| import 시 Scheduler/Broker | lifecycle/startup 에서만 | 유지 |
| 운영 검증 | `validate_startup()` lifecycle | import 에서 호출하지 않음 |
| 테스트 오염 | secrets 파일의 Live 플래그가 단위 테스트에 유입 | **conftest 환경변수 오버라이드** |

### 1.2 이름 통일

| 공식 | 호환(임시) | 비고 |
|------|------------|------|
| `JWT_SECRET` | `JWT_SECRET_KEY` | alias + warning |
| `STOCK_PLATFORM_ENV_FILE` | 레거시 `E:\StockTrading\secrets\…` | 신규는 명시 경로 권장 |
| `STOCK_PLATFORM_DISABLE_ENV_FILE` | — | 파일 미사용(환경변수만) |
| `STOCK_PLATFORM_DISABLE_LEGACY_ENV_PATH` | — | 레거시 경로 제외 |
| `STOCK_PLATFORM_TESTING` | pytest 자동 | conftest `setdefault` |

---

## 2. 발견된 문제 (수정 전)

- **High:** `get_settings()`가 머신 secrets를 읽어 `KIWOOM_LIVE_ORDER_ENABLED=true`가 단위 테스트에 유입 (`test_security_defaults` 실패)
- **High:** `notification/runtime.py`가 import 시 Settings·알림 채널 구성
- **Medium:** `realtime/runtime.py`가 import 시 `get_settings()`로 계좌 ID 주입
- **Medium:** JWT 오류 메시지가 Windows 고정 경로를 테스트에 하드코딩
- **Medium:** `JWT_SECRET_KEY` 미지원
- **Low:** Kiwoom config 오류 문구에 머신 경로 하드코딩

---

## 3. 수정한 파일

| 파일 | 내용 |
|------|------|
| `src/stock_platform/common/settings.py` | resolve 지연, JWT alias, `__init__` env 주입, clear cache |
| `src/stock_platform/notification/runtime.py` | lazy `__getattr__` / reset |
| `src/stock_platform/realtime/runtime.py` | import 시 Settings 미호출, startup 반영 함수 |
| `src/stock_platform/api/lifecycle.py` | 기동 시 paper account 적용 |
| `src/stock_platform/broker/kiwoom/config.py` | 오류 문구 일반화 |
| `tests/conftest.py` | 테스트 안전 env + 캐시 정리 |
| `tests/test_settings_configuration.py` | **신규** 설정/import 테스트 |
| `tests/test_jwt_startup.py` | 경로 하드코딩 assertion 제거 |
| `tests/test_step40_recovery_security.py` | 격리된 security defaults |
| `tests/test_auth_deps_step52.py` | `_env_file=None` + DB 필드 |

---

## 4. 주요 수정 내용

1. **env 파일:** 클래스에 경로를 굽지 않고 `resolve_env_file()` → `Settings(_env_file=…)` / `get_settings()`.
2. **JWT:** `AliasChoices(JWT_SECRET, JWT_SECRET_KEY)` + 구명칭 사용 시 warning.
3. **테스트 격리:** conftest가 Live/알림 플래그를 `false`로 강제(환경변수 > env 파일).
4. **import 안전:** notification runtime 지연 생성; realtime runner 기본 `account_id=1`, lifecycle에서 Settings 반영.
5. **`validate_startup()`** 은 계속 lifecycle에서만 호출.

---

## 5. 실행한 테스트

```powershell
pytest tests/test_settings_configuration.py tests/test_jwt_startup.py `
  tests/test_step40_recovery_security.py tests/test_auth_deps_step52.py `
  tests/test_app_settings.py -q
# → 전부 통과

pytest -q
# → 13 failed, 500 passed, 3 skipped
```

### STEP2 대비

| | STEP2 | STEP3 후 |
|--|-------|----------|
| passed | 484 | **500** |
| failed | 14 | **13** |
| skipped | 3 | 3 |

해결: `test_security_defaults` (환경 오염).  
잔여 13: Auth Fake(STEP4), 예외코드(STEP5), Scheduler(STEP9), KillSwitch Fake(STEP8).

---

## 6. 남아 있는 문제

- Auth `_repository._session` / Fake 계약 (STEP4)
- 예외 코드 세분화 (STEP5)
- `api/main.py`의 `app = create_app()` 은 import 시 Settings 로드(DB 연결은 아님) — ASGI 관행상 유지
- 레거시 `E:\…` 경로는 호환용으로 잔존(`DISABLE_LEGACY`로 차단 가능)
- 이전 pytest 로그에 Telegram Bot 토큰이 URL로 노출된 적 있음 → **BotFather에서 토큰 재발급 권장**. conftest에서 `TELEGRAM_ENABLED=false` 강제 추가함.

---

## 7. 다음 단계

**STEP4** — Auth Repository 계약 정렬, `_repository._session` 제거.

---

## 8. 권장 커밋 메시지

```text
fix(step03): isolate settings loading and defer import-time side effects
```
