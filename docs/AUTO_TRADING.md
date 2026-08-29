# Auto Trading — Current Policy (SoT summary)

문서화만. **정책을 이 파일로 변경하지 않는다.** 구현 SoT는 소스 + UBA risk/portfolio 설정이다.

## UPBIT (UBA 1380 — Short-Term Operation V1)

| 항목 | 현재 |
|------|------|
| Daily AUTO Entry Limit | **6** / KST day (`portfolio_daily_entry_limit`) |
| EXIT vs ENTRY quota | **분리** — SELL은 ENTRY quota 미소비 |
| AUTO Slot max | **6** (`max_position_count`, 숫자 증가 없음) |
| AUTO slot count | **AUTO-owned** open + ENTRY_PENDING reservation |
| MANUAL / UNKNOWN | AUTO slot **미소비**, account exposure/risk에는 **포함** |
| Entry strategy | 기존 MA/AI/candidate (이 문서에서 변경하지 않음) |
| Exit REAL | **MA_DEAD_CROSS** |
| SL / TP | **NOT_CONFIGURED** (REAL enable 금지 상태) |
| Trailing | **SHADOW** (기존 trailing forward shadow) |
| Time Exit | **RESEARCH** |
| H2 / H3 | **SHADOW**, N300 + cost-aware 전 REAL promote 금지 |
| Exit Strategy Shadow V1 | MA/SL/TP/Trail/Time **비교 관측만** (REAL SELL 없음) |

기회 기반 거래: 하루 강제 N회 금지. 나쁜 시장에서 **0 trades 허용**.

## KIWOOM

장중 FIXED_SYMBOL / session timeline 기반. LIVE는 P0·장후 상태와 별도 승인 전 **NOT APPROVED**.  
상세: [trading/](trading/), [AI_TRADING_SAFETY.md](AI_TRADING_SAFETY.md)

## 안전

- LIVE 기본 OFF, startup fail-closed
- Kill Switch · Account Pause · 한도 우회 금지
- LIVE / PAPER 데이터·설정 분리
- Shadow 실패는 REAL을 차단하지 않음 (fail-open observability)

관련: [OPERATIONS.md](OPERATIONS.md) · [AI_TRADING_SAFETY.md](AI_TRADING_SAFETY.md) · [PROJECT_IMPLEMENTATION_STATUS.md](PROJECT_IMPLEMENTATION_STATUS.md)
