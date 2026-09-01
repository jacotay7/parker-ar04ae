"""Drive-level behaviour, driven entirely by the in-memory FakePort."""

import pytest

from parker_ar04ae import AriesDrive, CommandError
from parker_ar04ae.errors import ConnectionError_, TimeoutError_
from parker_ar04ae.testing import DEMO_REPLIES, FakePort, demo_drive


@pytest.fixture
def port():
    return FakePort(DEMO_REPLIES)


@pytest.fixture
def drive(port):
    d = AriesDrive(byte_port=port, timeout=0.3)
    d.transport.quiet_time = 0.02
    return d.connect()


# -- plumbing --------------------------------------------------------------
def test_requires_a_port_or_transport():
    with pytest.raises(ValueError):
        AriesDrive()


def test_commands_before_connect_raise():
    d = AriesDrive(byte_port=FakePort(DEMO_REPLIES))
    with pytest.raises(ConnectionError_):
        d.revision()


def test_context_manager_connects_and_closes(port):
    with AriesDrive(byte_port=port) as d:
        assert d.is_connected
    assert not d.is_connected


def test_arguments_are_concatenated_onto_the_command(drive, port):
    drive.raw("DMTR", "BE231FJ", strict=False)
    assert port.written[-1] == "DMTRBE231FJ"


def test_numeric_arguments(drive, port):
    drive.raw("ERES", 4000, strict=False)
    assert port.written[-1] == "ERES4000"


def test_address_prefixes_the_command(port):
    d = AriesDrive(byte_port=port, address=2)
    d.transport.quiet_time = 0.02
    d.connect().raw("TREV", strict=False)
    assert port.written[-1] == "2_TREV"


def test_no_prefix_without_an_address(drive, port):
    drive.raw("TREV", strict=False)
    assert port.written[-1] == "TREV"


# -- errors ----------------------------------------------------------------
def test_strict_mode_raises_on_drive_error(drive):
    with pytest.raises(CommandError) as exc:
        drive.raw("NOSUCHCOMMAND")
    assert exc.value.code == "UNDEFINED_COMMAND"
    assert exc.value.command == "NOSUCHCOMMAND"


def test_non_strict_mode_returns_the_error(drive):
    resp = drive.raw("NOSUCHCOMMAND", strict=False)
    assert resp.is_error and resp.error_code == "UNDEFINED_COMMAND"


def test_strict_can_be_disabled_for_the_whole_drive(port):
    d = AriesDrive(byte_port=port, strict=False)
    d.transport.quiet_time = 0.02
    assert d.connect().raw("NOSUCHCOMMAND").is_error


def test_query_raises_when_the_drive_stays_silent(drive, port):
    port.replies["QUIET"] = ""
    port.echo = False
    with pytest.raises(TimeoutError_):
        drive.query("QUIET")


def test_ping_is_true_when_the_drive_answers(drive):
    assert drive.ping() is True


def test_ping_is_false_when_it_does_not():
    silent = FakePort({}, echo=False, default="")
    d = AriesDrive(byte_port=silent, timeout=0.05)
    d.transport.quiet_time = 0.02
    assert d.connect().ping() is False


def test_ping_is_true_even_when_the_reply_is_an_error(port):
    port.replies.clear()  # every command now answers *UNDEFINED_COMMAND
    d = AriesDrive(byte_port=port, timeout=0.3)
    d.transport.quiet_time = 0.02
    assert d.connect().ping() is True


def test_ping_is_false_when_not_connected():
    assert AriesDrive(byte_port=FakePort()).ping() is False


# -- queries ---------------------------------------------------------------
def test_revision(drive):
    assert drive.revision() == "92-016966-01-5_D1.0 ARIES"


def test_position_is_an_int(drive):
    assert drive.position() == 0


def test_velocity_is_a_float(drive):
    assert drive.velocity() == pytest.approx(0.0)


def test_temperature(drive):
    assert drive.drive_temperature() == pytest.approx(32.0)


def test_is_enabled_reads_drive(drive):
    assert drive.is_enabled() is False


def test_status_report_returns_every_line(drive):
    lines = drive.status_report(timeout=0.5)
    assert len(lines) == 5
    assert lines[0].startswith("*ARIES")


def test_axis_status_bits(drive):
    assert drive.axis_status().as_bits() == "0" * 32


def test_drive_fault_is_false_when_ter_is_clear(drive):
    assert drive.drive_fault() is False


def test_drive_fault_is_true_when_a_bit_is_set(drive, port):
    port.replies["TER"] = "*TER0000_0010_0000_0000"
    assert drive.drive_fault() is True


# -- commands --------------------------------------------------------------
def test_enable_and_disable_send_the_right_commands(drive, port):
    drive.enable()
    assert port.written[-1] == "DRIVE1"
    drive.disable()
    assert port.written[-1] == "DRIVE0"


def test_reset_does_not_wait_for_a_reply(drive, port):
    drive.reset()
    assert port.written[-1] == "RESET"


def test_motor_reads_when_called_bare(drive, port):
    assert drive.motor().value == "BE231FJ"
    assert port.written[-1] == "DMTR"


def test_motor_writes_when_given_a_part_number(drive, port):
    port.replies["DMTRBE231FJ"] = ""
    drive.motor("BE231FJ")
    assert port.written[-1] == "DMTRBE231FJ"


def test_set_echo_tracks_state_on_the_transport(drive, port):
    port.replies["ECHO0"] = ""
    drive.set_echo(False)
    assert port.written[-1] == "ECHO0"
    assert drive.transport.echo is False


def test_demo_drive_helper_is_connected():
    d = demo_drive()
    assert d.is_connected
    assert d.revision().startswith("92-")
