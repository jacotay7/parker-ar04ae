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

from typing import Callable, Mapping, Union

from .protocol import DC1, ENQ
from .transport import BytePort

Reply = Union[str, list, Callable[[str], str]]


class FakePort(BytePort):
    """A ``BytePort`` that answers from a lookup table instead of a wire.

    Parameters
    ----------
    replies:
        Maps an upper-cased command to the text sent back. The value may be a
        string, a list of lines, or a callable taking the command. A command
        with no entry gets ``default``.
    echo:
        Echo the received command back first, as the drive does with ``ECHO1``.
    enq:
        Terminate each reply with the ENQ prompt, as the drive does. Set
        ``False`` to model a unit that never sends one.
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
    ):
        self.replies = dict(replies or {})
        self.echo = echo
        self.eol = eol
        self.enq = enq
        self.default = default
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
    def _handle(self, command: str) -> None:
        if not command:
            return
        self.written.append(command)
        if self.echo:
            self._emit(command)
        reply = self.replies.get(command.upper(), self.default)
        if callable(reply):
            reply = reply(command)
        for line in [reply] if isinstance(reply, str) else reply:
            self._emit(line)
        if self.enq:
            self._emit(ENQ)

    def _emit(self, line: str) -> None:
        self._rx += (line + self.eol).encode("ascii", errors="replace")

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


def demo_drive(**kwargs):
    """An :class:`~parker_ar04ae.drive.AriesDrive` wired to a connected fake."""
    from .drive import AriesDrive

    return AriesDrive(byte_port=FakePort(DEMO_REPLIES), **kwargs).connect()
