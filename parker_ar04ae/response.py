"""Parsing of the drive's reply to a command."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Error tokens the drive returns in place of a value. Matched case-sensitively
#: after the leading ``*``. Extend via ``AriesDrive(error_tokens=...)``.
ERROR_TOKENS = frozenset(
    {
        "UNDEFINED_COMMAND",
        "INVALID_DATA",
        "INVALID_DATA_HIGH",
        "INVALID_DATA_LOW",
        "INVALID_CONDITIONS",
        "INCORRECT_DATA_TYPE",
        "MISSING_DATA",
        "DATA_OUT_OF_RANGE",
        "COMMAND_NOT_ALLOWED",
        "NO_MOTOR_SELECTED",
        "DRIVE_NOT_ENABLED",
        "DRIVE_ALREADY_ENABLED",
        "MOTION_IN_PROGRESS",
        "NOT_ALLOWED_IN_MOTION",
    }
)

#: An all-caps underscore-joined token after ``*`` is an error even if it is not
#: in ERROR_TOKENS. Value replies are either numeric or carry the command name
#: followed by a space, so they do not match this.
_ERROR_SHAPE = re.compile(r"^[A-Z]+(?:_[A-Z0-9]+)+$")


def looks_like_error(line: str, extra_tokens: frozenset[str] = frozenset()) -> bool:
    if not line.startswith("*"):
        return False
    body = line[1:].strip()
    return body in ERROR_TOKENS or body in extra_tokens or bool(_ERROR_SHAPE.match(body))


@dataclass
class Response:
    """The drive's reply to one command.

    ``lines`` holds the reply with the command echo and the ``>`` prompt already
    removed. Most commands answer with a single line; ``TSTAT`` answers with a
    page of them.
    """

    command: str
    lines: list[str] = field(default_factory=list)
    error_tokens: frozenset[str] = ERROR_TOKENS

    @property
    def text(self) -> str:
        """The whole reply as one newline-joined string."""
        return "\n".join(self.lines)

    @property
    def empty(self) -> bool:
        return not self.lines

    @property
    def is_error(self) -> bool:
        return any(looks_like_error(ln, self.error_tokens) for ln in self.lines)

    @property
    def error_code(self) -> str | None:
        for ln in self.lines:
            if looks_like_error(ln, self.error_tokens):
                return ln[1:].strip()
        return None

    @property
    def value(self) -> str:
        """The payload of a single-value reply.

        Strips the leading ``*`` and, when the drive echoes the command name
        back inside the reply (``*TREV 92-016966``), that name too.
        """
        if not self.lines:
            return ""
        line = self.lines[0]
        if line.startswith("*"):
            line = line[1:]
        head = self.command.split()[0].upper() if self.command else ""
        if head and line.upper().startswith(head):
            line = line[len(head):]
        return line.strip()

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
        """Status replies (``TAS``, ``TASX``, ``TER``) as a plain bit string.

        The drive groups the bits with underscores; they are removed here so
        that ``bit(n)`` indexes bit 1 at position 0, matching the manual's
        one-based bit numbering.
        """
        return "".join(c for c in self.value if c in "01")

    def bit(self, n: int) -> bool:
        """Bit ``n`` of a status reply, **one-based** as in the manual."""
        bits = self.as_bits()
        if not 1 <= n <= len(bits):
            raise IndexError(f"bit {n} out of range for {len(bits)}-bit status")
        return bits[n - 1] == "1"

    def __str__(self) -> str:
        return self.text
