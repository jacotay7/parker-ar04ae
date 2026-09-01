"""Drive-level behaviour, driven by the in-memory FakePort.

Reply values are the ones captured from an AR-04AE running Aries OS 3.30.
"""

import pytest

from parker_ar04ae import AriesDrive, CommandError
from parker_ar04ae.drive import PARAMETER_COMMANDS, PARAMETERS
from parker_ar04ae.errors import (
    ConnectionError_,
    TimeoutError_,
    VerificationError,
)
from parker_ar04ae.testing import ALL_REPLIES, DEMO_REPLIES, FakePort, demo_drive


@pytest.fixture
def port():
    return FakePort(ALL_REPLIES)


@pytest.fixture
def drive(port):
    return AriesDrive(byte_port=port, timeout=0.3).connect()


# -- plumbing --------------------------------------------------------------
def test_requires_a_port_or_transport():
    with pytest.raises(ValueError):
        AriesDrive()


def test_commands_before_connect_raise():
    with pytest.raises(ConnectionError_):
        AriesDrive(byte_port=FakePort(ALL_REPLIES)).revision()


def test_context_manager_connects_and_closes(port):
    with AriesDrive(byte_port=port) as d:
        assert d.is_connected
    assert not d.is_connected


def test_arguments_are_concatenated_onto_the_command(drive, port):
    drive.raw("SGP", 2.0, strict=False)
    assert port.written[-1] == "SGP2.0"


def test_bare_command_reads(drive, port):
    drive.raw("SGP", strict=False)
    assert port.written[-1] == "SGP"


def test_address_prefixes_the_command(port):
    AriesDrive(byte_port=port, address=2).connect().raw("TREV", strict=False)
    assert port.written[-1] == "2_TREV"


def test_no_prefix_without_an_address(drive, port):
    drive.raw("TREV", strict=False)
    assert port.written[-1] == "TREV"


# -- errors ----------------------------------------------------------------
def test_strict_mode_raises_on_drive_error(drive):
    with pytest.raises(CommandError) as exc:
        drive.raw("TASX")
    assert exc.value.message == "Unknown Command"
    assert exc.value.command == "TASX"


def test_non_strict_mode_returns_the_error(drive):
    resp = drive.raw("TASX", strict=False)
    assert resp.is_error and resp.error_message == "Unknown Command"


def test_strict_can_be_disabled_for_the_whole_drive(port):
    d = AriesDrive(byte_port=port, strict=False).connect()
    assert d.raw("TASX").is_error


def test_query_raises_when_the_drive_stays_silent(port):
    silent = FakePort({}, echo=False, enq=False, default="")
    d = AriesDrive(byte_port=silent, timeout=0.05).connect()
    with pytest.raises(TimeoutError_):
        d.query("TPE")


def test_ping_is_true_when_the_drive_answers(drive):
    assert drive.ping() is True


def test_ping_is_true_even_when_the_reply_is_an_error(port):
    port.replies.clear()  # everything now answers ERROR: Unknown Command
    assert AriesDrive(byte_port=port, timeout=0.3).connect().ping() is True


def test_ping_is_false_on_a_dead_link():
    dead = FakePort({}, echo=False, enq=False, default="")
    assert AriesDrive(byte_port=dead, timeout=0.05).connect().ping() is False


def test_ping_is_false_when_not_connected():
    assert AriesDrive(byte_port=FakePort()).ping() is False


# -- telemetry -------------------------------------------------------------
def test_revision(drive):
    assert drive.revision() == "Aries OS Revision 3.30"


def test_motor(drive):
    assert drive.motor() == "OTHER=R200D"


def test_position_is_an_int(drive):
    assert drive.position() == 0


def test_velocity_and_torque_are_floats(drive):
    assert drive.actual_velocity() == pytest.approx(0.0)
    assert drive.torque() == pytest.approx(0.0)


def test_bus_voltage(drive):
    assert drive.bus_voltage() == pytest.approx(163.1)


def test_temperatures(drive):
    assert drive.drive_temperature() == pytest.approx(30.43)
    assert drive.motor_temperature() == pytest.approx(25.0)


def test_analog_input(drive):
    assert drive.analog_input() == pytest.approx(0.94)


def test_is_enabled_reads_drive(drive):
    assert drive.is_enabled() is False


def test_axis_status_bits(drive):
    assert drive.axis_status().set_bits() == []


def test_output_states_bits(drive):
    assert drive.output_states().set_bits() == [15, 16]


