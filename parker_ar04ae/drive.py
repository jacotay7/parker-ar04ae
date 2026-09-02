"""High-level interface to a Parker ARIES AR-04AE servo drive.

Wiring on a Mac is USB-C -> USB-A -> USB/RS-232 adapter -> the drive's RS-232
port. See the README for the driver a Prolific PL2303 adapter needs.

    from parker_ar04ae import AriesDrive

    with AriesDrive("/dev/cu.PL2303G-USBtoUART10") as drive:
        print(drive.revision())          # 'Aries OS Revision 3.30'
        print(drive.bus_voltage())       # 163.1
        print(drive.axis_status().set_bits())

Every command wrapped here was verified against an AR-04AE running Aries OS
3.30; :data:`PARAMETERS` records the set. Anything else can be sent with
:meth:`raw`, so the class never gets in the way of a command it does not know.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Optional, Union

from .errors import (
    AriesError,
    CommandError,
    ConnectionError_,
    TimeoutError_,
    VerificationError,
)
from .protocol import DEFAULT_BAUD, ERROR_PREFIX
from .reference import (
    ACTION_COMMANDS,
    ANALOG_COMMAND_MODES,
    DRIVE_MODES,
    ERROR_CODES,
    FEEDBACK_TYPES,
    MAX_COMMAND_LENGTH,
    describe_error,
)
from .response import Response
from .transport import BytePort, SerialPort, SerialTransport

log = logging.getLogger(__name__)

Number = Union[int, float]

#: Baud rates to sweep when probing. 9600 is the factory default.
BAUD_RATES = (9600, 19200, 38400, 57600, 115200)

#: Per-poll timeout while waiting for a reset to complete. Short, because the
#: drive is expected to be unreachable for part of it.
RESET_POLL = 0.35

#: Settle time after a reset before flushing. The poll that detects recovery can
#: return a partial reply, leaving the rest of it in flight; flushing before
#: that lands leaves the stream misaligned, and the next read picks up the tail
#: of the old one.
RESET_SETTLE = 0.5

#: Readable parameters, grouped as the manual groups them:
#: ``name -> (command, description, source)``. Sending the bare command reads
#: the value; appending a value writes it. Used by :meth:`AriesDrive.snapshot`.
#:
#: ``source`` is ``"hw"`` for commands confirmed against an AR-04AE running
#: Aries OS 3.30, and ``"doc"`` for ones taken from the Rev G manual but not yet
#: seen on hardware. All 84 below currently read back on OS 3.30; the tag is
#: kept so anything added later from the manual alone is marked as such.
#: :meth:`snapshot` reports a parameter the firmware rejects as ``None`` rather
#: than failing, so a "doc" entry is never fatal.
PARAMETERS: dict[str, dict[str, tuple[str, str, str]]] = {
    "identity": {
        "revision": ("TREV", "firmware revision", "hw"),
        "motor": ("DMTR", "configured motor", "hw"),
        "address": ("ADDR", "daisy-chain unit address", "hw"),
        "echo": ("ECHO", "serial echo enabled", "hw"),
        "error_level": ("ERRLVL", "error reporting verbosity (undocumented)", "hw"),
    },
    "status": {
        "enabled": ("DRIVE", "drive enabled", "hw"),
        "axis_status": ("TAS", "axis status bits (undocumented)", "hw"),
        "inputs": ("TIN", "digital input states (undocumented)", "hw"),
        "outputs": ("TOUT", "digital output states", "hw"),
    },
    "feedback": {
        "position": ("TPE", "encoder position, counts", "hw"),
        "commanded_position": ("TPC", "commanded position, counts", "hw"),
        "position_error": ("TPER", "following error, counts", "hw"),
        "velocity": ("TVEL", "commanded velocity", "hw"),
        "actual_velocity": ("TVELA", "actual velocity", "hw"),
        "velocity_error": ("TVER", "commanded velocity error", "hw"),
        "torque": ("TTRQ", "commanded torque/force", "hw"),
        "actual_torque": ("TTRQA", "actual torque/force", "hw"),
        "commanded_current": ("TCI", "commanded current", "hw"),
        "analog_input": ("TANI", "analog command input, volts", "hw"),
        "hall": ("THALL", "hall sensor values", "hw"),
    },
    "power": {
        "bus_voltage": ("TVBUS", "DC bus voltage", "hw"),
        "drive_temperature": ("TDTEMP", "drive temperature, degC", "hw"),
        "motor_temperature": ("TMTEMP", "motor temperature, degC", "hw"),
        "continuous_rating": ("TDICNT", "continuous current rating", "hw"),
        "max_rating": ("TDIMAX", "maximum current rating", "hw"),
        "pwm_period": ("TSSPD", "PWM update period", "hw"),
    },
    "runtime": {
        "operating_hours": ("TDHRS", "operating hours", "hw"),
        "operating_minutes": ("TDMIN", "operating minutes", "hw"),
        "operating_ms": ("TDSEC", "operating milliseconds", "hw"),
    },
    "drive_config": {
        "drive_mode": ("DMODE", "control mode, see DRIVE_MODES", "hw"),
        "encoder_resolution": ("ERES", "encoder resolution, counts/rev", "hw"),
        "resolution": ("DRES", "drive resolution, step/dir modes", "hw"),
        "feedback_source": ("SFB", "feedback type, see FEEDBACK_TYPES", "hw"),
        "current_foldback": ("DIFOLD", "current foldback enabled", "hw"),
        "thermal_mode": ("DTHERM", "motor thermal switch checking", "hw"),
        "pwm_frequency": ("DPWM", "PWM frequency setting", "hw"),
        "command_direction": ("CMDDIR", "direction of rotation", "hw"),
        "pulse_scaling": ("DMPSCL", "incoming pulse scaling", "hw"),
        "invert_analog": ("IANI", "invert analog input", "hw"),
        "analog_deadband": ("ANICDB", "analog input centre deadband, volts", "hw"),
        "fault_on_disable": ("FLTDSB", "fault on drive disable", "hw"),
        "fault_startup_voltage": ("FLTSTP", "fault on excessive startup voltage", "hw"),
        "encoder_fault_frequency": ("ENCFLT", "max pre-quadrature encoder frequency", "hw"),
        "encoder_offset": ("ENCOFF", "encoder offset", "hw"),
        "encoder_polarity": ("ENCPOL", "encoder polarity", "hw"),
        "hall_config": ("SHALL", "hall sensor configuration", "hw"),
        "hall_only": ("OHALL", "hall-only commutation", "hw"),
        "hall_direction": ("P163", "hall direction", "hw"),
    },
    "motor_config": {
        "continuous_current": ("DMTIC", "motor continuous current, A", "hw"),
        "current_limit": ("DMTLIM", "torque/force limit, A", "hw"),
        "peak_current": ("DMTIP", "motor peak current, A", "hw"),
        "rated_speed": ("DMTW", "motor rated speed", "hw"),
        "back_emf": ("DMTKE", "motor Ke", "hw"),
        "winding_resistance": ("DMTRES", "winding resistance, ohm", "hw"),
        "winding_inductance": ("DMTIND", "winding inductance, mH", "hw"),
        "inductance_factor": ("DMTINF", "motor inductance factor", "hw"),
        "poles": ("DPOLE", "motor pole pairs", "hw"),
        "inertia": ("DMTJ", "rotor inertia", "hw"),
        "damping": ("DMTD", "damping", "hw"),
        "encoder_pitch": ("DMEPIT", "motor electrical pitch, linear only", "hw"),
        "torque_scaling": ("DMTSCL", "torque/force scaling", "hw"),
        "velocity_scaling": ("DMVSCL", "velocity scaling", "hw"),
        "velocity_limit": ("DMVLIM", "velocity limit", "hw"),
        "ambient_temperature": ("DMTAMB", "motor ambient temperature", "hw"),
        "max_winding_temperature": ("DMTMAX", "max motor winding temperature", "hw"),
        "thermal_resistance": ("DMTRWC", "winding thermal resistance", "hw"),
        "thermal_time_constant": ("DMTTCM", "motor thermal time constant", "hw"),
        "winding_time_constant": ("DMTTCW", "motor winding time constant", "hw"),
        "temperature_switch": ("DMTSWT", "motor temperature switch type", "hw"),
        "current_derating": ("DMTICD", "continuous current derating", "hw"),
    },
    "servo_gains": {
        "gain_p": ("SGP", "servo proportional gain", "hw"),
        "gain_i": ("SGI", "servo integral gain", "hw"),
        "gain_v": ("SGV", "servo velocity gain", "hw"),
        "gain_vf": ("SGVF", "velocity feedforward (undocumented)", "hw"),
        "gain_af": ("SGAF", "acceleration feedforward (undocumented)", "hw"),
        "integral_windup_limit": ("SGILIM", "integral windup limit", "hw"),
        "max_position_error": ("SMPER", "maximum allowable position error", "hw"),
        "max_velocity_error": ("SMVER", "maximum allowable velocity error", "hw"),
        "max_acceleration": ("SMAV", "max acceleration in velocity mode", "hw"),
        "proportional_gain": ("PGAIN", "current loop proportional gain", "hw"),
        "integral_gain": ("IGAIN", "current loop integral gain", "hw"),
        "current_loop_bandwidth": ("DIBW", "current loop bandwidth", "hw"),
        "auto_current_gains": ("IAUTO", "auto-determine current loop gains", "hw"),
        "load_inertia_ratio": ("LJRAT", "load-to-rotor inertia ratio", "hw"),
    },
}

#: Flat ``name -> command`` view of :data:`PARAMETERS`.
PARAMETER_COMMANDS: dict[str, str] = {
    name: entry[0]
    for group in PARAMETERS.values()
    for name, entry in group.items()
}


class AriesDrive:
    """A single ARIES drive on a serial port.

    Parameters
    ----------
    port:
        Device path, e.g. ``/dev/cu.PL2303G-USBtoUART10``. Ignored if
        ``transport`` is given.
    baudrate:
        Serial speed; must match the drive's own setting.
    address:
        Unit address for a daisy chain. When set, commands go out prefixed as
        ``<address>_COMMAND``. Leave as ``None`` for a single drive.
    timeout:
        Seconds to wait for the drive's end-of-response prompt.
    strict:
        Raise :class:`CommandError` when the drive reports an error. Set
        ``False`` to get the error back in the :class:`Response` instead.
    transport:
        Supply a pre-built transport (or a fake one) instead of a port path.
    """

    def __init__(
        self,
        port: Optional[str] = None,
        baudrate: int = DEFAULT_BAUD,
        address: Optional[int] = None,
        timeout: float = 1.0,
        strict: bool = True,
        transport: Optional[SerialTransport] = None,
        byte_port: Optional[BytePort] = None,
        error_prefix: str = ERROR_PREFIX,
    ):
        if transport is None:
            if byte_port is None:
                if port is None:
                    raise ValueError("give either port=, byte_port= or transport=")
                byte_port = SerialPort(port, baudrate=baudrate)
            transport = SerialTransport(byte_port, timeout=timeout)
        self.transport = transport
        self.address = address
        self.strict = strict
        self.error_prefix = error_prefix

    # -- lifecycle ---------------------------------------------------------
    def connect(self) -> "AriesDrive":
        self.transport.open()
        self.transport.flush_input()
        return self

    def close(self) -> None:
        self.transport.close()

    @property
    def is_connected(self) -> bool:
        return self.transport.is_open

    def __enter__(self) -> "AriesDrive":
        return self.connect()

    def __exit__(self, *exc) -> None:
        self.close()

    # -- command plumbing --------------------------------------------------
    def _format(self, command: str, args: tuple) -> str:
        text = command + "".join(str(a) for a in args if a is not None)
        if self.address is not None:
            text = f"{self.address}_{text}"
        return text

    def raw(
        self,
        command: str,
        *args: object,
        timeout: Optional[float] = None,
        strict: Optional[bool] = None,
        expect_reply: Optional[bool] = None,
    ) -> Response:
        """Send ``command`` verbatim and return the parsed :class:`Response`.

        Arguments are concatenated directly onto the command, which is the
        drive's own syntax: ``raw("SGP", 2.0)`` sends ``SGP2.0``. Sending a
        command bare reads the current value.

        ``expect_reply`` defaults to "a bare command is a query, one with
        arguments is a write". Writes send no ENQ, so waiting for one would
        block for the full timeout. Pass it explicitly for writes that carry
        their value in the command name, such as ``DRIVE1``.
        """
        if not self.is_connected:
            raise ConnectionError_("drive is not connected; call connect() first")
        if expect_reply is None:
            expect_reply = not args
        text = self._format(command, args)
        if len(text) > MAX_COMMAND_LENGTH:
            raise ValueError(
                f"command {text!r} is {len(text)} characters; the drive's line "
                f"limit is {MAX_COMMAND_LENGTH}"
            )
        lines = self.transport.exchange(text, timeout=timeout, expect_reply=expect_reply)
        resp = Response(command=text, lines=lines, error_prefix=self.error_prefix)
        strict = self.strict if strict is None else strict
        if strict and resp.is_error:
            raise CommandError(text, resp.error_message or "unknown error", resp.text)
        return resp

    def query(self, command: str, *args: object, **kw) -> Response:
        """Send a command that must answer, raising on silence."""
        resp = self.raw(command, *args, **kw)
        if resp.empty:
            raise TimeoutError_(resp.command, self.transport.timeout)
        return resp

    def ping(self) -> bool:
        """True if the drive answers at all. Never raises."""
        try:
            return not self.raw("TREV", strict=False).empty
        except (ConnectionError_, TimeoutError_, OSError):
            return False

    # -- generic parameter access -----------------------------------------
    def get(self, name: str, **kw) -> Response:
        """Read a parameter by its friendly name from :data:`PARAMETERS`."""
        command = self._command_for(name)
        self._guard_action(command)
        return self.query(command, **kw)

    def set(self, name: str, value: object, verify: bool = True, **kw) -> Response:
        """Write a parameter by its friendly name, then read it back.

        The drive does not acknowledge writes, so a refused write is
        indistinguishable from an accepted one on the wire. With ``verify``
        (the default) the value is read back and compared, raising
        :class:`VerificationError` if it did not take. Returns the read-back
        response, so the caller sees the drive's own normalised value
        (``0.1`` comes back as ``0.100``).

        See the README on persistence before assuming a change survives a
        power cycle.
        """
        command = self._command_for(name)
        written = self.raw(command, value, **kw)
        if not verify:
            return written
        readback = self.raw(command, **kw)
        if not self._values_match(value, readback.value):
            raise VerificationError(
                f"{command}{value}", value, readback.value or "(no reply)"
            )
        return readback

    @staticmethod
    def _values_match(wanted: object, actual: str) -> bool:
        """Compare numerically when both sides parse, else case-insensitively.

        The drive normalises what it stores - ``SGI0.1`` reads back as
        ``0.100`` - so a plain string comparison would report a false failure.
        """
        try:
            return float(str(wanted)) == float(actual)
        except (TypeError, ValueError):
            return str(wanted).strip().upper() == actual.strip().upper()

    @staticmethod
    def _guard_action(command: str) -> None:
        """Refuse to read a command that would act instead of reporting."""
        if command.upper() in ACTION_COMMANDS:
            raise ValueError(
                f"{command} performs an action when sent bare and has no "
                f"read-back form; reading it would change the drive's state"
            )

    @staticmethod
    def _command_for(name: str) -> str:
        try:
            return PARAMETER_COMMANDS[name]
        except KeyError:
            known = ", ".join(sorted(PARAMETER_COMMANDS))
            raise KeyError(f"unknown parameter {name!r}; known names: {known}") from None

    def snapshot(self, groups: Optional[list[str]] = None) -> dict[str, dict[str, str]]:
        """Read every parameter and return ``{group: {name: value}}``.

        Never raises on an unsupported command: a parameter the firmware does
        not know is reported as ``None`` rather than aborting the sweep, so this
        doubles as a way to see what a given unit supports.
        """
        out: dict[str, dict[str, str]] = {}
        for group, entries in PARAMETERS.items():
            if groups and group not in groups:
                continue
            out[group] = {}
            for name, entry in entries.items():
                cmd = entry[0]
                if cmd.upper() in ACTION_COMMANDS:
                    continue  # reading it would trigger it
                resp = self.raw(cmd, strict=False)
                out[group][name] = None if resp.empty or resp.is_error else resp.value
        return out

    # -- identity ----------------------------------------------------------
    def revision(self) -> str:
        """Firmware revision (``TREV``), e.g. ``Aries OS Revision 3.30``."""
        return self.query("TREV").value

    def motor(self) -> str:
        """Configured motor (``DMTR``), e.g. ``OTHER=R200D``."""
        return self.query("DMTR").value

    # -- status ------------------------------------------------------------
    def axis_status(self) -> Response:
        """Axis status bits (``TAS``).

        Use ``.bit(n)`` with the manual's one-based numbering, or
        ``.set_bits()`` for the positions that are set.
        """
        return self.query("TAS")

    def input_states(self) -> Response:
        """Digital input states (``TIN``)."""
        return self.query("TIN")

    def output_states(self) -> Response:
        """Digital output states (``TOUT``)."""
        return self.query("TOUT")

    def is_enabled(self) -> bool:
        """Current enable state (``DRIVE``)."""
        return self.query("DRIVE").as_bool()

    # -- feedback ----------------------------------------------------------
    def position(self) -> int:
        """Encoder position in counts (``TPE``)."""
        return self.query("TPE").as_int()

    def commanded_position(self) -> int:
        """Commanded position in counts (``TPC``)."""
        return self.query("TPC").as_int()

    def position_error(self) -> int:
        """Following error in counts (``TPER``)."""
        return self.query("TPER").as_int()

    def velocity(self) -> float:
        """Commanded velocity (``TVEL``)."""
        return self.query("TVEL").as_float()

    def actual_velocity(self) -> float:
        """Actual velocity (``TVELA``)."""
        return self.query("TVELA").as_float()

    def torque(self) -> float:
        """Torque (``TTRQ``)."""
        return self.query("TTRQ").as_float()

    def analog_input(self) -> float:
        """Analog command input in volts (``TANI``)."""
        return self.query("TANI").as_float()

    # -- power -------------------------------------------------------------
    def bus_voltage(self) -> float:
        """DC bus voltage (``TVBUS``)."""
        return self.query("TVBUS").as_float()

    def drive_temperature(self) -> float:
        """Drive temperature in degrees C (``TDTEMP``)."""
        return self.query("TDTEMP").as_float()

    def motor_temperature(self) -> float:
        """Motor temperature in degrees C (``TMTEMP``)."""
        return self.query("TMTEMP").as_float()

    # -- enable ------------------------------------------------------------
    def enable(self, verify: bool = True) -> bool:
        """Energise the motor (``DRIVE1``). Returns the resulting enable state.

        The motor holds position after this, and in an analog command mode it
        will act on whatever is on the command input the instant it is
        energised - make sure the axis is clear and check :meth:`analog_input`
        first.

        ``DRIVE1`` is unacknowledged, so a refused enable is silent on the
        wire. With ``verify`` the state is read back and
        :class:`VerificationError` raised if the drive did not come up.
        """
        self.raw("DRIVE1", expect_reply=False)
        if not verify:
            return True
        state = self.is_enabled()
        if not state:
            raise VerificationError(
                "DRIVE1", True, False, self._why_not_enabled()
            )
        return state

    def _why_not_enabled(self) -> str:
        """Ask the drive why it refused, for the enable failure message."""
        try:
            active = self.active_errors()
        except AriesError:
            return "the drive refused to enable, and ERROR could not be read"
        if not active:
            return "the drive refused to enable but ERROR reports nothing active"
        return "the drive refused to enable: " + "; ".join(
            f"{code} {desc}" for code, desc in active
        )

    def disable(self, verify: bool = True) -> bool:
        """De-energise the motor (``DRIVE0``). The load is free to move."""
        self.raw("DRIVE0", expect_reply=False)
        if not verify:
            return False
        state = self.is_enabled()
        if state:
            raise VerificationError("DRIVE0", False, True, "the drive stayed enabled")
        return state

    def reset(self, wait: bool = True, timeout: float = 20.0) -> Optional[float]:
        """Reboot the drive (``RESET``), returning seconds until it answered.

        The reboot cuts the echo off mid-word and the drive is unreachable for
        roughly two seconds. With ``wait`` this polls until the link has both
        dropped *and* recovered, so a caller cannot read stale values from a
        drive that has not actually come back yet. Returns ``None`` when
        ``wait`` is False.

        Parameters survive the reboot - the drive stores them itself, with no
        save command needed.
        """
        self.transport.write_line(self._format("RESET", ()))
        if not wait:
            return None

        t0 = time.monotonic()
        went_down = False
        while time.monotonic() - t0 < timeout:
            alive = not self.raw("TREV", strict=False, timeout=RESET_POLL).empty
            if not alive:
                went_down = True
            elif went_down:
                elapsed = time.monotonic() - t0
                time.sleep(RESET_SETTLE)
                self.transport.flush_input()
                return elapsed
            time.sleep(0.05)

        if not went_down:
            raise VerificationError(
                "RESET", "a reboot", "the drive never stopped answering"
            )
        raise TimeoutError_("RESET", timeout, "drive did not come back")

    # -- text reports ------------------------------------------------------
    def error_report(self, timeout: float = 3.0) -> Response:
        """Raw ``ERROR`` report: the conditions preventing the drive enabling."""
        return self.query("ERROR", timeout=timeout)

    def active_errors(self, timeout: float = 3.0) -> list[tuple[str, str]]:
        """Active errors as ``[(code, description)]``, empty when there are none.

        ``ERROR`` answers with text - ``NO ERRORS``, or lines naming codes such
        as ``E46-Hardware Enable``. Codes are matched against
        :data:`~parker_ar04ae.reference.ERROR_CODES`, and an unrecognised one is
        still returned, paired with the drive's own wording.
        """
        resp = self.error_report(timeout=timeout)
        if not resp.lines or "NO ERROR" in resp.text.upper():
            return []
        found: list[tuple[str, str]] = []
        for match in re.finditer(r"\b(E\d{1,2})\b[\s\-:]*([^\n]*)", resp.text):
            code, tail = match.group(1).upper(), match.group(2).strip()
            found.append((code, ERROR_CODES.get(code) or tail or "unrecognised code"))
        return found

    def status(self, timeout: float = 4.0) -> list[str]:
        """The ``STATUS`` full-text report, one entry per line.

        Note this is ``STATUS``, not ``TSTAT`` - the latter does not exist on
        this firmware.
        """
        return self.query("STATUS", timeout=timeout).lines

    def error_log(self, timeout: float = 5.0) -> list[str]:
        """The ``TERRLG`` error log: the last ten errors or power cycles."""
        return self.query("TERRLG", timeout=timeout).lines

    def clear_error_log(self) -> Response:
        """Erase the error log (``CERRLG``)."""
        return self.raw("CERRLG", expect_reply=False)

    def config_report(self, timeout: float = 4.0) -> list[str]:
        """Configuration errors and warnings (``CONFIG``)."""
        return self.query("CONFIG", timeout=timeout).lines

    # -- decoded configuration --------------------------------------------
    def drive_mode(self) -> int:
        """Control mode as an integer (``DMODE``)."""
        return self.query("DMODE").as_int()

    def drive_mode_name(self) -> str:
        """Control mode as text, e.g. ``Velocity Control`` for mode 4."""
        entry = DRIVE_MODES.get(self.drive_mode())
        return entry[0] if entry else "unknown mode"

    def feedback_type(self) -> str:
        """Feedback source as text (``SFB``)."""
        return FEEDBACK_TYPES.get(self.query("SFB").as_int(), "unknown")

    # -- analog command input ---------------------------------------------
    def zero_command_offset(self, volts: Optional[Number] = None) -> Response:
        """Set the analog command zero point (``DCMDZ``).

        Called bare, the drive takes the *voltage currently on the input* as its
        new zero - so short AIN+ to AIN- on the DRIVE I/O connector, or have the
        controller command 0 V, before calling it. Passing ``volts`` sets an
        explicit zero point instead.

        Unlike every other command here, ``DCMDZ`` uses an ``=`` in its syntax
        (``DCMDZ=0.5``), which is why it is not a plain :meth:`set`. It also has
        no read-back form - the manual gives its Response as ``N/A`` - so the
        only way to see the effect is that :meth:`analog_input` reports the
        voltage *after* the zero point is applied.

        Calling this bare therefore changes drive state, and there is no way to
        recover the previous zero point from the drive afterwards. Note the
        present ``TANI`` reading first if you may need to put it back.
        """
        if volts is None:
            return self.raw("DCMDZ", expect_reply=False)
        return self.raw(f"DCMDZ={volts}", expect_reply=False)

    def will_move_on_enable(self) -> tuple[bool, str]:
        """Would enabling the drive command motion right now?

        In torque (``DMODE2``) and velocity (``DMODE4``) modes the drive acts on
        the analog command input the instant it is energised - there is no
        separate "go". This compares the input against the configured zero point
        and deadband and returns ``(will_move, explanation)``.

        A best-effort safety aid, not an interlock: it reads three parameters
        over a serial link and cannot see what the controller does next. Never
        rely on it in place of the hardware enable or an E-stop.
        """
        mode = self.drive_mode()
        if mode not in ANALOG_COMMAND_MODES:
            name = DRIVE_MODES.get(mode, ("unknown mode",))[0]
            return False, f"DMODE{mode} ({name}) does not follow the analog input"

        # TANI reports the voltage *after* the DCMDZ zero point is applied, so
        # the effective command is TANI itself. DCMDZ is deliberately not read:
        # sending it bare re-zeros the input (see ACTION_COMMANDS).
        volts = self.analog_input()
        deadband = self._optional_float("ANICDB", 0.04)
        name = DRIVE_MODES[mode][0]

        if abs(volts) <= deadband:
            return False, (
                f"DMODE{mode} ({name}): command input is {volts:+.3f} V, inside "
                f"the {deadband:.3f} V deadband"
            )

        scale_cmd = "DMVSCL" if mode == 4 else "DMTSCL"
        scale = self._optional_float(scale_cmd, 0.0)
        # Rev G, ANICDB: command = (Vin - DCMDZ -/+ ANICDB) * scale / 10
        magnitude = (abs(volts) - deadband) * scale / 10.0
        units = "rev/s" if mode == 4 else "A"
        estimate = (
            f", which {scale_cmd}{scale:g} scales to about "
            f"{magnitude * (1 if volts > 0 else -1):+.3f} {units}"
            if scale else ""
        )
        return True, (
            f"DMODE{mode} ({name}): command input is {volts:+.3f} V, outside the "
            f"{deadband:.3f} V deadband{estimate} - the motor will move on enable"
        )

    def _optional_float(self, command: str, fallback: float) -> float:
        """Read a float, falling back when the firmware lacks the command."""
        resp = self.raw(command, strict=False)
        try:
            return resp.as_float()
        except (ValueError, IndexError):
            return fallback

    def __repr__(self) -> str:
        state = "connected" if self.is_connected else "closed"
        return f"<AriesDrive {self.transport.port!r} {state}>"
