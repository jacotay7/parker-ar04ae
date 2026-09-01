"""In-memory fakes, so the library can be exercised with no hardware attached.

    from parker_ar04ae import AriesDrive
    from parker_ar04ae.testing import FakePort

    port = FakePort({"TREV": "*TREV 92-016966-01-5"})
    drive = AriesDrive(byte_port=port).connect()
    drive.revision()
"""

from __future__ import annotations

from typing import Callable, Mapping, Union

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
    default:
        Reply for an unknown command; ``*UNDEFINED_COMMAND`` as the real drive
        does. Pass ``""`` to model a dead or wrongly-wired link, where nothing
        comes back at all.
    echo:
        Prepend the received command to its reply, imitating the drive's
        full-duplex echo.
    eol:
        Terminator appended to each response line.
    """

    def __init__(
        self,
        replies: Mapping[str, Reply] | None = None,
        echo: bool = True,
        eol: str = "\r\n",
        default: Reply = "*UNDEFINED_COMMAND",
    ):
        self.replies = dict(replies or {})
        self.echo = echo
        self.default = default
        self.eol = eol
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

    def _emit(self, line: str) -> None:
        self._rx += (line + self.eol).encode("ascii", errors="replace")

    def __repr__(self) -> str:
        return f"<FakePort {len(self.replies)} replies, {len(self.written)} received>"


#: Plausible replies for the common queries, for smoke-testing offline. The
#: exact text a real drive returns will differ; do not assert on these values
#: when checking against hardware.
DEMO_REPLIES: dict[str, Reply] = {
    "TREV": "*TREV 92-016966-01-5_D1.0 ARIES",
    "TAS": "*TAS0000_0000_0000_0000_0000_0000_0000_0000",
    "TASX": "*TASX0000_0000_0000_0000",
    "TER": "*TER0000_0000_0000_0000",
    "TPE": "*TPE+0",
    "TPC": "*TPC+0",
    "TPER": "*TPER+0",
    "TVEL": "*TVEL+0.0000",
    "TCMD": "*TCMD+0.000",
    "TDTEMP": "*TDTEMP32.0",
    "TANI": "*TANI+0.000",
    "DRIVE": "*DRIVE0",
    "DRIVE1": "",
    "DRIVE0": "",
    "DMTR": "*DMTRBE231FJ",
    "DMODE": "*DMODE1",
    "ERES": "*ERES4000",
    "TSTAT": [
        "*ARIES SERVO DRIVE",
        "*TREV 92-016966-01-5_D1.0",
        "*MOTOR: BE231FJ",
        "*DRIVE: DISABLED",
        "*POSITION: +0",
    ],
}


def demo_drive(**kwargs):
    """An :class:`~parker_ar04ae.drive.AriesDrive` wired to a connected fake."""
    from .drive import AriesDrive

    return AriesDrive(byte_port=FakePort(DEMO_REPLIES), **kwargs).connect()
