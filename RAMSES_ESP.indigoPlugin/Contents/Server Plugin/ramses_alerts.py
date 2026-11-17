#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    ramses_alerts.py
# Description: Keeps a Pushover alert that could not be sent and says when to try it again.
#              Pure logic with no indigo import, so tests can drive it without a server.
# Author:      CliveS & Claude Fable 5.2
# Date:        17-11-2026 20:30
# Version:     1.0
#
# Why it exists (measured 17-11-2026): the router was swapped, the internet was down for some
# minutes, and the "gateway offline" alert was tried once, failed and was lost. The plugin
# logged "unable to convert python exception", which is what Indigo raises in the caller when
# another plugin's action raises.
#
# One message is kept per sender ("gateway", "watchdog"). A newer message from the same sender
# replaces an older one still waiting. A waiting message is tried again no more often than
# RETRY_SECONDS and is dropped GIVE_UP_SECONDS after it was raised, so the retrying always ends.

from datetime import datetime

RETRY_SECONDS   = 60      # never try a waiting alert more often than this
GIVE_UP_SECONDS = 1800    # drop an alert this long after it was raised

KIND_OFFLINE  = "offline"
KIND_RESTORED = "restored"

_INDIGO_WRAPPED_ERROR = "unable to convert python exception"


def explain_failure(reason):
    """Why a send failed, in plain words.

    "unable to convert python exception" is Indigo's own wording for "the other plugin's
    action raised", and it tells a reader nothing. The usual cause is no internet.
    """
    text = str(reason or "").strip()
    if not text:
        return "the Pushover plugin gave no reason"
    if _INDIGO_WRAPPED_ERROR in text.lower():
        return "the Pushover plugin could not send it (most often because there is no internet)"
    return text


def clock_words(when):
    """A time of day as a person says it: 7:32pm, 7pm, 12:05am."""
    if not isinstance(when, datetime):
        when = datetime.fromtimestamp(float(when))
    hour   = when.hour % 12 or 12
    suffix = "am" if when.hour < 12 else "pm"
    if when.minute == 0:
        return f"{hour}{suffix}"
    return f"{hour}:{when.minute:02d}{suffix}"


def _minutes_words(seconds):
    minutes = max(1, int(round(seconds / 60.0)))
    return "1 minute" if minutes == 1 else f"{minutes} minutes"


class AlertOutbox:
    """The alerts still waiting to be sent, one per sender.

    The caller does the sending. For each message it calls queue(), tries the send, and
    reports the outcome with record(). From its main loop it calls give_up() and then due().
    record() and give_up() hand back (level, text) log lines; the outbox itself logs nothing.
    """

    def __init__(self, retry_seconds=RETRY_SECONDS, give_up_seconds=GIVE_UP_SECONDS):
        self.retry_seconds   = retry_seconds
        self.give_up_seconds = give_up_seconds
        self.pending         = {}    # sender -> message dict
        self.lost_offline    = {}    # sender -> time an "offline" alert was raised and never sent

    def queue(self, sender, title, body, priority, now, kind=""):
        """Take a new message, replacing any older one still waiting from this sender.

        A "restored" message says so when the "offline" one before it never got through.
        """
        old = self.pending.pop(sender, None)
        if old is not None and old["kind"] == KIND_OFFLINE and old["failures"] > 0:
            self.lost_offline[sender] = old["raised"]
        if kind == KIND_RESTORED:
            lost_at = self.lost_offline.pop(sender, None)
            if lost_at is not None:
                body = (f"{body}. The alert that it had gone offline, raised at "
                        f"{clock_words(lost_at)}, could not be sent")
        else:
            self.lost_offline.pop(sender, None)
        message = {
            "title":      title,
            "body":       body,
            "priority":   priority,
            "kind":       kind,
            "raised":     now,
            "last_try":   None,
            "failures":   0,
        }
        self.pending[sender] = message
        return message

    def discard(self, sender):
        """Forget a waiting message without any log line (Pushover is not there at all)."""
        self.pending.pop(sender, None)

    def record(self, sender, delivered, now, reason=""):
        """Note the outcome of a send. Returns one (level, text) log line, or None.

        Only the first failure and the final delivery are worth a line; the failed tries in
        between return None so the log is not filled with them.
        """
        message = self.pending.get(sender)
        if message is None:
            return None
        if delivered:
            del self.pending[sender]
            if message["failures"] == 0:
                return ("info", f"Pushover sent: {message['title']}")
            waited = _minutes_words(now - message["raised"])
            return ("info", f"Pushover sent after {waited} of trying: {message['title']}")
        message["last_try"]  = now
        message["failures"] += 1
        if message["failures"] > 1:
            return None
        return (
            "warning",
            f"Pushover alert not sent yet: {message['title']} - {explain_failure(reason)}. "
            f"Trying again every {_minutes_words(self.retry_seconds)} "
            f"for up to {_minutes_words(self.give_up_seconds)}",
        )

    def give_up(self, now):
        """Drop every message that has waited too long. Returns one log line for each."""
        lines = []
        for sender in list(self.pending):
            message = self.pending[sender]
            if now - message["raised"] < self.give_up_seconds:
                continue
            del self.pending[sender]
            if message["kind"] == KIND_OFFLINE:
                self.lost_offline[sender] = message["raised"]
            lines.append((
                "warning",
                f"Pushover alert given up on after {_minutes_words(now - message['raised'])}: "
                f"{message['title']} - it was never delivered",
            ))
        return lines

    def due(self, now):
        """The senders whose waiting message should be tried again now."""
        ready = []
        for sender, message in self.pending.items():
            if message["failures"] == 0 or message["last_try"] is None:
                continue                      # not yet tried: the caller is about to
            if now - message["last_try"] >= self.retry_seconds:
                ready.append(sender)
        return ready
