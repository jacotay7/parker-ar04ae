"""Framing tests: what goes on the wire and how replies are cut into lines."""

import pytest

from parker_ar04ae.testing import FakePort
from parker_ar04ae.transport import SerialTransport


def make(replies=None, **kw):
    port = FakePort(replies or {}, **kw)
    transport = SerialTransport(port, timeout=0.3, quiet_time=0.02)
    transport.open()
    return port, transport


def test_write_line_appends_cr():
    port, t = make()
    t.write_line("TREV")
    assert port.written == ["TREV"]


def test_split_lines_handles_cr_crlf_and_lf():
    assert SerialTransport.split_lines("*A\r*B\r\n*C\n") == ["*A", "*B", "*C"]


def test_split_lines_drops_blanks_and_prompt():
    assert SerialTransport.split_lines("\r\n>\r\n*TREV 1.0\r\n>\r\n") == ["*TREV 1.0"]


def test_strip_echo_removes_leading_command():
    _, t = make()
    assert t.strip_echo("TREV", ["TREV", "*TREV 1.0"]) == ["*TREV 1.0"]


def test_strip_echo_is_case_insensitive():
    _, t = make()
    assert t.strip_echo("trev", ["TREV", "*TREV 1.0"]) == ["*TREV 1.0"]


def test_strip_echo_leaves_reply_alone_when_not_echoed():
    _, t = make()
    assert t.strip_echo("TREV", ["*TREV 1.0"]) == ["*TREV 1.0"]


def test_exchange_returns_reply_without_echo():
    _, t = make({"TREV": "*TREV 92-016966"})
    assert t.exchange("TREV") == ["*TREV 92-016966"]


def test_exchange_with_echo_off():
    _, t = make({"TREV": "*TREV 92-016966"}, echo=False)
    assert t.exchange("TREV") == ["*TREV 92-016966"]


def test_exchange_collects_multiline_reply():
    _, t = make({"TSTAT": ["*LINE ONE", "*LINE TWO", "*LINE THREE"]})
    assert t.exchange("TSTAT") == ["*LINE ONE", "*LINE TWO", "*LINE THREE"]


def test_read_raw_returns_empty_on_silence():
    port, t = make()
    port.replies.clear()
    assert t.read_raw(timeout=0.05) == ""


def test_flush_input_discards_pending_bytes():
    port, t = make({"TREV": "*TREV 1.0"})
    t.write_line("TREV")
    t.flush_input()
    assert t.read_raw(timeout=0.05) == ""


def test_transport_is_a_context_manager():
    port = FakePort()
    with SerialTransport(port) as t:
        assert t.is_open
    assert not port.is_open
