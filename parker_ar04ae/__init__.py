"""Serial control library for the Parker Hannifin ARIES AR-04AE servo drive."""

from .drive import (
    BAUD_RATES,
    PARAMETER_COMMANDS,
    PARAMETERS,
    AriesDrive,
    VelocityMeasurement,
)
from .errors import (
    AriesConnectionError,
    AriesError,
    AriesTimeoutError,
    CommandError,
)
from .response import Response
from .transport import BytePort, SerialPort, SerialTransport

__version__ = "0.2.0"

__all__ = [
    "AriesDrive",
    "BAUD_RATES",
    "PARAMETERS",
    "PARAMETER_COMMANDS",
    "AriesError",
    "AriesConnectionError",
    "AriesTimeoutError",
    "CommandError",
    "Response",
    "VelocityMeasurement",
    "BytePort",
    "SerialPort",
    "SerialTransport",
    "__version__",
]
