"""Exception hierarchy for the ARIES drive library."""


class AriesError(Exception):
    """Base class for every error raised by this library."""


class ConnectionError_(AriesError):
    """The serial port could not be opened, or was used while closed."""


class TimeoutError_(AriesError):
    """The drive did not answer within the read timeout."""

    def __init__(self, command: str, timeout: float, partial: str = ""):
        self.command = command
        self.timeout = timeout
        self.partial = partial
        msg = f"no response to {command!r} within {timeout:g}s"
        if partial:
            msg += f" (partial data: {partial!r})"
        super().__init__(msg)


class CommandError(AriesError):
    """The drive answered, but reported an error for the command we sent.

    ``code`` is the drive's error token with the leading ``*`` stripped, e.g.
    ``UNDEFINED_COMMAND`` or ``INVALID_DATA``.
    """

    def __init__(self, command: str, code: str, raw: str = ""):
        self.command = command
        self.code = code
        self.raw = raw
        super().__init__(f"{command!r} rejected by drive: {code}")


# Friendlier aliases that do not shadow the builtins inside this package.
AriesConnectionError = ConnectionError_
AriesTimeoutError = TimeoutError_
