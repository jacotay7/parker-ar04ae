"""Serial transport for Parker ARIES drives.

Two layers live here:

``BytePort``
    A minimal byte-level port interface. ``SerialPort`` implements it on top of
    pyserial; ``parker_ar04ae.testing.FakePort`` implements it in memory so the
    framing logic can be exercised without hardware.

``SerialTransport``
    Framing on top of a ``BytePort``: append CR on write, read until the drive
    sends its ENQ end-of-response prompt, then split on CRLF and drop the
    command echo and the protocol's control markers.

See :mod:`parker_ar04ae.protocol` for the wire format.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Optional

from .errors import ConnectionError_
from .protocol import DC1, ENQ, EOL, WRITE_QUIET

log = logging.getLogger(__name__)

#: Poll interval while waiting for bytes to arrive.
POLL_INTERVAL = 0.005

#: After ENQ arrives, how long to keep draining so the CRLF that follows it does
#: not leak into the next reply.
TRAILER_DRAIN = 0.03


class BytePort(ABC):
    """Byte-level serial port interface."""

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @property
    @abstractmethod
    def is_open(self) -> bool: ...

    @abstractmethod
    def write(self, data: bytes) -> int: ...

    @abstractmethod
    def read(self, size: int) -> bytes: ...

    @property
    @abstractmethod
    def in_waiting(self) -> int: ...

    @abstractmethod
    def reset_input_buffer(self) -> None: ...


class SerialPort(BytePort):
    """``BytePort`` backed by pyserial.

    The pyserial object is created lazily in :meth:`open` so that constructing a
    drive object never touches hardware.
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 9600,
        bytesize: int = 8,
        parity: str = "N",
        stopbits: float = 1,
        rtscts: bool = False,
        xonxoff: bool = False,
    ):
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.rtscts = rtscts
        self.xonxoff = xonxoff
        self._serial = None

    def open(self) -> None:
        if self._serial is not None and self._serial.is_open:
            return
        try:
            import serial
        except ImportError as exc:  # pragma: no cover - depends on install
            raise ConnectionError_(
                "pyserial is not installed; run: pip install pyserial"
            ) from exc
        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=self.bytesize,
                parity=self.parity,
                stopbits=self.stopbits,
                rtscts=self.rtscts,
                # The drive uses DC1/ENQ as protocol markers, so software flow
                # control must stay off or pyserial would eat them.
                xonxoff=False,
                timeout=0,  # non-blocking; SerialTransport owns the deadlines
                write_timeout=2.0,
            )
        except Exception as exc:
            raise ConnectionError_(f"could not open {self.port}: {exc}") from exc
        log.debug("opened %s at %d baud", self.port, self.baudrate)

    def close(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def _require(self):
        if not self.is_open:
            raise ConnectionError_(f"port {self.port} is not open")
        return self._serial

    def write(self, data: bytes) -> int:
        return self._require().write(data)

    def read(self, size: int) -> bytes:
        return self._require().read(size)

    @property
    def in_waiting(self) -> int:
        return self._require().in_waiting

    def reset_input_buffer(self) -> None:
        self._require().reset_input_buffer()

    def __repr__(self) -> str:
        return f"<SerialPort {self.port} @ {self.baudrate}>"


class SerialTransport:
    """Line framing over a :class:`BytePort`.

    Parameters
    ----------
    port:
        The underlying byte port.
    timeout:
        Seconds to wait for the drive's ENQ end-of-response prompt.
    eol:
        Terminator appended to every command; the drive expects a bare CR.
    encoding:
        Wire encoding. The protocol is ASCII.
    """

    def __init__(
        self,
        port: BytePort,
        timeout: float = 1.0,
        eol: str = EOL,
        encoding: str = "ascii",
    ):
        self.port = port
        self.timeout = timeout
        self.eol = eol
        self.encoding = encoding

    # -- lifecycle ---------------------------------------------------------
    def open(self) -> None:
        self.port.open()

    def close(self) -> None:
        self.port.close()

    @property
    def is_open(self) -> bool:
        return self.port.is_open

    def __enter__(self) -> "SerialTransport":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- raw I/O -----------------------------------------------------------
    def flush_input(self) -> None:
        """Discard anything the drive has already sent."""
        self.port.reset_input_buffer()

    def write_line(self, text: str) -> None:
        data = (text + self.eol).encode(self.encoding, errors="replace")
        log.debug("TX %r", data)
        self.port.write(data)

    def read_quiet(
        self, quiet: float = WRITE_QUIET, max_wait: Optional[float] = None
    ) -> str:
        """Read until the line has been silent for ``quiet`` seconds.

        Used after a write, which echoes the command and then sends nothing -
        no value and no ENQ - so there is no marker to stop on. Draining the
        echo here keeps it out of the head of the next reply.
        """
        max_wait = self.timeout if max_wait is None else max_wait
        buf = bytearray()
        deadline = time.monotonic() + max_wait
        last_rx = None
        while time.monotonic() < deadline:
            if self.port.in_waiting:
                buf += self.port.read(self.port.in_waiting)
                last_rx = time.monotonic()
            elif last_rx is not None and time.monotonic() - last_rx >= quiet:
                break
            time.sleep(POLL_INTERVAL)
        text = buf.decode(self.encoding, errors="replace")
        if text:
            log.debug("RX %r", text)
        return text

    def read_raw(self, timeout: Optional[float] = None) -> str:
        """Read one reply, stopping at the drive's ENQ prompt.

        Returns whatever arrived if ``timeout`` expires first, so a drive that
        never sends ENQ degrades to a plain timed read rather than hanging.
        """
        timeout = self.timeout if timeout is None else timeout
        enq = ENQ.encode(self.encoding)

        buf = bytearray()
        deadline = time.monotonic() + timeout
        drain_until = None

        while True:
            if self.port.in_waiting:
                buf += self.port.read(self.port.in_waiting)
                # Keep draining briefly past ENQ so its trailing CRLF does not
                # show up at the head of the next reply.
                if drain_until is None and enq in buf:
                    drain_until = time.monotonic() + TRAILER_DRAIN
            if drain_until is not None:
                if time.monotonic() >= drain_until:
                    break
            elif time.monotonic() >= deadline:
                break
            time.sleep(POLL_INTERVAL)

        text = buf.decode(self.encoding, errors="replace")
        if text:
            log.debug("RX %r", text)
        return text

    # -- framing -----------------------------------------------------------
    @staticmethod
    def split_lines(text: str) -> list[str]:
        """Split a raw reply into clean, non-empty lines.

        Drops the ENQ prompt and the DC1 lead marker, and any other stray
        control characters, which ``str.strip`` alone would leave behind as
        phantom non-empty lines.
        """
        lines = []
        for chunk in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            chunk = "".join(c for c in chunk if c >= " " and c != "\x7f")
            chunk = chunk.strip()
            if chunk:
                lines.append(chunk)
        return lines

    @staticmethod
    def looks_like_echo(command: str, line: str) -> bool:
        """True if ``line`` is the drive echoing ``command`` back.

        Tolerates a single mangled character. Motor PWM noise flips bits on the
        echo as readily as on the reply - ``TANI`` has come back as ``TQNI`` and
        ``UANI``, ``TVBUS`` as ``\VBUS`` - and an unstripped echo is worse than
        a dropped one, because it silently becomes the value. A genuine reply
        differing from the command name in exactly one character is not a case
        worth worrying about.
        """
        want = command.strip().upper()
        got = line.strip().upper()
        if want == got:
            return True
        if len(want) != len(got) or not want:
            return False
        return sum(a != b for a, b in zip(want, got)) == 1

    def strip_echo(self, command: str, lines: list[str]) -> list[str]:
        """Drop the leading echo of ``command`` from ``lines``, if present.

        Always checked rather than keyed off a configured flag: ECHO is a
        setting on the drive and may not match what we assume.
        """
        if lines and self.looks_like_echo(command, lines[0]):
            return lines[1:]
        return lines

    def exchange(
        self,
        command: str,
        timeout: Optional[float] = None,
        expect_reply: bool = True,
    ) -> list[str]:
        """Send ``command`` and return the reply lines, echo and markers removed.

        With ``expect_reply=False`` the read stops at a short silence instead of
        waiting for an ENQ that a write will never send. Without this a write
        blocks for the whole timeout.
        """
        self.write_line(command)
        raw = (
            self.read_raw(timeout=timeout)
            if expect_reply
            else self.read_quiet(max_wait=timeout)
        )
        return self.strip_echo(command, self.split_lines(raw))

    def __repr__(self) -> str:
        return f"<SerialTransport {self.port!r} timeout={self.timeout}>"