# -- commands --------------------------------------------------------------
# -- parameter registry ----------------------------------------------------
def test_get_reads_by_friendly_name(drive):
    assert drive.get("bus_voltage").as_float() == pytest.approx(163.1)
    assert drive.get("gain_p").value == "2.000"


def test_unknown_parameter_name_raises_with_a_hint(drive):
    with pytest.raises(KeyError) as exc:
        drive.get("nonesuch")
    assert "gain_p" in str(exc.value)


def test_snapshot_covers_every_group(drive):
    snap = drive.snapshot()
    assert set(snap) == set(PARAMETERS)
    assert snap["identity"]["revision"] == "Aries OS Revision 3.30"
    assert snap["motor_config"]["poles"] == "16"


def test_snapshot_can_be_limited_to_one_group(drive):
    assert set(drive.snapshot(groups=["power"])) == {"power"}


def test_snapshot_reports_unsupported_parameters_as_none(drive, port):
    del port.replies["TVBUS"]  # now answers ERROR: Unknown Command
    assert drive.snapshot(groups=["power"])["power"]["bus_voltage"] is None


def test_snapshot_never_raises_on_a_dead_parameter(port):
    port.replies.clear()
    snap = AriesDrive(byte_port=port, timeout=0.3).connect().snapshot()
    assert all(v is None for g in snap.values() for v in g.values())


def test_every_registered_parameter_has_a_command():
    assert len(PARAMETER_COMMANDS) == sum(len(g) for g in PARAMETERS.values())


def test_demo_drive_helper_is_connected():
    d = demo_drive()
    assert d.is_connected
    assert d.revision().startswith("Aries OS")


# -- writes ----------------------------------------------------------------
def test_bare_command_expects_a_reply_and_an_argument_does_not(drive, port):
    # A write that waited for ENQ would block for the whole timeout.
    import time

    drive.transport.timeout = 5.0
    start = time.monotonic()
    drive.raw("SGI", 0.1)
    assert time.monotonic() - start < 1.0


def test_set_reads_the_value_back(drive, port):
    assert drive.set("gain_i", 0.1).value == "0.1"
    assert port.written[-2:] == ["SGI0.1", "SGI"]


def test_set_accepts_the_drives_normalised_value(port):
    # The drive stores 0.1 as '0.100'; comparison must be numeric, not textual.
    port.replies["SGI"] = "0.000"
    d = AriesDrive(byte_port=port, timeout=0.3).connect()
    port.emulate_writes = False
    port.replies["SGI0.1"] = None
    port.replies["SGI"] = "0.100"
    assert d.set("gain_i", 0.1).value == "0.100"


def test_set_raises_when_the_write_is_ignored(port):
    refusing = FakePort(ALL_REPLIES, refuse={"SGI"})
    d = AriesDrive(byte_port=refusing, timeout=0.3).connect()
    with pytest.raises(VerificationError) as exc:
        d.set("gain_i", 0.1)
    assert exc.value.expected == 0.1


def test_set_can_skip_verification(port):
    refusing = FakePort(ALL_REPLIES, refuse={"SGI"})
    d = AriesDrive(byte_port=refusing, timeout=0.3).connect()
    d.set("gain_i", 0.1, verify=False)  # no raise
    assert refusing.written[-1] == "SGI0.1"


def test_values_match_compares_numerically():
    assert AriesDrive._values_match(0.1, "0.100")
    assert AriesDrive._values_match("2", "2.000")
    assert not AriesDrive._values_match(0.1, "0.200")


def test_values_match_falls_back_to_text():
    assert AriesDrive._values_match("BE231FJ", "be231fj")
    assert not AriesDrive._values_match("BE231FJ", "R200D")


# -- enable / disable ------------------------------------------------------
def test_enable_verifies_the_drive_came_up(drive, port):
    assert drive.enable() is True
    assert port.written[-2] == "DRIVE1"


def test_enable_raises_when_the_drive_refuses(port):
    # What the real AR-04AE does: DRIVE1 echoes, and DRIVE still reads 0.
    refusing = FakePort({**ALL_REPLIES, "ERROR": "E46-Hardware Enable"},
                        refuse={"DRIVE"})
    d = AriesDrive(byte_port=refusing, timeout=0.3).connect()
    with pytest.raises(VerificationError) as exc:
        d.enable()
    # The reason comes from the drive's own ERROR report, not a guess.
    assert "E46" in str(exc.value)
    assert "hardware enable input" in str(exc.value)


