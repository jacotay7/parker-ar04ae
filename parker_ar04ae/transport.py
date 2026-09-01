"""Serial transport for Parker ARIES drives.

Two layers live here:

``BytePort``
    A minimal byte-level port interface. ``SerialPort`` implements it on top of
    pyserial; ``parker_ar04ae.testing.FakePort`` implements it in memory so the
    framing logic can be exercised without hardware.

``SerialTransport``
    Line framing on top of a ``BytePort``: append the terminator on write,
    accumulate bytes on read, split on CR/LF, drop the command echo and the
    ``>`` prompt that the drive emits in full-duplex mode.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Optional

from .errors import ConnectionError_

log = logging.getLogger(__name__)

#: Poll interval while waiting for bytes to arrive.
POLL_INTERVAL = 0.005


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
                xonxoff=self.xonxoff,
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
    """Line-oriented framing over a :class:`BytePort`.

    Parameters
    ----------
    port:
        The underlying byte port.
    timeout:
        Default seconds to wait for the first byte of a response.
    quiet_time:
        Once bytes have arrived, how long the line must stay silent before the
        response is considered complete. Multi-line reports (``TSTAT``) arrive
        as a burst, so this is what separates "still streaming" from "done".
    eol:
        Terminator appended to every command. Parker drives use a bare CR.
    echo:
        ``True`` if the drive echoes the characters it receives (the factory
        default). The echoed command is stripped from the response.
    """

    def __init__(
        self,
        port: BytePort,
        timeout: float = 1.0,
        quiet_time: float = 0.12,
        eol: str = "\r",
        echo: bool = True,
        encoding: str = "ascii",
    ):
        self.port = port
        self.timeout = timeout
        self.quiet_time = quiet_time
        self.eol = eol
        self.echo = echo
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

    def read_raw(
        self, timeout: Optional[float] = None, quiet_time: Optional[float] = None
    ) -> str:
        """Read until the drive goes quiet, and return the decoded text.

        Returns an empty string if nothing arrived before ``timeout``.
        """
        timeout = self.timeout if timeout is None else timeout
        quiet_time = self.quiet_time if quiet_time is None else quiet_time

        buf = bytearray()
        deadline = time.monotonic() + timeout
        last_rx = None

        while True:
            n = self.port.in_waiting
            if n:
                buf += self.port.read(n)
                last_rx = time.monotonic()
            elif last_rx is not None:
                if time.monotonic() - last_rx >= quiet_time:
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
        """Split a raw response into stripped, non-empty lines.

        The drive terminates lines with CR, CRLF or LF depending on the command,
        and emits a bare ``>`` prompt in full-duplex mode; both are normalised
        away here.
        """
        lines = []
        for chunk in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            chunk = chunk.strip()
            if chunk and chunk != ">":
                lines.append(chunk)
        return lines

    def strip_echo(self, command: str, lines: list[str]) -> list[str]:
        """Drop the leading echo of ``command`` from ``lines``, if present.

        Always checked, not only when ``self.echo`` is set: the echo state is a
        property of the drive's configuration and may not match ours.
        """
        if lines and lines[0].strip().upper() == command.strip().upper():
            return lines[1:]
        return lines

    def exchange(
        self,
        command: str,
        timeout: Optional[float] = None,
        quiet_time: Optional[float] = None,
    ) -> list[str]:
        """Send ``command`` and return the response lines, echo removed."""
        self.write_line(command)
        raw = self.read_raw(timeout=timeout, quiet_time=quiet_time)
        return self.strip_echo(command, self.split_lines(raw))

    def __repr__(self) -> str:
        return f"<SerialTransport {self.port!r} timeout={self.timeout}>"
