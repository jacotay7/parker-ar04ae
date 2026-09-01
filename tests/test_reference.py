"""The manual's lookup tables, and the decoding built on them."""

import pytest

from parker_ar04ae.reference import (
    ANALOG_COMMAND_MODES,
    DRIVE_MODES,
    ERROR_CODES,
    ERROR_LOG_BITS,
    FEEDBACK_TYPES,
    MAX_COMMAND_LENGTH,
    describe_drive_mode,
    describe_error,
)


def test_dmode_4_is_velocity_control():
    # The mode the AR-04AE under test reports.
    assert DRIVE_MODES[4][0] == "Velocity Control"
    assert describe_drive_mode(4) == "Velocity Control"


def test_analog_command_modes_are_torque_and_velocity():
    # Modes where the drive acts on the analog input the moment it energises.
    assert set(ANALOG_COMMAND_MODES) == {2, 4}


def test_step_and_direction_modes_are_not_analog():
    assert 6 not in ANALOG_COMMAND_MODES
    assert 7 not in ANALOG_COMMAND_MODES


def test_e46_is_the_hardware_enable_error():
    assert "hardware enable" in describe_error("E46").lower()
    assert "1 and 21" in describe_error("E46")


def test_describe_error_is_case_insensitive():
    assert describe_error("e46") == describe_error("E46")


def test_unknown_error_code_is_reported_as_such():
    assert describe_error("E99") == "unrecognised error code"


def test_error_table_covers_the_documented_range():
    # Rev G Table 46 runs E25 to E52, with E33 absent.
    assert "E25" in ERROR_CODES and "E52" in ERROR_CODES
    assert "E33" not in ERROR_CODES


def test_error_log_bits_are_zero_based():
    assert ERROR_LOG_BITS[0].startswith("enable/disable")
    assert ERROR_LOG_BITS[12] == "regeneration fault"


def test_feedback_types_include_smart_encoder():
    assert "smart encoder" in FEEDBACK_TYPES[5]


def test_command_length_limit():
    assert MAX_COMMAND_LENGTH == 32
