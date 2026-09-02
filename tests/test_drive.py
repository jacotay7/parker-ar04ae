"""Drive-level behaviour, driven by the in-memory FakePort.

Reply values are the ones captured from an AR-04AE running Aries OS 3.30.
"""

import pytest

from parker_ar04ae import AriesDrive, CommandError, UnsafeOperationError
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
    assert drive.reset(wait=False, force=True) is None
    assert port.written[-1] == "RESET"


def test_reset_raises_if_the_drive_never_reboots(drive):
    with pytest.raises(VerificationError) as exc:
        drive.reset(timeout=0.4, force=True)
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


def test_tani_is_already_zero_point_adjusted(port):
    # TANI reports the voltage after DCMDZ is applied, so once the input has
    # been zeroed the reading itself falls inside the deadband.
    port.replies["TANI"] = "0.001"
    d = AriesDrive(byte_port=port, timeout=0.3).connect()
    assert d.will_move_on_enable()[0] is False


def test_will_move_on_enable_never_sends_dcmdz(drive, port):
    # Sending DCMDZ bare would re-zero the input - it must not be read.
    drive.will_move_on_enable()
    assert "DCMDZ" not in port.written


def test_will_move_on_enable_estimates_the_commanded_velocity(drive):
    # DMODE4, TANI 0.940 V, deadband 0.040 V, DMVSCL 100.0
    _, why = drive.will_move_on_enable()
    assert "rev/s" in why and "DMVSCL" in why


# -- action commands must not be read --------------------------------------
def test_guard_refuses_an_action_command(drive):
    with pytest.raises(ValueError) as exc:
        drive._guard_action("DCMDZ")
    assert "read-back" in str(exc.value)


def test_guard_allows_ordinary_parameters(drive):
    drive._guard_action("SGP")  # no raise


def test_snapshot_skips_action_commands(drive, port):
    drive.snapshot()
    for cmd in ("DCMDZ", "RESET", "RFS", "ESTORE", "ALIGN", "CERRLG"):
        assert cmd not in port.written


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


# -- noise tolerance -------------------------------------------------------
def test_corrupted_reply_is_detected():
    from parker_ar04ae.response import Response

    assert Response("TVELA", ["0.0�2"]).corrupted
    assert not Response("TVELA", ["0.082"]).corrupted


def test_reads_are_retried_after_corruption(port):
    calls = {"n": 0}

    def flaky(_cmd):
        calls["n"] += 1
        return "0.0�2" if calls["n"] == 1 else "0.082"

    port.replies["TVELA"] = flaky
    d = AriesDrive(byte_port=port, timeout=0.3).connect()
    assert d.actual_velocity() == pytest.approx(0.082)
    assert calls["n"] == 2


def test_reads_are_retried_when_silent(port):
    calls = {"n": 0}

    def flaky(_cmd):
        calls["n"] += 1
        return "" if calls["n"] == 1 else "163.1"

    port.replies["TVBUS"] = flaky
    port.echo = False
    d = AriesDrive(byte_port=port, timeout=0.2).connect()
    assert d.bus_voltage() == pytest.approx(163.1)


def test_retries_give_up_and_return_the_last_reply(port):
    port.replies["TVELA"] = "0.0�2"
    d = AriesDrive(byte_port=port, timeout=0.2, retries=2).connect()
    resp = d.raw("TVELA", strict=False)
    assert resp.corrupted
    assert port.written.count("TVELA") == 3  # 1 attempt + 2 retries


def test_writes_are_never_retried(port):
    # Re-sending a write could apply it twice.
    d = AriesDrive(byte_port=port, timeout=0.2, retries=2).connect()
    d.raw("SGI", 0.1)
    assert port.written.count("SGI0.1") == 1


def test_an_error_reply_is_not_retried(port):
    d = AriesDrive(byte_port=port, timeout=0.2, retries=2).connect()
    d.raw("NOSUCHCMD", strict=False)
    assert port.written.count("NOSUCHCMD") == 1


def test_retries_can_be_disabled_per_call(port):
    port.replies["TVELA"] = "0.0�2"
    d = AriesDrive(byte_port=port, timeout=0.2).connect()
    d.raw("TVELA", strict=False, retries=0)
    assert port.written.count("TVELA") == 1


