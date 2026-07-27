#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_paho_v2.py
# Description: Pins the paho-mqtt 2.x contract — the required callback_api_version
#              positional and the VERSION2 connect/disconnect signatures. Getting
#              any of these wrong means the gateway silently never connects, and
#              this plugin drives 12 heating zones.
# Author:      CliveS & Claude Opus 5
# Date:        27-07-2026
# Version:     1.0

from unittest.mock import MagicMock

from conftest import (RC_DISCONNECTED, RC_KEEPALIVE, RC_NOT_AUTHORIZED,
                      RC_SUCCESS, FakeCallbackAPIVersion)


# --------------------------------------------------------------------------
# Client construction
# --------------------------------------------------------------------------

def _connect(plug, rp, **kwargs):
    """Drive _mqtt_connect with a recording Client and return the mock."""
    plug.broker_host     = "192.168.1.10"
    plug.broker_port     = 1883
    plug.broker_username = kwargs.get("username", "")
    plug.broker_password = kwargs.get("password", "")
    plug.mqtt_client     = None
    fake_client_cls = MagicMock()
    rp.mqtt.Client  = fake_client_cls
    plug._mqtt_connect()
    return fake_client_cls


def test_client_is_built_with_the_version2_callback_api(plug, rp):
    """paho 2.x REQUIRES callback_api_version as the first positional. Omit it
    and Client() raises, so the gateway never connects and 12 heating zones go
    quiet — with nothing in the log that names the cause."""
    cls = _connect(plug, rp)
    assert cls.called
    args, _ = cls.call_args
    assert args[0] is FakeCallbackAPIVersion.VERSION2


def test_client_id_and_clean_session_are_still_passed(plug, rp):
    """clean_session stays legal because the default protocol is MQTTv311."""
    cls = _connect(plug, rp)
    _, kwargs = cls.call_args
    assert kwargs["clean_session"] is True
    assert kwargs["client_id"].startswith("indigo-ramses-esp-")


def test_credentials_are_applied_when_configured(plug, rp):
    cls = _connect(plug, rp, username="ha", password="secret")
    cls.return_value.username_pw_set.assert_called_once_with(
        username="ha", password="secret")


def test_no_credentials_means_no_username_call(plug, rp):
    cls = _connect(plug, rp)
    assert not cls.return_value.username_pw_set.called


def test_the_loop_is_started(plug, rp):
    cls = _connect(plug, rp)
    assert cls.return_value.loop_start.called


# --------------------------------------------------------------------------
# _on_connect — VERSION2 signature, ReasonCode rather than an int
# --------------------------------------------------------------------------

def test_on_connect_success_subscribes_and_marks_connected(plug, rp):
    client = MagicMock()
    plug.gateway_id         = ""
    plug.gateway_subscribed = False
    plug._on_connect(client, None, {}, RC_SUCCESS, None)
    assert plug.mqtt_connected is True
    client.subscribe.assert_called_once_with(rp.TOPIC_INFO_WILDCARD, qos=0)


def test_on_connect_also_resubscribes_a_known_gateway(plug, rp):
    client = MagicMock()
    plug.gateway_id         = "18:123456"
    plug.gateway_subscribed = False
    plug._on_connect(client, None, {}, RC_SUCCESS, None)
    topics = [c.args[0] for c in client.subscribe.call_args_list]
    assert f"{rp.RAMSES_ROOT}/18:123456/rx" in topics
    assert plug.gateway_subscribed is True


def test_on_connect_failure_logs_the_readable_reason(plug):
    """str(ReasonCode) is already human-readable. The old 1-5 int table could
    never match again under VERSION2, which is why it was deleted."""
    plug._on_connect(MagicMock(), None, {}, RC_NOT_AUTHORIZED, None)
    assert plug.mqtt_connected is False
    msg = plug.logger.error.call_args.args[0]
    assert "Not authorized" in msg


def test_on_connect_accepts_a_missing_properties_argument(plug):
    """Some brokers/paths call back without properties — the default must hold."""
    plug._on_connect(MagicMock(), None, {}, RC_SUCCESS)
    assert plug.mqtt_connected is True


# --------------------------------------------------------------------------
# _on_disconnect — VERSION2 adds disconnect_flags before the reason code
# --------------------------------------------------------------------------

def test_on_disconnect_clean_is_reported_as_clean(plug):
    plug.mqtt_connected = True
    plug._on_disconnect(MagicMock(), None, None, RC_DISCONNECTED, None)
    assert plug.mqtt_connected is False
    assert "cleanly" in plug.logger.info.call_args.args[0]
    assert not plug.logger.warning.called


def test_on_disconnect_unexpected_warns_with_the_reason(plug):
    plug.mqtt_connected = True
    plug._on_disconnect(MagicMock(), None, None, RC_KEEPALIVE, None)
    msg = plug.logger.warning.call_args.args[0]
    assert "Keep alive timeout" in msg and "reconnect" in msg


def test_on_disconnect_queues_offline_for_every_zone(plug):
    plug.zone_devices = {1: object(), 2: object()}
    plug.pending_updates = {}
    plug._on_disconnect(MagicMock(), None, None, RC_KEEPALIVE, None)
    assert plug.pending_updates[1]["offline"] is True
    assert plug.pending_updates[2]["offline"] is True


def test_an_unconvertible_reason_code_is_treated_as_unexpected(plug):
    """Safe way round: reconnect rather than assume a tidy shutdown."""
    plug.mqtt_connected = True
    plug._on_disconnect(MagicMock(), None, None, object(), None)
    assert plug.logger.warning.called


def test_a_bare_zero_reason_code_still_reads_as_clean(plug):
    """Defensive path for anything handing back a plain int."""
    plug.mqtt_connected = True
    plug._on_disconnect(MagicMock(), None, None, 0, None)
    assert "cleanly" in plug.logger.info.call_args.args[0]
