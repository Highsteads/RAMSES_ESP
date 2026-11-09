"""Grouped setpoints are paced, superseded safely and confirmed from real replies."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest


@pytest.fixture
def sender(plug, rp, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(rp.time, "time", lambda: clock[0])
    plug.mqtt_connected = True
    plug.gateway_online = True
    plug.gateway_id = "18:123456"
    plug.controller_id = "01:123456"
    plug.mqtt_client = MagicMock()
    plug.mqtt_client.publish.return_value = SimpleNamespace(rc=0)
    monkeypatch.setattr(plug, "_find_zone_device", lambda z: SimpleNamespace(
        id=z, address=str(z), name=f"Zone {z}", states={}))
    return plug, clock


def test_five_zone_burst_becomes_five_spaced_sends(sender):
    p, clock = sender
    for zone in range(5):
        assert p._queue_setpoint(zone, 22)
    assert p.mqtt_client.publish.call_count == 1
    assert p.pending_setpoints[1]["first"] is None
    for zone in range(1, 5):
        clock[0] += 5
        p._retry_setpoints(clock[0])
        assert p.mqtt_client.publish.call_count == zone + 1
        assert p.pending_setpoints[zone]["first"] == clock[0]
    # Confirm actual commands, not acceptance by the MQTT client.
    for zone in range(5):
        p._confirm_mode(zone, {"mode": "permanent override", "until": "",
                              "setpoint": 22, "rx": clock[0]})
    assert not p.pending_setpoints


def test_latest_queued_value_wins_and_old_report_cannot_confirm(sender):
    p, clock = sender
    p._queue_setpoint(0, 22)
    p._queue_setpoint(1, 22)
    p._queue_setpoint(1, 18)
    p._confirm_mode(1, {"mode": "permanent override", "until": "", "setpoint": 18})
    assert p.pending_setpoints[1]["first"] is None
    clock[0] += 5
    p._retry_setpoints(clock[0])
    assert p.pending_setpoints[1]["sp"] == 18
    assert p.pending_setpoints[1]["sends"] == 1
    assert "0708" in p.mqtt_client.publish.call_args.args[1]


def test_renewal_does_not_reset_unconfirmed_deadline(sender):
    p, clock = sender
    until = datetime.now() + timedelta(hours=2)
    p._queue_setpoint(0, 22, until)
    first = p.pending_setpoints[0]["first"]
    clock[0] += 299
    assert p._queue_setpoint(0, 22, until + timedelta(minutes=5))
    assert p.pending_setpoints[0]["budget_first"] == first
    assert p.pending_setpoints[0]["until"] == until + timedelta(minutes=5)
    clock[0] += 2
    p._retry_setpoints(clock[0])
    assert 0 not in p.pending_setpoints
    assert "not confirmed" in p.logger.warning.call_args.args[0]


def test_queued_command_expires_during_outage(sender):
    p, clock = sender
    p._queue_setpoint(0, 22)
    p._queue_setpoint(1, 22)
    p.gateway_online = False
    clock[0] += 121
    p._retry_setpoints(clock[0])
    assert 1 not in p.pending_setpoints
    assert p.mqtt_client.publish.call_count == 1


def test_retry_round_is_paced_too(sender):
    p, clock = sender
    for zone in range(4):
        p._queue_setpoint(zone, 22)
        clock[0] += 5
    before = p.mqtt_client.publish.call_count
    clock[0] += 60
    p._retry_setpoints(clock[0])
    p._retry_setpoints(clock[0])
    assert p.mqtt_client.publish.call_count == before + 1


def test_disabled_zone_never_leaves_queue(sender, monkeypatch):
    p, clock = sender
    p._queue_setpoint(0, 22)
    p._queue_setpoint(1, 22)
    find = p._find_zone_device
    monkeypatch.setattr(p, "_find_zone_device", lambda z: SimpleNamespace(enabled=False) if z == 1 else find(z))
    clock[0] += 5
    p._retry_setpoints(clock[0])
    assert 1 not in p.pending_setpoints
    assert p.mqtt_client.publish.call_count == 1


def test_changed_expiry_is_delivered_as_new_intent(sender):
    p, clock = sender
    until = datetime.now() + timedelta(hours=2)
    p._queue_setpoint(0, 22, until)
    clock[0] += 5
    shorter = until - timedelta(hours=1)
    p._queue_setpoint(0, 22, shorter)
    assert p.pending_setpoints[0]["until"] == shorter
    assert p.pending_setpoints[0]["sends"] == 2
    assert p.pending_setpoints[0]["first"] == clock[0]
    p._confirm_mode(0, {"mode": "temporary override", "until": until.strftime("%Y-%m-%d %H:%M"), "setpoint": 22})
    assert 0 in p.pending_setpoints
    p._confirm_mode(0, {"mode": "temporary override", "until": shorter.strftime("%Y-%m-%d %H:%M"), "setpoint": 22})
    assert not p.pending_setpoints


def test_a_pass_just_under_the_loop_period_still_sends(sender):
    """The main loop sleeps 5 s; a strict 5 s gap would skip every other pass."""
    p, clock = sender
    p._queue_setpoint(0, 22)
    p._queue_setpoint(1, 22)
    clock[0] += 4.9
    p._retry_setpoints(clock[0])
    assert p.mqtt_client.publish.call_count == 2


def test_changed_expiry_after_max_sends_still_goes_out(sender):
    p, clock = sender
    until = datetime.now() + timedelta(hours=2)
    p._queue_setpoint(0, 22, until)
    p.pending_setpoints[0]["sends"] = 5
    clock[0] += 20
    p._queue_setpoint(0, 22, until + timedelta(minutes=5))
    assert p.mqtt_client.publish.call_count == 2
