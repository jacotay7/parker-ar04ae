"""Drive-level behaviour, driven by the in-memory FakePort.

Reply values are the ones captured from an AR-04AE running Aries OS 3.30.
"""

import pytest

from parker_ar04ae import AriesDrive, CommandError
from parker_ar04ae.drive import PARAMETER_COMMANDS, PARAMETERS
from parker_ar04ae.errors import ConnectionError_, TimeoutError_
from parker_ar04ae.testing import DEMO_REPLIES, FakePort, demo_drive


@pytest.fixture
def port():
    return FakePort(DEMO_REPLIES)


@pytest.fixture
def drive(port):
    return AriesDrive(byte_port=port, timeout=0.3).connect()


# -- plumbing --------------------------------------------------------------
def test_requires_a_port_or_transport():
    with pytest.raises(ValueError):
        AriesDrive()


def test_commands_before_connect_raise():
    with pytest.raises(ConnectionError_):
        AriesDrive(byte_port=FakePort(DEMO_REPLIES)).revision()


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
def test_enable_and_disable_send_the_right_commands(drive, port):
    port.replies["DRIVE1"] = ""
    port.replies["DRIVE0"] = ""
    drive.enable()
    assert port.written[-1] == "DRIVE1"
    drive.disable()
    assert port.written[-1] == "DRIVE0"


def test_reset_does_not_wait_for_a_reply(drive, port):
    drive.reset()
    assert port.written[-1] == "RESET"


# -- parameter registry ----------------------------------------------------
def test_get_reads_by_friendly_name(drive):
    assert drive.get("bus_voltage").as_float() == pytest.approx(163.1)
    assert drive.get("gain_p").value == "2.000"


def test_set_writes_by_friendly_name(drive, port):
    port.replies["SGP3.5"] = ""
    drive.set("gain_p", 3.5)
    assert port.written[-1] == "SGP3.5"


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
