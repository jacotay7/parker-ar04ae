"""Lookup tables transcribed from the Aries User Guide, Revision G
(88-021610-01G), Chapter 6 "Command Reference" and Chapter 7 "Troubleshooting".

Kept apart from :mod:`parker_ar04ae.drive` so the source of each fact is
obvious: everything here comes from the manual in ``manuals/``, whereas the
command wrappers were confirmed against hardware.

A caveat that matters: the manual documents Aries OS 1.0-3.10, and the drive
this library was developed against reports **OS 3.30**. Commands exist on that
firmware which appear nowhere in Rev G (``TAS``, ``TIN``, ``ERRLVL``), and
some documented commands may be absent. Treat these tables as the manual's
account, not as a guarantee about a particular unit.
"""

from __future__ import annotations

#: Maximum command line length, including spaces (Rev G, Table 41).
MAX_COMMAND_LENGTH = 32

#: ``DMODE`` drive control modes (Rev G, Table 44). Modes 6 and 7 exist only on
#: step-and-direction versions of the drive.
DRIVE_MODES: dict[int, tuple[str, str]] = {
    1: ("Autorun", "Rotates the motor at 1 rps/mps, current reduced by 10%"),
    2: ("Torque/Force Control", "Direct control of rotary torque or linear force"),
    3: ("Feedback Alignment", "Auto-configure for feedback setup"),
    4: ("Velocity Control", "Direct control of rotary or linear motor velocity"),
    6: ("Position Control", "5V differential (RS-422) step and direction"),
    7: ("Reversed Position Control", "Step and direction with reversed polarity"),
}

#: ``SFB`` feedback types. Availability varies by OS revision.
FEEDBACK_TYPES: dict[int, str] = {
    0: "unknown",
    1: "auto-detect (OS 2.10+); standard encoder (OS 1.0/2.0)",
    2: "standard encoder (OS 2.10+)",
    3: "resolver option (OS 3.10+)",
    5: "smart encoder (OS 2.10+)",
    6: "absolute encoder (reserved, OS 2.10+)",
}

#: Errors reported by ``ERROR`` (Rev G, Table 46). These are the conditions that
#: prevent the drive from enabling. The related command to investigate with is
#: named in parentheses in the manual and repeated here where given.
ERROR_CODES: dict[str, str] = {
    "E25": "Excessive command voltage at enable - voltage at ANI+ was too high "
           "when the drive was enabled (see FLTSTP)",
    "E26": "Drive faulted",
    "E27": "Bridge hardware fault - excessive current or a short on the H-bridge",
    "E28": "Bridge temperature fault - excessive current commanded "
           "(see DMTLIM, DIFOLD)",
    "E29": "Drive over-voltage - bus above 410 VDC (see TVBUS)",
    "E30": "Drive under-voltage - bus below 85 VDC, or over-aggressive "
           "acceleration/deceleration (see TVBUS)",
    "E31": "Bridge foldback - current limited to prevent overheating "
           "(warning only, see DIFOLD)",
    "E32": "Power regeneration fault - check the regeneration resistor for a short",
    "E34": "Drive temperature fault - wait for the drive to cool (see TDTEMP)",
    "E35": "Motor thermal model fault - the thermal model says the motor is too "
           "hot (see TMTEMP)",
    "E36": "Motor temperature fault - the motor thermal switch has tripped "
           "(see TMTEMP)",
    "E37": "Bad hall state - check the hall wiring (see THALL)",
    "E38": "Feedback failure - feedback absent or at the wrong level "
           "(see TPE, THALL)",
    "E39": "Drive disabled (see DRIVE)",
    "E40": "PWM not active - the H-bridge is not switching",
    "E41": "Power regeneration warning - the drive regenerated (warning only)",
    "E42": "Shaft power limited to the rated output to protect the drive "
           "(warning only)",
    "E43": "Excessive speed at enable - the motor was turning too fast",
    "E44": "Excessive position error - beyond the value set by SMPER",
    "E45": "Excessive velocity error - beyond the value set by SMVER",
    "E46": "No hardware enable - the hardware enable input (Drive I/O pins 1 "
           "and 21) is open",
    "E47": "Low voltage enable - no motor power was present when the drive was "
           "enabled",
    "E48": "Control power active - the drive is in control power mode, no motor "
           "power present",
    "E49": "Alignment error - the ALIGN command did not complete (see TPE, THALL)",
    "E50": "Flash error - a problem writing to non-volatile memory (see RFS)",
    "E51": "Resolver error - check the resolver feedback wiring (ARxx-xR only)",
    "E52": "Encoder loss fault - check the feedback wiring (see TPE, THALL)",
}

#: ``ERRORL`` / error-log condition bits (Rev G, Table 47), zero-based as the
#: manual numbers them here - note this differs from the one-based numbering
#: used for status words like ``TAS``.
ERROR_LOG_BITS: dict[int, str] = {
    0: "enable/disable (hardware enable input or DRIVE command)",
    1: "bridge fault",
    2: "no PWM output (H-bridge switching)",
    3: "over voltage (DC bus)",
    4: "under voltage (DC bus)",
    5: "startup voltage (analog command voltage)",
    6: "drive over temperature",
    7: "motor over temperature (thermal model)",
    8: "motor thermal switch",
    9: "feedback error",
    10: "hall error",
    11: "motor configuration error",
    12: "regeneration fault",
    13: "reserved",
    14: "reserved",
    15: "reserved",
}


def describe_error(code: str) -> str:
    """Describe an ``E``-code from :data:`ERROR_CODES`, e.g. ``E46``."""
    return ERROR_CODES.get(code.strip().upper(), "unrecognised error code")


def describe_drive_mode(mode: int) -> str:
    """Name a ``DMODE`` value, e.g. ``4`` -> ``Velocity Control``."""
    entry = DRIVE_MODES.get(mode)
    return entry[0] if entry else "unknown mode"


#: Modes in which the drive acts on the analog command input the moment it is
#: energised. In these, a non-zero reading on TANI means the motor will move on
#: enable, with no further command needed.
ANALOG_COMMAND_MODES = (2, 4)
