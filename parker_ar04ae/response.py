"""Parsing of the drive's reply to a command."""

from __future__ import annotations

from dataclasses import dataclass, field

from .protocol import ERROR_PREFIX


def looks_like_error(line: str, prefix: str = ERROR_PREFIX) -> bool:
    """True if ``line`` is one of the drive's error messages.

    The firmware reports failures as plain text, e.g.
    ``ERROR: Unknown Command`` - not as a status token.
    """
    return line.strip().upper().startswith(prefix.upper())


@dataclass
class Response:
    """The drive's reply to one command.

    ``lines`` holds the reply with the command echo, the ENQ prompt and the DC1
    marker already removed. Most commands answer with a single value line.
    """

    command: str
    lines: list[str] = field(default_factory=list)
    error_prefix: str = ERROR_PREFIX

    @property
    def text(self) -> str:
        """The whole reply as one newline-joined string."""
        return "\n".join(self.lines)

    @property
    def empty(self) -> bool:
        return not self.lines

    @property
    def is_error(self) -> bool:
        return any(looks_like_error(ln, self.error_prefix) for ln in self.lines)

    @property
    def error_message(self) -> str | None:
        """The text after ``ERROR:``, e.g. ``Unknown Command``."""
        for ln in self.lines:
            if looks_like_error(ln, self.error_prefix):
                return ln.strip()[len(self.error_prefix):].strip()
        return None

    @property
    def value(self) -> str:
        """The payload of a single-value reply.

        The drive answers bare - no ``*`` prefix and no repetition of the
        command name - so this is simply the first reply line.
        """
        return self.lines[0] if self.lines else ""

    # -- typed accessors ---------------------------------------------------
    def as_int(self) -> int:
        return int(self.value.replace("+", "").strip())

    def as_float(self) -> float:
        return float(self.value.replace("+", "").strip())

    def as_bool(self) -> bool:
        v = self.value.strip()
        if v in ("1", "0"):
            return v == "1"
        raise ValueError(f"cannot read {v!r} as a boolean")

    def as_bits(self) -> str:
        """A status reply (``TAS``, ``TIN``, ``TOUT``) as a plain bit string.

        The drive groups the bits in fours with underscores
        (``0000_0000_0000_0011``); they are removed here so that :meth:`bit`
        can use the manual's one-based numbering.
        """
        return "".join(c for c in self.value if c in "01")

    def bit(self, n: int) -> bool:
        """Bit ``n`` of a status reply, **one-based** as in the manual."""
        bits = self.as_bits()
        if not 1 <= n <= len(bits):
            raise IndexError(f"bit {n} out of range for {len(bits)}-bit status")
        return bits[n - 1] == "1"

    def set_bits(self) -> list[int]:
        """The one-based positions of every bit that is set."""
        return [i + 1 for i, b in enumerate(self.as_bits()) if b == "1"]

    def __str__(self) -> str:
        return self.text
