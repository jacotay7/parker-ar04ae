"""Reply parsing: values, typed accessors, status bits, error detection."""

import pytest

from parker_ar04ae.response import Response, looks_like_error


def r(command, *lines):
    return Response(command=command, lines=list(lines))


def test_value_is_the_first_line_verbatim():
    assert r("TREV", "Aries OS Revision 3.30").value == "Aries OS Revision 3.30"


def test_value_keeps_text_that_resembles_the_command():
    # The drive does not repeat the command name, so nothing should be stripped.
    assert r("DMTR", "OTHER=R200D").value == "OTHER=R200D"


def test_value_of_empty_response():
    assert r("TREV").value == ""
    assert r("TREV").empty


def test_as_int():
    assert r("ERES", "944000").as_int() == 944000
    assert r("TPE", "-6").as_int() == -6


def test_as_float():
    assert r("TVBUS", "163.1").as_float() == pytest.approx(163.1)
    assert r("TVEL", "0.000").as_float() == pytest.approx(0.0)


def test_as_bool():
    assert r("DRIVE", "1").as_bool() is True
    assert r("DRIVE", "0").as_bool() is False


def test_as_bool_rejects_non_boolean():
    with pytest.raises(ValueError):
        r("TREV", "Aries OS Revision 3.30").as_bool()


def test_as_bits_removes_underscores():
    assert r("TOUT", "0000_0000_0000_0011").as_bits() == "0000000000000011"


def test_bit_is_one_based():
    resp = r("TOUT", "0000_0000_0000_0011")
    assert resp.bit(15) is True
    assert resp.bit(16) is True
    assert resp.bit(1) is False


def test_set_bits_lists_one_based_positions():
    assert r("TOUT", "0000_0000_0000_0011").set_bits() == [15, 16]
    assert r("TAS", "0000_0000_0000_0000").set_bits() == []


def test_bit_out_of_range_raises():
    with pytest.raises(IndexError):
        r("TAS", "0000").bit(9)
    with pytest.raises(IndexError):
        r("TAS", "0000").bit(0)


def test_error_reply_detected():
    resp = r("TASX", "ERROR: Unknown Command")
    assert resp.is_error
    assert resp.error_message == "Unknown Command"


def test_error_detection_is_case_insensitive():
    assert r("X", "error: Something Went Wrong").is_error


def test_value_replies_are_not_errors():
    assert not r("TREV", "Aries OS Revision 3.30").is_error
    assert not r("TPE", "0").is_error
    assert not r("TAS", "0000_0000_0000_0000").is_error


def test_a_value_merely_mentioning_error_is_not_one():
    assert not r("X", "no error present").is_error


def test_error_message_is_none_when_there_is_no_error():
    assert r("TPE", "0").error_message is None


def test_looks_like_error_requires_the_prefix():
    assert looks_like_error("ERROR: Unknown Command")
    assert not looks_like_error("Unknown Command")


def test_text_joins_lines():
    assert r("X", "A", "B").text == "A\nB"
