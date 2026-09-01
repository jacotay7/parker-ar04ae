"""Serial control library for the Parker Hannifin ARIES AR-04AE servo drive."""

from .drive import BAUD_RATES, AriesDrive
from .errors import (
    AriesConnectionError,
    AriesError,
    AriesTimeoutError,
    CommandError,
)
from .response import Response
from .transport import BytePort, SerialPort, SerialTransport

__version__ = "0.1.0"

__all__ = [
    "AriesDrive",
    "BAUD_RATES",
    "AriesError",
    "AriesConnectionError",
    "AriesTimeoutError",
    "CommandError",
    "Response",
    "BytePort",
    "SerialPort",
    "SerialTransport",
    "__version__",
]
