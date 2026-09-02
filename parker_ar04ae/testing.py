"""In-memory fakes, so the library can be exercised with no hardware attached.

    from parker_ar04ae import AriesDrive
    from parker_ar04ae.testing import FakePort

    port = FakePort({"TREV": "Aries OS Revision 3.30"})
    drive = AriesDrive(byte_port=port).connect()
    drive.revision()

:class:`FakePort` reproduces the real wire format - command echo, optional DC1
lead marker, reply lines, then the ENQ end-of-response prompt.
"""

from __future__ import annotations

import re
from typing import Callable, Mapping, Union

from .protocol import DC1, ENQ, REPLACEMENT_CHAR
from .transport import BytePort

Reply = Union[str, list, Callable[[str], str], None]

#: A write carries a numeric value, e.g. ``SGI0.1``, ``DRIVE1`` or - for DCMDZ,
#: which uses an ``=`` in its documented syntax - ``DCMDZ=0.5``. Requiring a
#: numeric suffix keeps ``TASX`` from being read as a write of ``X`` to ``TAS``.
_NUMERIC = re.compile(r"^=?[-+]?(?:\d+\.?\d*|\.\d+)$")


class FakePort(BytePort):
    """A ``BytePort`` that answers from a lookup table instead of a wire.

    Parameters
    ----------
    replies:
        Maps an upper-cased command to the text sent back. The value may be a
        string, a list of lines, a callable taking the command, or ``None`` to
        echo with no value and no ENQ, as a write does. A command with no entry
        gets ``default``.
    echo:
        Echo the received command back first, as the drive does with ``ECHO1``.
        A ``\ufffd`` anywhere in a reply is emitted as an undecodable byte, so
        scripted replies can model the line noise the motor produces.
    enq:
        Terminate each *query* reply with the ENQ prompt, as the drive does.
        Set ``False`` to model a unit that never sends one.
    emulate_writes:
        Model the drive's write behaviour: ``SGI0.1`` stores ``0.1`` against
        ``SGI`` and replies with the echo only - no value and no ENQ, exactly
        as the hardware does.
    refuse:
        Commands whose writes are silently ignored, the way the real drive
        ignores ``DRIVE1`` when it will not enable. The echo still comes back,
        so the refusal is invisible until the value is read again.
    default:
        Reply for an unknown command. Pass ``""`` to model a dead link, where
        nothing comes back at all.
    """

    def __init__(
        self,
        replies: Mapping[str, Reply] | None = None,
        echo: bool = True,
        eol: str = "\r\n",
        enq: bool = True,
        default: Reply = "ERROR: Unknown Command",
        emulate_writes: bool = True,
        refuse: set[str] | None = None,
    ):
        self.replies = dict(replies or {})
        self.echo = echo
        self.eol = eol
        self.enq = enq
        self.default = default
        self.emulate_writes = emulate_writes
        self.refuse = {c.upper() for c in (refuse or set())}
        self.written: list[str] = []
        self._rx = bytearray()
        self._tx_partial = ""
        self._open = False

    # -- BytePort ----------------------------------------------------------
    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def write(self, data: bytes) -> int:
        self._tx_partial += data.decode("ascii", errors="replace")
        while "\r" in self._tx_partial:
            line, self._tx_partial = self._tx_partial.split("\r", 1)
            self._handle(line.strip())
        return len(data)

    def read(self, size: int) -> bytes:
        chunk = bytes(self._rx[:size])
        del self._rx[:size]
        return chunk

    @property
    def in_waiting(self) -> int:
        return len(self._rx)

    def reset_input_buffer(self) -> None:
        self._rx.clear()

    # -- behaviour ---------------------------------------------------------
    def _split_write(self, command: str) -> tuple[str, str] | None:
        """Split ``SGI0.1`` into ``("SGI", "0.1")`` using the longest known
        command that prefixes it. Returns None if this is not a write."""
        upper = command.upper()
        for i in range(len(upper) - 1, 0, -1):
            if upper[:i] in self.replies and _NUMERIC.match(command[i:]):
                return upper[:i], command[i:]
        return None

    def _handle(self, command: str) -> None:
        if not command:
            return
        self.written.append(command)
        if self.echo:
            self._emit(command)

        if self.emulate_writes and command.upper() not in self.replies:
            write = self._split_write(command)
            if write is not None:
                name, value = write
                if name not in self.refuse:
                    self.replies[name] = value.lstrip("=")
                return  # a write echoes and says nothing more - no ENQ

        reply = self.replies.get(command.upper(), self.default)
        if callable(reply):
            reply = reply(command)
        if reply is None:
            return  # echo only, no value and no ENQ - what a write looks like
        for line in [reply] if isinstance(reply, str) else reply:
            self._emit(line)
        if self.enq:
            self._emit(ENQ)

    def _emit(self, line: str) -> None:
        # A replacement character in a scripted reply stands for line noise, so
        # put a byte on the wire that really is undecodable as ASCII. Encoding
        # it normally would yield "?", which decodes cleanly and would not
        # exercise the corruption path at all.
        data = bytearray()
        for ch in line + self.eol:
            data += b"\xff" if ch == REPLACEMENT_CHAR else ch.encode(
                "ascii", errors="replace"
            )
        self._rx += data

    def __repr__(self) -> str:
        return f"<FakePort {len(self.replies)} replies, {len(self.written)} received>"


