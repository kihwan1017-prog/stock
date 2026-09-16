# UPBIT Full-Market: SINGLE vs PORTFOLIO

운영 SoT 요약. 소스·Risk DB가 문서보다 우선한다.

## Modes

| Mode | 의미 | 기본 |
|------|------|------|
| `FIXED_SYMBOL` | deployment/template 심볼 고정 | 신규 UBA 기본 |
| `FULL_MARKET_AUTO` / `FULL_MARKET_SINGLE` | Scanner Top-1 후보 → 단일 strategy-owned 포지션 | 기존 LIVE 경로 |
| `FULL_MARKET_PORTFOLIO` | Top-K → Position Slot(최대 N) | **default OFF** |

레거시 DB 값 `FULL_MARKET_AUTO`는 SINGLE과 동일하게 취급한다.

## Portfolio Policy

`operation.upbit_portfolio_policy` (UBA당 1행)

- `max_positions` (초기 3)
- `portfolio_capital_limit_krw` — 전체 잔고 100% 자동투자 금지
- `per_position_target_pct` / exposure / cash reserve
- `portfolio_max_pending_entries` (초기 1) — 동시 BUY 순차
- `portfolio_daily_entry_limit` — 계좌 `daily_order_limit`과 분리 (무시 금지)
- Averaging down / duplicate symbol: 초기 OFF

Account / Activation Risk가 더 엄격하면 **항상 더 엄격한 한도**를 적용한다.

## Position Slot

`operation.upbit_position_slot`

상태: `EMPTY → RESERVED/ENTRY_PENDING → OPEN → EXIT_PENDING → COOLDOWN → EMPTY`

- UBA + `slot_no` unique
- active symbol 중복 방지 partial unique index
- Pending reservation은 fill 전 capital에서 차감
- OPEN 강제 청산 없이 `max_positions` 축소 가능 (신규 ENTRY만 제한)

## Capital allocation

`UpbitPortfolioCapitalAllocator` (`capital_allocator.py`)

1. `base = capital_limit × per_position_target_pct`
2. quality multiplier (0.5~1.25)
3. cash reserve → total/symbol exposure → pending → account/activation max → min notional
4. 최소주문 미만이면 **SKIP** (임의 증액 금지)

## Protective exit

- strategy-owned binding(+`slot_id`)만 자동 EXIT
- manual holding 분리
- Portfolio ENTRY pause / consecutive loss → 신규 ENTRY만 중지, protective EXIT 유지
- Kill Switch / ARM / Unattended는 기존 fail-closed 유지

## Enable / Disable

- 관리자 확인 문구 필수
- Enable 후 강제 주문 없음
- 구현·배포만으로 UBA1380을 PORTFOLIO로 자동 전환하지 않음

## Fail Closed

모드/정책/슬롯/리스크/게이트 조회 실패 시 신규 ENTRY 차단.
