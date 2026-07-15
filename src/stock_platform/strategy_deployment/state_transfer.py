from __future__ import annotations

from typing import Any


class StrategyStateTransferService:
    """
    전략이 export_state/import_state를 제공하면 상태를 이전한다.
    지원하지 않으면 빈 상태로 안전하게 시작한다.
    """

    @staticmethod
    def export_state(strategy: object) -> dict[str, Any]:
        exporter = getattr(strategy, "export_state", None)

        if exporter is None:
            return {}

        state = exporter()

        if state is None:
            return {}

        if not isinstance(state, dict):
            raise TypeError(
                "export_state() must return dict or None"
            )

        return state

    @staticmethod
    def import_state(
        strategy: object,
        state_payload: dict[str, Any],
    ) -> None:
        if not state_payload:
            return

        importer = getattr(strategy, "import_state", None)

        if importer is None:
            return

        importer(state_payload)
