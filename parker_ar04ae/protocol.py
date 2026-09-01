"""The ARIES serial protocol, as observed on an AR-04AE running Aries OS 3.30.

A command is sent as ASCII terminated by CR. The drive replies with:

    <echo of the command> CRLF        (when ECHO is 1, the factory default)
    [ DC1 CRLF ]                      (lead marker, seen on TREV)
    <value or message> CRLF           (zero or more lines)
    ENQ CRLF                          (end-of-response prompt)

For example ``TREV`` returns::

    b'TREV\\r\\n\\x11\\r\\nAries OS Revision 3.30\\r\\n\\x05\\r\\n'

ENQ (0x05) terminating every reply is what makes reads deterministic: the
transport can stop the moment it arrives instead of guessing from a silence
timeout. Values come back bare - there is no ``*`` prefix, and the command name
is not repeated in the reply.

Errors are plain text rather than a token::

    b'TASX\\r\\nERROR: Unknown Command\\r\\n\\x05\\r\\n'
"""

#: End-of-response prompt. Every reply ends with this byte.
ENQ = "\x05"

#: Lead marker preceding the payload on some replies (observed on TREV).
DC1 = "\x11"

#: Prefix identifying an error reply.
ERROR_PREFIX = "ERROR:"

#: Command terminator.
EOL = "\r"

#: Factory default line settings.
DEFAULT_BAUD = 9600
