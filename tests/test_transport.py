"""Framing tests: what goes on the wire, and how replies are cut into lines."""

import pytest

from parker_ar04ae.protocol import DC1, ENQ
from parker_ar04ae.testing import FakePort
from parker_ar04ae.transport import SerialTransport


def make(replies=None, **kw):
    port = FakePort(replies or {}, **kw)
    transport = SerialTransport(port, timeout=0.3)
    transport.open()
    return port, transport


def test_write_line_appends_cr():
    port, t = make()
    t.write_line("TREV")
    assert port.written == ["TREV"]


def test_split_lines_handles_cr_crlf_and_lf():
    assert SerialTransport.split_lines("A\rB\r\nC\n") == ["A", "B", "C"]


def test_split_lines_drops_enq_and_dc1_markers():
    raw = f"TREV\r\n{DC1}\r\nAries OS Revision 3.30\r\n{ENQ}\r\n"
    assert SerialTransport.split_lines(raw) == ["TREV", "Aries OS Revision 3.30"]


def test_split_lines_drops_stray_control_characters():
    # str.strip() alone leaves these behind as phantom non-empty lines.
    assert SerialTransport.split_lines("\x05\r\n\x11\r\n\x00\r\nreal\r\n") == ["real"]


def test_split_lines_drops_blanks():
    assert SerialTransport.split_lines("\r\n\r\n0.000\r\n") == ["0.000"]


def test_strip_echo_removes_leading_command():
    _, t = make()
    assert t.strip_echo("TREV", ["TREV", "Aries OS 3.30"]) == ["Aries OS 3.30"]


def test_strip_echo_is_case_insensitive():
    _, t = make()
    assert t.strip_echo("trev", ["TREV", "Aries OS 3.30"]) == ["Aries OS 3.30"]


def test_strip_echo_leaves_reply_alone_when_not_echoed():
    _, t = make()
    assert t.strip_echo("TREV", ["Aries OS 3.30"]) == ["Aries OS 3.30"]


def test_exchange_returns_reply_without_echo_or_markers():
    _, t = make({"TREV": [DC1, "Aries OS Revision 3.30"]})
    assert t.exchange("TREV") == ["Aries OS Revision 3.30"]


def test_exchange_with_echo_off():
    _, t = make({"TVEL": "0.000"}, echo=False)
    assert t.exchange("TVEL") == ["0.000"]


def test_exchange_collects_multiline_reply():
    _, t = make({"TX": ["LINE ONE", "LINE TWO", "LINE THREE"]})
    assert t.exchange("TX") == ["LINE ONE", "LINE TWO", "LINE THREE"]


def test_reply_does_not_leak_into_the_next_one():
    # The CRLF trailing ENQ must be consumed, or it heads the next reply.
    _, t = make({"TPE": "0", "TVEL": "1.500"})
    assert t.exchange("TPE") == ["0"]
    assert t.exchange("TVEL") == ["1.500"]


def test_read_stops_promptly_at_enq():
    import time

    _, t = make({"TPE": "0"})
    t.timeout = 5.0
    start = time.monotonic()
    t.exchange("TPE")
    assert time.monotonic() - start < 1.0


def test_read_falls_back_to_timeout_without_enq():
    _, t = make({"TPE": "0"}, enq=False)
    assert t.exchange("TPE", timeout=0.15) == ["0"]


def test_read_raw_returns_empty_on_silence():
    _, t = make({}, default="")
    assert t.read_raw(timeout=0.05) == ""


def test_flush_input_discards_pending_bytes():
    port, t = make({"TREV": "Aries OS 3.30"})
    t.write_line("TREV")
    t.flush_input()
    assert t.read_raw(timeout=0.05) == ""


def test_transport_is_a_context_manager():
    port = FakePort()
    with SerialTransport(port) as t:
        assert t.is_open
    assert not port.is_open