def test_enable_can_skip_verification(port):
    refusing = FakePort(ALL_REPLIES, refuse={"DRIVE"})
    d = AriesDrive(byte_port=refusing, timeout=0.3).connect()
    assert d.enable(verify=False) is True


def test_disable_verifies(drive, port):
    drive.enable()
    assert drive.disable() is False
    assert port.written[-2] == "DRIVE0"


def test_reset_without_waiting_just_sends_it(drive, port):
    assert drive.reset(wait=False) is None
    assert port.written[-1] == "RESET"


def test_reset_raises_if_the_drive_never_reboots(drive):
    with pytest.raises(VerificationError) as exc:
        drive.reset(timeout=0.4)
    assert "never stopped answering" in str(exc.value)


# -- text reports and decoding ---------------------------------------------
def test_active_errors_is_empty_when_the_drive_says_no_errors(drive):
    assert drive.active_errors() == []


def test_active_errors_decodes_codes(port):
    port.replies["ERROR"] = ["E46-Hardware Enable", "E39-Drive Disabled"]
    d = AriesDrive(byte_port=port, timeout=0.3).connect()
    codes = dict(d.active_errors())
    assert set(codes) == {"E46", "E39"}
    assert "hardware enable" in codes["E46"].lower()


def test_active_errors_keeps_an_unrecognised_code(port):
    port.replies["ERROR"] = ["E99-Something New"]
    d = AriesDrive(byte_port=port, timeout=0.3).connect()
    assert d.active_errors() == [("E99", "Something New")]


def test_status_report_uses_STATUS_not_TSTAT(drive, port):
    lines = drive.status()
    assert any("OS Revision" in ln for ln in lines)
    assert port.written[-1] == "STATUS"


def test_error_log_reads_terrlg(drive, port):
    assert any("Operating hours" in ln for ln in drive.error_log())
    assert port.written[-1] == "TERRLG"


def test_clear_error_log(drive, port):
    drive.clear_error_log()
    assert port.written[-1] == "CERRLG"


def test_drive_mode_is_decoded(drive):
    assert drive.drive_mode() == 4
    assert drive.drive_mode_name() == "Velocity Control"


def test_feedback_type_is_decoded(drive):
    assert "smart encoder" in drive.feedback_type()


# -- analog command input --------------------------------------------------
def test_zero_command_offset_bare(drive, port):
    drive.zero_command_offset()
    assert port.written[-1] == "DCMDZ"


def test_zero_command_offset_uses_equals_syntax(drive, port):
    drive.zero_command_offset(0.5)
    assert port.written[-1] == "DCMDZ=0.5"


def test_will_move_on_enable_is_true_for_a_standing_command(drive):
    # DMODE4, TANI 0.940 V, zero 0.000 V, deadband 0.040 V.
    will_move, why = drive.will_move_on_enable()
    assert will_move is True
    assert "0.940" in why and "will move on enable" in why


def test_will_move_on_enable_is_false_inside_the_deadband(port):
    port.replies["TANI"] = "0.020"
    d = AriesDrive(byte_port=port, timeout=0.3).connect()
    will_move, why = d.will_move_on_enable()
    assert will_move is False
    assert "deadband" in why


def test_will_move_on_enable_accounts_for_the_zero_point(port):
    port.replies["DCMDZ"] = "0.930"  # zeroed against the standing command
    d = AriesDrive(byte_port=port, timeout=0.3).connect()
    assert d.will_move_on_enable()[0] is False


def test_will_move_on_enable_is_false_in_step_and_direction_mode(port):
    port.replies["DMODE"] = "6"
    d = AriesDrive(byte_port=port, timeout=0.3).connect()
    will_move, why = d.will_move_on_enable()
    assert will_move is False
    assert "does not follow the analog input" in why


def test_will_move_on_enable_falls_back_when_commands_are_missing(port):
    del port.replies["ANICDB"]
    del port.replies["DCMDZ"]
    d = AriesDrive(byte_port=port, timeout=0.3).connect()
    assert d.will_move_on_enable()[0] is True  # 0.940 V still outside default 0.04


# -- command line limit ----------------------------------------------------
def test_overlong_command_is_rejected(drive):
    with pytest.raises(ValueError) as exc:
        drive.raw("D" * 40)
    assert "32" in str(exc.value)


def test_command_at_the_limit_is_allowed(drive):
    drive.raw("D" * 32, strict=False)  # no raise
