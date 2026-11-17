"""A Pushover alert that does not go is kept, tried again, and in the end sent or dropped."""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

import ramses_alerts as ra

WRAPPED = "unable to convert python exception"
T0 = datetime(2026, 11, 17, 19, 33, 23).timestamp()


@pytest.fixture
def box():
    return ra.AlertOutbox()


def _offline(box, now=T0):
    return box.queue("gateway", "RAMSES Gateway Offline", "gone offline", "1", now,
                     kind=ra.KIND_OFFLINE)


# ---------------------------------------------------------------- the pure outbox

def test_first_failure_queues_and_logs_one_warning(box):
    _offline(box)
    line = box.record("gateway", False, T0, WRAPPED)
    assert "gateway" in box.pending
    assert line[0] == "warning"
    assert "RAMSES Gateway Offline" in line[1]
    assert "30 minutes" in line[1] and "1 minute" in line[1]


def test_later_failures_log_nothing(box):
    _offline(box)
    box.record("gateway", False, T0, WRAPPED)
    assert box.record("gateway", False, T0 + 60, WRAPPED) is None
    assert box.record("gateway", False, T0 + 120, WRAPPED) is None
    assert box.pending["gateway"]["failures"] == 3


def test_retry_interval_is_respected(box):
    _offline(box)
    assert box.due(T0) == []                       # not yet tried: nothing to retry
    box.record("gateway", False, T0, WRAPPED)
    assert box.due(T0 + 5) == []
    assert box.due(T0 + 59.9) == []
    assert box.due(T0 + 60) == ["gateway"]
    box.record("gateway", False, T0 + 60, WRAPPED)
    assert box.due(T0 + 119) == []                 # counted from the last try, not the first
    assert box.due(T0 + 120) == ["gateway"]


def test_delivery_clears_and_says_how_long_it_took(box):
    _offline(box)
    box.record("gateway", False, T0, WRAPPED)
    line = box.record("gateway", True, T0 + 180)
    assert box.pending == {}
    assert box.due(T0 + 10_000) == []
    assert line == ("info", "Pushover sent after 3 minutes of trying: RAMSES Gateway Offline")


def test_delivery_first_time_is_the_plain_line(box):
    _offline(box)
    assert box.record("gateway", True, T0) == ("info", "Pushover sent: RAMSES Gateway Offline")
    assert box.pending == {}


def test_gives_up_after_thirty_minutes_with_one_warning(box):
    _offline(box)
    box.record("gateway", False, T0, WRAPPED)
    assert box.give_up(T0 + 1799) == []
    lines = box.give_up(T0 + 1800)
    assert len(lines) == 1 and lines[0][0] == "warning"
    assert "30 minutes" in lines[0][1] and "never delivered" in lines[0][1]
    assert box.pending == {}
    assert box.give_up(T0 + 5000) == []            # said once, never again
    assert box.due(T0 + 5000) == []


def test_the_retrying_always_ends(box):
    """Drive it the way the main loop does, every 5 s, against a send that never works."""
    _offline(box)
    box.record("gateway", False, T0, WRAPPED)
    tries, lines, now = 0, [], T0
    while now < T0 + 7200:
        now += 5
        lines += box.give_up(now)
        for sender in box.due(now):
            tries += 1
            line = box.record(sender, False, now, WRAPPED)
            if line:
                lines.append(line)
    assert tries == 29                             # once a minute, short of 30 minutes
    assert len(lines) == 1                         # only the give-up; the first line came earlier
    assert box.pending == {}


def test_a_newer_message_replaces_an_older_one(box):
    box.queue("watchdog", "cycle 1", "one", "0", T0)
    box.record("watchdog", False, T0, WRAPPED)
    box.queue("watchdog", "cycle 2", "two", "0", T0 + 900)
    waiting = box.pending["watchdog"]
    assert waiting["title"] == "cycle 2" and waiting["failures"] == 0
    assert waiting["raised"] == T0 + 900           # its own 30 minutes
    assert len(box.pending) == 1


def test_senders_do_not_replace_each_other(box):
    _offline(box)
    box.queue("watchdog", "cycle 1", "one", "0", T0)
    assert set(box.pending) == {"gateway", "watchdog"}


def test_restored_says_the_offline_alert_was_never_sent(box):
    _offline(box)
    box.record("gateway", False, T0, WRAPPED)
    msg = box.queue("gateway", "RAMSES Gateway Restored", "gateway is back online", "0",
                    T0 + 600, kind=ra.KIND_RESTORED)
    assert msg["body"] == ("gateway is back online. The alert that it had gone offline, "
                           "raised at 7:33pm, could not be sent")
    assert box.pending["gateway"] is msg


def test_restored_after_the_offline_alert_was_given_up_on(box):
    _offline(box)
    box.record("gateway", False, T0, WRAPPED)
    box.give_up(T0 + 1800)
    msg = box.queue("gateway", "RAMSES Gateway Restored", "back online", "0", T0 + 4000,
                    kind=ra.KIND_RESTORED)
    assert "7:33pm" in msg["body"]
    again = box.queue("gateway", "RAMSES Gateway Restored", "back online", "0", T0 + 9000,
                      kind=ra.KIND_RESTORED)
    assert again["body"] == "back online"          # said once


def test_restored_is_untouched_when_the_offline_alert_got_through(box):
    _offline(box)
    box.record("gateway", False, T0, WRAPPED)
    box.record("gateway", True, T0 + 60)
    msg = box.queue("gateway", "RAMSES Gateway Restored", "back online", "0", T0 + 600,
                    kind=ra.KIND_RESTORED)
    assert msg["body"] == "back online"


