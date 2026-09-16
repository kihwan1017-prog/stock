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
        self.history = []

    def scalar(self, statement):
        return self.entity

    def scalars(self, statement):
        return list(reversed(self.history))

    def add(self, entity):
        self.added.append(entity)
        name = entity.__class__.__name__
        if name == "KillSwitchEntity":
            self.entity = entity
        elif name == "KillSwitchHistoryEntity":
            if getattr(entity, "kill_switch_history_id", None) is None:
                entity.kill_switch_history_id = (
                    len(self.history) + 1
                )
            self.history.append(entity)

    def commit(self):
        pass

    def refresh(self, entity):
        if getattr(entity, "kill_switch_id", None) is None:
            entity.kill_switch_id = 1


def test_default_state_is_inactive() -> None:
    session = FakeSession()
    state = KillSwitchService(session).get_state()

    assert state.status == KillSwitchStatus.INACTIVE
    assert state.exchange_scope == ()


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


def test_activate_with_exchange_codes() -> None:
    session = FakeSession()
    service = KillSwitchService(session)
    state = service.activate(
        actor="admin",
        reason="upbit only",
        exchange_codes=["upbit", "KRX"],
    )
    assert "EXCHANGES=" in (state.reason or "")
    assert state.exchange_scope == ("KRX", "UPBIT")
    assert service.active_exchange_scope() == {
        "KRX",
        "UPBIT",
    }


def test_list_history_returns_actions() -> None:
    session = FakeSession()
    service = KillSwitchService(session)
    service.activate(actor="a", reason="on")
    service.deactivate(actor="a", reason="off")
    rows = service.list_history(limit=10)
    assert len(rows) == 2
    assert {row.action_code for row in rows} == {
        "ACTIVATE",
        "DEACTIVATE",
    }