# -- velocity ---------------------------------------------------------------
def test_commanded_velocity_applies_the_manual_formula(drive):
    # TANI 0.940, ANICDB 0.040, DMVSCL 100.0 -> (0.940-0.040)*100/10
    assert drive.commanded_velocity() == pytest.approx(9.0)


def test_commanded_velocity_is_zero_inside_the_deadband(port):
    port.replies["TANI"] = "0.020"
    d = AriesDrive(byte_port=port, timeout=0.3).connect()
    assert d.commanded_velocity() == 0.0


def test_commanded_velocity_follows_the_sign_of_the_input(port):
    port.replies["TANI"] = "-0.940"
    d = AriesDrive(byte_port=port, timeout=0.3).connect()
    assert d.commanded_velocity() == pytest.approx(-9.0)


def _ramping_port(counts_per_second, eres="944000", jitter=None):
    """A fake whose TPE advances at a fixed rate in real time."""
    import time

    start = time.monotonic()
    state = {"n": 0}

    def tpe(_cmd):
        state["n"] += 1
        if jitter and state["n"] in jitter:
            return jitter[state["n"]]
        return str(int((time.monotonic() - start) * counts_per_second))

    return FakePort({**ALL_REPLIES, "TPE": tpe, "ERES": eres})


def test_measure_velocity_recovers_the_rate():
    d = AriesDrive(byte_port=_ramping_port(94400), timeout=0.3).connect()
    m = d.measure_velocity(duration=1.2, interval=0.05)
    assert m.rev_per_s == pytest.approx(0.1, rel=0.05)
    assert m.rpm == pytest.approx(6.0, rel=0.05)
    assert m.r_squared > 0.99
    assert m.samples >= 3


def test_measure_velocity_discards_corrupted_samples():
    # Sample 5 comes back mangled; the fit should not be dragged by it.
    port = _ramping_port(94400, jitter={5: "99999�9"})
    d = AriesDrive(byte_port=port, timeout=0.3).connect()
    m = d.measure_velocity(duration=1.2, interval=0.05)
    assert m.rev_per_s == pytest.approx(0.1, rel=0.05)


def test_measure_velocity_discards_backward_jumps():
    # An undetectable corruption that stays valid ASCII, but goes backwards.
    port = _ramping_port(94400, jitter={6: "12"})
    d = AriesDrive(byte_port=port, timeout=0.3).connect()
    m = d.measure_velocity(duration=1.2, interval=0.05)
    assert m.rev_per_s == pytest.approx(0.1, rel=0.05)


def test_measure_velocity_uses_an_explicit_eres():
    d = AriesDrive(byte_port=_ramping_port(94400), timeout=0.3).connect()
    m = d.measure_velocity(duration=1.0, interval=0.05, eres=9440)
    assert m.rev_per_s == pytest.approx(10.0, rel=0.05)


def test_measure_velocity_raises_without_enough_samples(port):
    port.replies["TPE"] = "���"
    d = AriesDrive(byte_port=port, timeout=0.2, retries=0).connect()
    with pytest.raises(ValueError) as exc:
        d.measure_velocity(duration=0.4, interval=0.1)
    assert "usable position samples" in str(exc.value)


def test_velocity_measurement_str():
    from parker_ar04ae import VelocityMeasurement

    m = VelocityMeasurement(rev_per_s=0.0168, r_squared=0.999, samples=53, duration=32.0)
    assert "1.0080 RPM" in str(m)


# -- position reference ----------------------------------------------------
def test_establish_position_defaults_to_zero(drive, port):
    drive.establish_position()
    assert port.written[-1] == "PSET0"


def test_establish_position_accepts_a_value(drive, port):
    drive.establish_position(-1500)
    assert port.written[-1] == "PSET-1500"


def test_establish_position_is_not_retried(port):
    # It is a write: re-sending would reapply the offset.
    d = AriesDrive(byte_port=port, timeout=0.2, retries=2).connect()
    d.establish_position(0)
    assert port.written.count("PSET0") == 1


def test_pset_cannot_be_read_back(drive):
    # PSET is an action; reading it bare would be a write with no argument.
    with pytest.raises(ValueError):
        drive._guard_action("PSET")