def test_plain_english_for_indigos_wrapped_error():
    text = ra.explain_failure(WRAPPED)
    assert "unable to convert" not in text
    assert "Pushover plugin could not send it" in text and "no internet" in text
    assert "no internet" in ra.explain_failure("Unable to convert Python exception ")
    assert ra.explain_failure("HTTP 500 from api.pushover.net") == "HTTP 500 from api.pushover.net"
    assert ra.explain_failure("") == "the Pushover plugin gave no reason"


def test_first_failure_line_carries_the_translation(box):
    _offline(box)
    line = box.record("gateway", False, T0, WRAPPED)
    assert "unable to convert" not in line[1]
    assert "no internet" in line[1]


@pytest.mark.parametrize("when, words", [
    (datetime(2026, 11, 17, 19, 32), "7:32pm"),
    (datetime(2026, 11, 17, 19, 0), "7pm"),
    (datetime(2026, 11, 17, 0, 5), "12:05am"),
    (datetime(2026, 11, 17, 12, 0), "12pm"),
    (datetime(2026, 11, 17, 9, 7), "9:07am"),
])
def test_clock_words(when, words):
    assert ra.clock_words(when) == words
    assert ra.clock_words(when.timestamp()) == words


# ---------------------------------------------------------------- the plugin around it

@pytest.fixture
def sender(plug, rp, monkeypatch):
    clock = [T0]
    monkeypatch.setattr(rp.time, "time", lambda: clock[0])
    pushover = MagicMock()
    pushover.isEnabled.return_value = True
    pushover.isRunning.return_value = True
    # Assigned and put back by hand: pytest 9.2's monkeypatch undo deletes a MagicMock child.
    rp.indigo.server.getPlugin = MagicMock(return_value=pushover)
    plug.gateway_id = "18:123456"
    yield plug, clock, pushover
    rp.indigo.server.getPlugin = MagicMock()


def _logged(plug, level):
    return [c.args[0] for c in getattr(plug.logger, level).call_args_list]


def test_plugin_retries_a_lost_offline_alert_until_it_goes(sender):
    p, clock, pushover = sender
    pushover.executeAction.side_effect = Exception(WRAPPED)
    p._send_gateway_alert("offline")
    assert pushover.executeAction.call_count == 1
    assert p.logger.error.call_count == 0          # a send to be retried is a warning
    assert len(_logged(p, "warning")) == 1
    assert "no internet" in _logged(p, "warning")[0]

    for _ in range(11):                            # 55 s of main-loop passes: no retry yet
        clock[0] += 5
        p._retry_alerts(clock[0])
    assert pushover.executeAction.call_count == 1
    clock[0] += 5
    p._retry_alerts(clock[0])
    assert pushover.executeAction.call_count == 2
    assert len(_logged(p, "warning")) == 1         # the second failure is silent

    pushover.executeAction.side_effect = None
    clock[0] += 60
    p._retry_alerts(clock[0])
    assert pushover.executeAction.call_count == 3
    assert p.alert_outbox.pending == {}
    assert _logged(p, "info")[-1] == (
        "[Gateway] Pushover sent after 2 minutes of trying: RAMSES Gateway Offline")
    clock[0] += 600
    p._retry_alerts(clock[0])
    assert pushover.executeAction.call_count == 3  # nothing left to send


def test_plugin_restored_alert_says_the_offline_one_was_lost(sender):
    p, clock, pushover = sender
    pushover.executeAction.side_effect = Exception(WRAPPED)
    p._send_gateway_alert("offline")
    pushover.executeAction.side_effect = None
    clock[0] += 400
    p._send_gateway_alert("restored")
    props = pushover.executeAction.call_args.kwargs["props"]
    assert props["msgTitle"] == "RAMSES Gateway Restored"
    assert props["msgBody"].endswith(
        "is back online. The alert that it had gone offline, raised at 7:33pm, could not be sent")
    assert p.alert_outbox.pending == {}


def test_plugin_gives_up_after_thirty_minutes(sender):
    p, clock, pushover = sender
    pushover.executeAction.side_effect = Exception(WRAPPED)
    p._send_watchdog_pushover("RAMSES watchdog giving up", "needs a human", priority="1")
    while clock[0] < T0 + 3600:
        clock[0] += 5
        p._retry_alerts(clock[0])
    assert p.alert_outbox.pending == {}
    assert pushover.executeAction.call_count == 30
    warnings = _logged(p, "warning")
    assert len(warnings) == 2                      # first failure, then the give-up
    assert "given up on" in warnings[1]
    assert p.logger.error.call_count == 0


def test_plugin_treats_enabled_but_not_running_as_a_failure_to_retry(sender):
    p, clock, pushover = sender
    pushover.isRunning.return_value = False
    p._send_watchdog_pushover("RAMSES watchdog power-cycled gateway", "cycled")
    assert pushover.executeAction.call_count == 0
    assert "watchdog" in p.alert_outbox.pending
    assert "enabled but not running" in _logged(p, "warning")[0]
    pushover.isRunning.return_value = True
    clock[0] += 60
    p._retry_alerts(clock[0])
    assert pushover.executeAction.call_count == 1
    assert p.alert_outbox.pending == {}


def test_plugin_does_not_retry_when_pushover_is_switched_off(sender):
    p, clock, pushover = sender
    pushover.isEnabled.return_value = False
    p._send_gateway_alert("offline")
    assert p.alert_outbox.pending == {}
    assert "not enabled" in _logged(p, "warning")[0]
    clock[0] += 600
    p._retry_alerts(clock[0])
    assert pushover.executeAction.call_count == 0
