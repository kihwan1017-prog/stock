# Order/Fill Autotrading Dashboard — Evidence

- FINAL_VERDICT: **ORDER_FILL_AUTOTRADING_DASHBOARD_COMPLETE**
- ROUTE: /admin/orders
- AUTH_BROWSER_VERIFY: PASS
- SUMMARY_IMPLEMENTED: true
- TIMELINE_CHART: true
- SYMBOL_PNL_CHART: true
- EXIT_REASON_CHART: true
- PIPELINE_SUMMARY: true
- MANUAL_ORDER_MOVED_TO_OPERATIONS_TOOL: true
- PAPER_ORDER_MOVED_TO_OPERATIONS_TOOL: true
- TABLE_USER_FRIENDLY: true
- TRACE_LINK: true
- PROCESS_VERSION_LINK: true
- CONSOLE_ERRORS: 0
- CONSOLE_WARNINGS: 0
- REAL_ORDER_MUTATION: 0
- REAL_POLICY_MUTATION: 0
- http_404: 0
- http_500: 0

## DATA_SOT
```json
{
  "orders": "GET /orders",
  "pnl_exit": "GET /admin/dashboard/autotrading-performance",
  "pipeline": "GET /admin/autotrading/uba/{id}/pipeline-liveness",
  "traces": "GET /admin/autotrading/traces"
}
```

## UI
```json
{
  "nav_status": 200,
  "final_url": "http://127.0.0.1:3000/admin/orders",
  "login_redirect": false,
  "has_market_filter": true,
  "has_ops_collapse": true,
  "no_endpoint_main_label": true,
  "empty_state_friendly": true,
  "body_snippet": "KIKI Admin 대시보드 계좌·자산 자동매매 키움 자동매매 업비트 자동매매 프로세스·버전 주문·체결 전략·분석 리스크·안전 알림 시스템 Admin Console 주문·체결 API 연결됨 Admin admin Theme Bootstrap Admin 주문·체결 자동매매 주문·체결 모니터링 · 오늘 AUTO 기본 · 수동/Paper는 운영 도구 Kill Switch OFF 실거래는 LIVE Gate + 명시 승인 시에만 Admin / 주문·체결 전체 업비트 키움증권 자동매매 종목 전체 상태 기본: 오늘 · 자동매매 오늘 매수 10 오늘 매도 7 체결 16 미체결 0 취소 1 실현손익 -10원 승/패 1/8 승률 +11.11% 오늘 체결 흐름 (시간대) 00:00 03:00 06:00 09:00 12:00 15:00 18:00 21:00 0 1 2 3 4 매수매도 종목별 실현손익 이익 큰 순 -25 0 25 50 75 KRW-DRV KRW-SUI KRW-EUL KRW-ENA KRW-XLM KRW-RE KRW-STX 매도 사유별 성과 사유 건수 승 패 순손익 전략 신호 7 1 6 10원 트레일링 스탑 2 0 2 -20원 업비트 파이프라인 Signal: 500 Ad"
}
```
- GIT_COMMIT: **c0bfa45**
