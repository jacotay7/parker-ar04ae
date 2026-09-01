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

    ``message`` is the drive's text with the ``ERROR:`` prefix stripped, e.g.
    ``Unknown Command``.
    """

    def __init__(self, command: str, message: str, raw: str = ""):
        self.command = command
        self.message = message
        self.raw = raw
        super().__init__(f"{command!r} rejected by drive: {message}")


# Friendlier aliases that do not shadow the builtins inside this package.
AriesConnectionError = ConnectionError_
AriesTimeoutError = TimeoutError_
