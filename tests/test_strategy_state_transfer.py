from stock_platform.strategy_deployment.state_transfer import (
    StrategyStateTransferService,
)


class StatefulStrategy:
    def __init__(self):
        self.state = {"count": 1}

    def export_state(self):
        return self.state

    def import_state(self, state):
        self.state = dict(state)


def test_exports_and_imports_state():
    source = StatefulStrategy()
    target = StatefulStrategy()
    target.state = {}

    state = StrategyStateTransferService.export_state(
        source
    )
    StrategyStateTransferService.import_state(
        target,
        state,
    )

    assert target.state == {"count": 1}