# -- reset safety guard ----------------------------------------------------
def test_reset_refuses_when_it_would_start_the_motor(drive, port):
    # ERROR reports no E46, so the interlock is closed and the drive will
    # energise itself on power-up - into a standing analog command.
    with pytest.raises(UnsafeOperationError) as exc:
        drive.reset()
    assert "would start" in str(exc.value)
    assert "RESET" not in port.written


def test_reset_is_allowed_when_the_interlock_is_open(port):
    port.replies["ERROR"] = "E46-Hardware Enable"
    d = AriesDrive(byte_port=port, timeout=0.2).connect()
    with pytest.raises(VerificationError):        # never reboots in the fake
        d.reset(timeout=0.3)
    assert "RESET" in port.written                # but it did send it


def test_reset_is_allowed_when_the_command_scales_to_zero(port):
    port.replies["DMVSCL"] = "0.000"
    d = AriesDrive(byte_port=port, timeout=0.2).connect()
    with pytest.raises(VerificationError):
        d.reset(timeout=0.3)
    assert "RESET" in port.written


def test_reset_force_overrides_the_guard(drive, port):
    drive.reset(wait=False, force=True)
    assert port.written[-1] == "RESET"


def test_hardware_enable_closed_reflects_e46(port):
    d = AriesDrive(byte_port=port, timeout=0.2).connect()
    assert d.hardware_enable_closed() is True
    port.replies["ERROR"] = "E46-Hardware Enable"
    assert d.hardware_enable_closed() is False


# -- will_move_on_enable and the velocity scale ----------------------------
def test_zero_velocity_scale_means_no_motion(port):
    port.replies["DMVSCL"] = "0.000"
    d = AriesDrive(byte_port=port, timeout=0.2).connect()
    will_move, why = d.will_move_on_enable()
    assert will_move is False
    assert "scales it to zero" in why


def test_unreadable_scale_is_treated_as_unsafe(port):
    del port.replies["DMVSCL"]
    d = AriesDrive(byte_port=port, timeout=0.2).connect()
    will_move, why = d.will_move_on_enable()
    assert will_move is True
    assert "could not be read" in why


# -- undetectable numeric corruption ---------------------------------------
def test_read_median_rejects_plausible_outliers(port):
    # A flipped digit still parses: 0.001 read as 4.001 or 0.901.
    seq = iter(["0.001", "4.001", "0.001", "0.901", "0.001"])
    port.replies["TANI"] = lambda _c: next(seq)
    d = AriesDrive(byte_port=port, timeout=0.3).connect()
    assert d.read_median("TANI", samples=5) == pytest.approx(0.001)


def test_read_median_survives_some_unparsable_reads(port):
    seq = iter(["UANI", "0.002", "0.002", "xxx", "0.002"])
    port.replies["TANI"] = lambda _c: next(seq)
    d = AriesDrive(byte_port=port, timeout=0.2, retries=0).connect()
    assert d.read_median("TANI", samples=5) == pytest.approx(0.002)


def test_read_median_raises_when_nothing_parses(port):
    port.replies["TANI"] = "garbage"
    d = AriesDrive(byte_port=port, timeout=0.2, retries=0).connect()
    with pytest.raises(ValueError) as exc:
        d.read_median("TANI", samples=3)
    assert "no parsable value" in str(exc.value)


def test_safety_check_is_not_fooled_by_one_bad_sample(port):
    # Four honest ~0 V reads and one corrupted 4.0 V: must still read safe.
    seq = iter(["0.001", "0.001", "4.001", "0.001", "0.001"])
    port.replies["TANI"] = lambda _c: next(seq)
    d = AriesDrive(byte_port=port, timeout=0.3).connect()
    assert d.will_move_on_enable()[0] is False


def test_safety_check_is_not_fooled_into_calling_it_safe(port):
    # The dangerous direction: a standing command with one clean-looking zero.
    seq = iter(["0.920", "0.920", "0.001", "0.920", "0.920"])
    port.replies["TANI"] = lambda _c: next(seq)
    d = AriesDrive(byte_port=port, timeout=0.3).connect()
    assert d.will_move_on_enable()[0] is True


def test_typed_read_retries_a_bit_flipped_command_echo(port):
    seq = iter(["UANI", "0.123"])
    port.replies["TANI"] = lambda _c: next(seq)
    d = AriesDrive(byte_port=port, timeout=0.3).connect()
    assert d.analog_input() == pytest.approx(0.123)
