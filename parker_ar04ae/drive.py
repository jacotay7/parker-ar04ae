"""High-level interface to a Parker ARIES AR-04AE servo drive.

Wiring on a Mac is USB-C -> USB-A -> USB/RS-232 adapter -> the drive's RS-232
port, which shows up as ``/dev/cu.usbserial-*``. Use the ``cu.*`` node, not the
``tty.*`` one: ``tty.*`` blocks on open waiting for carrier detect.

    from parker_ar04ae import AriesDrive

    with AriesDrive("/dev/cu.usbserial-A50285BI") as drive:
        print(drive.revision())
        print(drive.axis_status().as_bits())

Command coverage
----------------
The AR-04AE is the *drive-only* member of the ARIES family: it follows step/
direction or +/-10V analog command from an external controller, and its RS-232
port is there for configuration and diagnostics. The methods under "motion" are
onboard-move commands that exist on the ARIES Controller (AR-xxCE); on an AE
unit they are expected to answer ``*UNDEFINED_COMMAND``. They are included so a
CE unit works with the same class, and are marked in their docstrings.

Any command can be sent verbatim with :meth:`raw`, so nothing is gated on this
module knowing about it.
"""

from __future__ import annotations

import logging
from typing import Optional, Union

from .errors import CommandError, ConnectionError_, TimeoutError_
from .response import ERROR_TOKENS, Response
from .transport import BytePort, SerialPort, SerialTransport

log = logging.getLogger(__name__)

Number = Union[int, float]

#: Baud rates the ARIES RS-232 port can be configured for. 9600 is the factory
#: default and what ``probe`` tries first.
BAUD_RATES = (9600, 19200, 38400, 57600, 115200)


