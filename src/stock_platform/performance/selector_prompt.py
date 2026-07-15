from __future__ import annotations

import json

from stock_platform.performance.selector_models import (
    StrategySelectionCandidate,
)


class StrategySelectorPromptBuilder:
    @staticmethod
    def build(
        *,
        candidates: list[StrategySelectionCandidate],
        market_context: dict,
        risk_context: dict,
    ) -> str:
        candidate_payload = [
            {
                "rank": item.rank,
                "strategy_code": item.strategy_code,
                "strategy_performance_run_id": (
                    item.strategy_performance_run_id
                ),
                "market_code": item.market_code,
                "symbol": item.symbol,
                "run_type": item.run_type,
                "score": str(item.score),
                "total_return_rate": str(
                    item.total_return_rate
                ),
                "maximum_drawdown_rate": str(
                    item.maximum_drawdown_rate
                ),
                "sharpe_ratio": (
                    str(item.sharpe_ratio)
                    if item.sharpe_ratio is not None
                    else None
                ),
                "sortino_ratio": (
                    str(item.sortino_ratio)
                    if item.sortino_ratio is not None
                    else None
                ),
                "win_rate": str(item.win_rate),
                "profit_factor": (
                    str(item.profit_factor)
                    if item.profit_factor is not None
                    else None
                ),
                "total_trade_count": (
                    item.total_trade_count
                ),
            }
            for item in candidates
        ]

        return f"""
당신은 한국 주식·암호화폐 자동매매 플랫폼의 전략 선택기입니다.

목표:
- 후보 전략 중 현재 시장과 위험제약에 가장 적합한 전략 1개를 선택합니다.
- 수익률만 높고 MDD가 과도한 전략은 피합니다.
- 거래 수가 지나치게 적은 전략은 신뢰도를 낮게 평가합니다.
- Walk Forward 성과가 있으면 단순 Backtest보다 우선합니다.
- 확신이 낮더라도 후보 목록 밖의 전략을 만들지 않습니다.

후보 전략:
{json.dumps(candidate_payload, ensure_ascii=False, indent=2)}

시장 컨텍스트:
{json.dumps(market_context, ensure_ascii=False, indent=2, default=str)}

위험 컨텍스트:
{json.dumps(risk_context, ensure_ascii=False, indent=2, default=str)}

반드시 아래 JSON 형식만 출력하세요.

{{
  "selected_strategy_code": "후보의 strategy_code",
  "selected_performance_run_id": 123,
  "confidence_score": 0.0,
  "reason": "선택 이유",
  "risk_notes": ["위험 메모"],
  "alternatives": ["대안 전략 코드"]
}}

제약:
- confidence_score는 0 이상 1 이하입니다.
- selected_performance_run_id는 선택한 후보와 일치해야 합니다.
- 설명 문장이나 Markdown 코드블록을 추가하지 마세요.
""".strip()