#: Replies captured from an AR-04AE running Aries OS 3.30, idle and disabled.
#: TREV carries the DC1 lead marker the real drive sends.
DEMO_REPLIES: dict[str, Reply] = {
    "TREV": [DC1, "Aries OS Revision 3.30"],
    "TAS": "0000_0000_0000_0000",
    "TIN": "0000_0000_0000_0000",
    "TOUT": "0000_0000_0000_0011",
    "TPE": "0",
    "TPC": "0",
    "TPER": "0",
    "TVEL": "0.000",
    "TVELA": "0.000",
    "TTRQ": "0.000",
    "TANI": "0.940",
    "TVBUS": "163.1",
    "TDTEMP": "30.43",
    "TMTEMP": "25.00",
    "DRIVE": "0",
    "DMTR": "OTHER=R200D",
    "DMODE": "4",
    "ERES": "944000",
    "DRES": "944000",
    "DIFOLD": "1",
    "DTHERM": "0",
    "DPWM": "32",
    "DMTIC": "2.000",
    "DMTLIM": "4.000",
    "DMTW": "5.000",
    "DMTKE": "325.0",
    "DMTRES": "10.40",
    "DMTIND": "21.00",
    "DMEPIT": "0.000",
    "DPOLE": "16",
    "DMTJ": "33158.0",
    "DMTD": "134.9",
    "SGP": "2.000",
    "SGI": "0.000",
    "SGV": "2.000",
    "SGVF": "0.000",
    "SGAF": "0.000",
    "SFB": "2",
    "SMPER": "944000",
    "ECHO": "1",
    "ADDR": "0",
    "ERRLVL": "4",
}


#: Plausible replies for commands documented in the Rev G manual but not seen on
#: the hardware this library was developed against. Kept separate from
#: DEMO_REPLIES so it stays clear which values came off a real drive: these are
#: shaped from the manual's own examples, not captured.
DOC_REPLIES: dict[str, Reply] = {
    "ERROR": "NO ERRORS",
    "STATUS": [
        "GENERAL:", " OS Revision: Aries Revision 3.30", " Power Level: 400W",
        " Control Power: INACTIVE", "MOTOR:", " Motor Name: R200D",
        " Motor Type: ROTARY", " Feedback Type: SMART ENCODER",
        " Motor Temp: 25C", "DRIVE", " Drive: DISABLED",
        " PWM Frequency: 32 kHz", " Feedback Resolution: 944000",
        " Drive Temperature: 30C", " Bus Voltage: 163V",
    ],
    "TERRLG": [
        "Operating hours: 105.25", "Power on Time: 5hrs 10 min 45.35 s",
        "Drive Temp: 30C", "Motor Temp: 25C", "Bus voltage: 163V",
        "Command Voltage: 0.93V", "[Power Cycle]",
    ],
    "CONFIG": "NO ERRORS",
    "CERRLG": None,   # an action: echoes, then silence
    "PSET": None,     # position reference; writes only, no read-back
    "SFB": "5",
    "ANICDB": "0.040",
    "DCMDZ": "0.000",
    "TCI": "0.000",
    "TTRQA": "0.000",
    "TVER": "0.000",
    "THALL": "5",
    "TDHRS": "105",
    "DMVLIM": "100.0",
    "DMTSCL": "1.000",
    "DMVSCL": "100.0",
}

#: Everything the fake knows: hardware captures plus manual-derived examples.
ALL_REPLIES: dict[str, Reply] = {**DEMO_REPLIES, **DOC_REPLIES}


def demo_drive(**kwargs):
    """An :class:`~parker_ar04ae.drive.AriesDrive` wired to a connected fake."""
    from .drive import AriesDrive

    return AriesDrive(byte_port=FakePort(ALL_REPLIES), **kwargs).connect()
