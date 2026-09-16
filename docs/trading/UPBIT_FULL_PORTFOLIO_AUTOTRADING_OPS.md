# UPBIT Full Portfolio Autotrading — Operations Guide

운영 SoT 요약. 소스·DB Risk가 문서보다 우선한다.

## End-to-end flow

```text
UPBIT KRW universe
→ Opportunity Scanner (SHADOW scan)
→ Top-N ranking
→ AI Gate (ALLOW/HOLD/BLOCK)
→ Candidate Selector (SINGLE Top-1 / PORTFOLIO Top-K)
→ Capital Allocator (recommended → approved + clamp reasons)
→ Account/Activation Risk clamp
→ Position Slot ENTRY (pending BUY = 1)
→ Fill → strategy_position_binding (+ slot_id)
→ Exit Monitor (SL/TP/Trailing) per slot
→ SELL → reconcile → COOLDOWN → EMPTY → refill
→ 24H unattended loop
```

## Modes (3)

| Mode | 의미 | Default |
|------|------|---------|
| `FIXED_SYMBOL` | template/deployment 심볼 고정 | 신규 기본 |
| `FULL_MARKET_AUTO` / `FULL_MARKET_SINGLE` | Scanner Top-1 → 단일 strategy-owned | 현재 UBA1380 |
| `FULL_MARKET_PORTFOLIO` | Top-K → max N slots | **OFF until admin Enable** |

레거시 `FULL_MARKET_AUTO` ≡ SINGLE. PORTFOLIO 자동 migration 금지.

## Portfolio Risk vs Account Risk

- **Account / Activation Risk**: 절대 상한 (max_order, daily loss, kill, ARM…)
- **Portfolio Policy**: 운용 allocation (capital limit, exposure %, cash reserve, pending entries)

`effective = min(portfolio_approved, account, activation)`. Portfolio가 Account보다 크면 clamp.

## Recommended conservative defaults

- max_positions = 3
- portfolio_max_pending_entries = 1
- per_position_target_pct = 8%
- max_symbol_exposure_pct = 12%
- max_total_exposure_pct = 30%
- min_cash_reserve_pct = 60%
- daily_loss_limit_pct = 2%
- consecutive_loss_limit = 3 → ENTRY_PAUSED
- averaging / duplicate = OFF

## Position slots

`EMPTY → RESERVED/ENTRY_PENDING → OPEN → EXIT_PENDING → COOLDOWN → EMPTY`

Protective EXIT는 slot full / entry pause / cash reserve에 막히지 않음.

## Admin UI

1. **설정 워크스페이스:** 관리자 → 자동매매 운영 → 업비트 자동매매 설정  
   `/admin/upbit/autotrading?ubaId=1380`  
   Tabs: 전체시장 자동선정 · 자금·포지션 · 진입 · 청산 · AI · 안전·손실 제한
2. **운영 Drawer:** 요약 + Start/Stop + [포트폴리오 설정] 링크 (설정 전체 중복 배치 금지)
3. **리스크 메뉴:** Account/System Safety SoT 유지

## Enable / Fail-closed

- Enable은 확인 문구 필수. Enable ≠ 강제 주문.
- Restart 후 PORTFOLIO 자동 ON이면 실패.
- Orphan (slot/binding/order 불일치) 시 신규 ENTRY fail-closed, 자동 삭제 금지.
- Correlation은 future-ready (`risk_group_policy_json`) — 이번 완료 blocker 아님.

## Related

- [UPBIT_FULL_MARKET_DYNAMIC_AUTOTRADING.md](./UPBIT_FULL_MARKET_DYNAMIC_AUTOTRADING.md)
- [UPBIT_FULL_MARKET_PORTFOLIO.md](./UPBIT_FULL_MARKET_PORTFOLIO.md)
