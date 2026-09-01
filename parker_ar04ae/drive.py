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
import time
from typing import Optional, Union

from .errors import (
    CommandError,
    ConnectionError_,
    TimeoutError_,
    VerificationError,
)
from .protocol import DEFAULT_BAUD, ERROR_PREFIX
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
#: ``name -> (command, description)``. Sending the bare command reads the
#: value; appending a value writes it. Used by :meth:`AriesDrive.snapshot`.
PARAMETERS: dict[str, dict[str, tuple[str, str]]] = {
    "identity": {
        "revision": ("TREV", "firmware revision"),
        "motor": ("DMTR", "configured motor"),
        "address": ("ADDR", "daisy-chain unit address"),
        "echo": ("ECHO", "serial echo enabled"),
        "error_level": ("ERRLVL", "error reporting verbosity"),
    },
    "status": {
        "enabled": ("DRIVE", "drive enabled"),
        "axis_status": ("TAS", "axis status bits"),
        "inputs": ("TIN", "digital input states"),
        "outputs": ("TOUT", "digital output states"),
    },
    "feedback": {
        "position": ("TPE", "encoder position, counts"),
        "commanded_position": ("TPC", "commanded position, counts"),
        "position_error": ("TPER", "following error, counts"),
        "velocity": ("TVEL", "commanded velocity"),
        "actual_velocity": ("TVELA", "actual velocity"),
        "torque": ("TTRQ", "torque"),
        "analog_input": ("TANI", "analog command input, volts"),
    },
    "power": {
        "bus_voltage": ("TVBUS", "DC bus voltage"),
        "drive_temperature": ("TDTEMP", "drive temperature, degC"),
        "motor_temperature": ("TMTEMP", "motor temperature, degC"),
    },
    "drive_config": {
        "drive_mode": ("DMODE", "command source / drive mode"),
        "encoder_resolution": ("ERES", "encoder resolution, counts/rev"),
        "resolution": ("DRES", "drive resolution, counts/rev"),
        "current_foldback": ("DIFOLD", "current foldback enabled"),
        "thermal_mode": ("DTHERM", "motor thermal protection mode"),
        "pwm_frequency": ("DPWM", "PWM frequency setting"),
    },
    "motor_config": {
        "continuous_current": ("DMTIC", "motor continuous current, A"),
        "current_limit": ("DMTLIM", "motor current limit, A"),
        "peak_current_time": ("DMTW", "peak current duration"),
        "back_emf": ("DMTKE", "back-EMF constant"),
        "winding_resistance": ("DMTRES", "winding resistance, ohm"),
        "winding_inductance": ("DMTIND", "winding inductance, mH"),
        "poles": ("DPOLE", "motor poles"),
        "inertia": ("DMTJ", "rotor inertia"),
        "damping": ("DMTD", "damping"),
        "encoder_pitch": ("DMEPIT", "encoder pitch"),
    },
    "servo_gains": {
        "gain_p": ("SGP", "proportional gain"),
        "gain_i": ("SGI", "integral gain"),
        "gain_v": ("SGV", "velocity gain"),
        "gain_vf": ("SGVF", "velocity feedforward"),
        "gain_af": ("SGAF", "acceleration feedforward"),
        "feedback_source": ("SFB", "servo feedback source"),
        "max_position_error": ("SMPER", "maximum allowable position error"),
    },
}

#: Flat ``name -> command`` view of :data:`PARAMETERS`.
PARAMETER_COMMANDS: dict[str, str] = {
    name: cmd
    for group in PARAMETERS.values()
    for name, (cmd, _) in group.items()
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
        return self.query(self._command_for(name), **kw)

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
            for name, (cmd, _) in entries.items():
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
                "DRIVE1", True, False,
                "the drive refused to enable. Check the hardware enable input "
                "(TIN), the axis status bits (TAS) and the bus voltage (TVBUS)",
            )
        return state

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

    def __repr__(self) -> str:
        state = "connected" if self.is_connected else "closed"
        return f"<AriesDrive {self.transport.port!r} {state}>"
