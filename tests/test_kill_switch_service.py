from types import SimpleNamespace

from stock_platform.risk_engine.kill_switch_models import (
    KillSwitchStatus,
)
from stock_platform.risk_engine.kill_switch_service import (
    KillSwitchService,
)


class FakeSession:
    def __init__(self):
        self.entity = None
        self.added = []

    def scalar(self, statement):
        return self.entity

    def add(self, entity):
        self.added.append(entity)
        if entity.__class__.__name__ == "KillSwitchEntity":
            self.entity = entity

    def commit(self):
        pass

    def refresh(self, entity):
        if getattr(entity, "kill_switch_id", None) is None:
            entity.kill_switch_id = 1


def test_default_state_is_inactive() -> None:
    session = FakeSession()
    state = KillSwitchService(session).get_state()

    assert state.status == KillSwitchStatus.INACTIVE


def test_activate_and_deactivate() -> None:
    session = FakeSession()
    service = KillSwitchService(session)

    active = service.activate(
        actor="tester",
        reason="risk detected",
    )
    inactive = service.deactivate(
        actor="tester",
        reason="resolved",
    )

    assert active.status == KillSwitchStatus.ACTIVE
    assert inactive.status == KillSwitchStatus.INACTIVE
