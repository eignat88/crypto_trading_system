import asyncio

from app.risk.emergency_stop import EmergencyReason, EmergencyStop


def test_emergency_stop_runs_safety_actions_once():
    actions = []

    class Notifier:
        def notify(self, notification):
            actions.append(("notify", notification.level.value))

    stop = EmergencyStop(
        disable_trading=lambda: actions.append("disable"),
        close_execution=lambda: actions.append("close"),
        save_checkpoint=lambda: actions.append("checkpoint"),
        record_risk_event=lambda reason, detail: actions.append((reason, detail)),
        stop_runtime=lambda: actions.append("stop"),
        notifier=Notifier(),
    )
    assert asyncio.run(stop.activate(EmergencyReason.EMERGENCY_MANUAL_STOP, "operator"))
    assert not asyncio.run(stop.activate(EmergencyReason.EMERGENCY_RUNTIME_ERROR))
    assert actions == [
        "disable",
        "close",
        "checkpoint",
        (EmergencyReason.EMERGENCY_MANUAL_STOP, "operator"),
        ("notify", "CRITICAL"),
        "stop",
    ]