class AriesDrive:
    """A single ARIES drive on a serial port.

    Parameters
    ----------
    port:
        Device path, e.g. ``/dev/cu.usbserial-1420``. Ignored if ``transport``
        is given.
    baudrate:
        Serial speed; must match the drive's own setting.
    address:
        Unit address for a daisy chain. When set, commands go out prefixed as
        ``<address>_COMMAND``. Leave as ``None`` for a single drive.
    timeout:
        Seconds to wait for the first byte of a response.
    strict:
        Raise :class:`CommandError` when the drive reports an error. Set
        ``False`` to get the error back in the :class:`Response` instead.
    transport:
        Supply a pre-built transport (or a fake one) instead of a port path.
    """

    def __init__(
        self,
        port: Optional[str] = None,
        baudrate: int = 9600,
        address: Optional[int] = None,
        timeout: float = 1.0,
        strict: bool = True,
        transport: Optional[SerialTransport] = None,
        byte_port: Optional[BytePort] = None,
        error_tokens: frozenset = ERROR_TOKENS,
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
        self.error_tokens = error_tokens

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
        quiet_time: Optional[float] = None,
        strict: Optional[bool] = None,
    ) -> Response:
        """Send ``command`` verbatim and return the parsed :class:`Response`.

        Arguments are concatenated directly onto the command, matching Parker's
        syntax (``DMTR`` + ``BE231FJ`` -> ``DMTRBE231FJ``).
        """
        if not self.is_connected:
            raise ConnectionError_("drive is not connected; call connect() first")
        text = self._format(command, args)
        lines = self.transport.exchange(text, timeout=timeout, quiet_time=quiet_time)
        resp = Response(command=text, lines=lines, error_tokens=self.error_tokens)
        strict = self.strict if strict is None else strict
        if strict and resp.is_error:
            raise CommandError(text, resp.error_code or "UNKNOWN", resp.text)
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

    # -- identity and diagnostics -----------------------------------------
    def revision(self) -> str:
        """Firmware/product revision (``TREV``)."""
        return self.query("TREV").value

    def status_report(self, timeout: float = 3.0) -> list[str]:
        """The full multi-line status page (``TSTAT``).

        Slower and chattier than the individual queries; a longer timeout and
        quiet time are used so the whole page is captured.
        """
        return self.query("TSTAT", timeout=timeout, quiet_time=0.4).lines

    def axis_status(self) -> Response:
        """Axis status bits (``TAS``). Use ``.bit(n)`` with the manual's numbering."""
        return self.query("TAS")

    def extended_status(self) -> Response:
        """Extended axis status bits (``TASX``)."""
        return self.query("TASX")

    def error_status(self) -> Response:
        """Error status bits (``TER``)."""
        return self.query("TER")

    def drive_fault(self) -> bool:
        """True if any bit of ``TER`` is set."""
        return "1" in self.error_status().as_bits()

    def input_states(self) -> Response:
        """Digital input states (``TIN``)."""
        return self.query("TIN")

    def output_states(self) -> Response:
        """Digital output states (``TOUT``)."""
        return self.query("TOUT")

    def analog_input(self) -> float:
        """Analog command input in volts (``TANI``)."""
        return self.query("TANI").as_float()

    def drive_temperature(self) -> float:
        """Drive heatsink temperature (``TDTEMP``)."""
        return self.query("TDTEMP").as_float()

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
        """Actual velocity (``TVEL``)."""
        return self.query("TVEL").as_float()

    def current(self) -> float:
        """Commanded motor current in amps (``TCMD``)."""
        return self.query("TCMD").as_float()

    def feedback(self) -> Response:
        """All feedback-device positions (``TFB``)."""
        return self.query("TFB")

    # -- drive enable ------------------------------------------------------
    def enable(self) -> Response:
        """Energise the motor (``DRIVE1``).

        The motor holds position after this; make sure the axis is clear.
        """
        return self.raw("DRIVE1")

    def disable(self) -> Response:
        """De-energise the motor (``DRIVE0``). The load is free to move."""
        return self.raw("DRIVE0")

    def is_enabled(self) -> bool:
        """Current enable state (``DRIVE``)."""
        return self.query("DRIVE").as_bool()

    def reset(self) -> None:
        """Reset the drive (``RESET``).

        Equivalent to a power cycle: the drive drops off the serial link for
        several seconds and does not answer, so no response is read.
        """
        self.transport.write_line(self._format("RESET", ()))

    # -- configuration -----------------------------------------------------
    def motor(self, part_number: Optional[str] = None) -> Response:
        """Read or set the configured motor (``DMTR``).

        Called with no argument this reads the current selection. Passing a
        Parker motor part number selects it; the drive must be disabled.
        """
        return self.query("DMTR") if part_number is None else self.raw("DMTR", part_number)

    def drive_mode(self, mode: Optional[int] = None) -> Response:
        """Read or set the command source / drive mode (``DMODE``)."""
        return self.query("DMODE") if mode is None else self.raw("DMODE", mode)

    def encoder_resolution(self, counts: Optional[int] = None) -> Response:
        """Read or set encoder resolution in counts/rev (``ERES``)."""
        return self.query("ERES") if counts is None else self.raw("ERES", counts)

    def set_echo(self, on: bool) -> Response:
        """Turn the drive's character echo on or off (``ECHO``).

        The transport strips echoes either way, so this is mostly for quieting
        the link. Keep :attr:`SerialTransport.echo` in step if you change it.
        """
        resp = self.raw("ECHO", 1 if on else 0)
        self.transport.echo = on
        return resp

    def set_address(self, address: int) -> Response:
        """Set the daisy-chain unit address (``ADDR``)."""
        return self.raw("ADDR", address)

    # -- motion (ARIES Controller AR-xxCE only; see module docstring) ------
    def go(self) -> Response:
        """Start a move (``GO``). *AR-xxCE only.*"""
        return self.raw("GO")

    def stop(self) -> Response:
        """Decelerate to a stop (``S``). *AR-xxCE only.*"""
        return self.raw("S")

    def kill(self) -> Response:
        """Abort motion immediately (``K``). *AR-xxCE only.*

        This is not a safety stop; it is not a substitute for the drive's
        hardware enable or an E-stop circuit.
        """
        return self.raw("K")

    def set_distance(self, counts: int) -> Response:
        """Set move distance/target in counts (``D``). *AR-xxCE only.*"""
        return self.raw("D", counts)

    def set_velocity(self, value: Number) -> Response:
        """Set move velocity in rev/s (``V``). *AR-xxCE only.*"""
        return self.raw("V", value)

    def set_acceleration(self, value: Number) -> Response:
        """Set acceleration in rev/s^2 (``A``). *AR-xxCE only.*"""
        return self.raw("A", value)

    def set_deceleration(self, value: Number) -> Response:
        """Set deceleration in rev/s^2 (``AD``). *AR-xxCE only.*"""
        return self.raw("AD", value)

    def set_absolute_mode(self, absolute: bool = True) -> Response:
        """Absolute (``MA1``) or incremental (``MA0``) positioning. *AR-xxCE only.*"""
        return self.raw("MA", 1 if absolute else 0)

    def home(self) -> Response:
        """Start the homing move (``HOM``). *AR-xxCE only.*"""
        return self.raw("HOM")

    def __repr__(self) -> str:
        state = "connected" if self.is_connected else "closed"
        return f"<AriesDrive {self.transport.port!r} {state}>"
