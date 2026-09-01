"""Reply parsing: values, types, status bits and error detection."""

import pytest

from parker_ar04ae.response import Response, looks_like_error


def r(command, *lines):
    return Response(command=command, lines=list(lines))


def test_value_strips_star_and_command_name():
    assert r("TREV", "*TREV 92-016966-01-5").value == "92-016966-01-5"


def test_value_strips_star_when_name_not_repeated():
    assert r("DRIVE", "*0").value == "0"


def test_value_of_empty_response():
    assert r("TREV").value == ""
    assert r("TREV").empty


def test_as_int_handles_leading_plus():
    assert r("TPE", "*TPE+12345").as_int() == 12345
    assert r("TPE", "*TPE-6").as_int() == -6


def test_as_float():
    assert r("TVEL", "*TVEL+1.2500").as_float() == pytest.approx(1.25)


def test_as_bool():
    assert r("DRIVE", "*DRIVE1").as_bool() is True
    assert r("DRIVE", "*DRIVE0").as_bool() is False


def test_as_bool_rejects_non_boolean():
    with pytest.raises(ValueError):
        r("TREV", "*TREV 1.0").as_bool()


def test_as_bits_removes_underscores():
    resp = r("TAS", "*TAS1000_0100_0000_0001")
    assert resp.as_bits() == "1000010000000001"


def test_bit_is_one_based():
    resp = r("TAS", "*TAS1000_0100_0000_0001")
    assert resp.bit(1) is True
    assert resp.bit(2) is False
    assert resp.bit(6) is True
    assert resp.bit(16) is True


def test_bit_out_of_range_raises():
    with pytest.raises(IndexError):
        r("TAS", "*TAS0000").bit(9)
    with pytest.raises(IndexError):
        r("TAS", "*TAS0000").bit(0)


def test_known_error_token_detected():
    resp = r("XYZZY", "*UNDEFINED_COMMAND")
    assert resp.is_error
    assert resp.error_code == "UNDEFINED_COMMAND"


def test_unknown_but_error_shaped_token_detected():
    assert r("D", "*SOME_NEW_FAULT").is_error


def test_value_reply_is_not_an_error():
    assert not r("TREV", "*TREV 92-016966-01-5").is_error
    assert not r("TPE", "*TPE+0").is_error
    assert not r("TAS", "*TAS0000_0000").is_error


def test_extra_error_tokens_are_honoured():
    resp = Response("D", ["*WEIRD"], error_tokens=frozenset({"WEIRD"}))
    assert resp.is_error


def test_looks_like_error_requires_star():
    assert not looks_like_error("UNDEFINED_COMMAND")


def test_text_joins_lines():
    assert r("TSTAT", "*A", "*B").text == "*A\n*B"
