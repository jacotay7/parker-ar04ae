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


#: Commands that *do something* when sent bare, rather than reporting a value.
#: Sending one as if it were a query changes the drive's state - ``DCMDZ`` with
#: no argument re-zeros the analog command input against whatever voltage
#: happens to be present, and its Response field in the manual is ``N/A``, so
#: there is no read-back form at all. :meth:`~parker_ar04ae.drive.AriesDrive.get`
#: and :meth:`~parker_ar04ae.drive.AriesDrive.snapshot` refuse these.
ACTION_COMMANDS: frozenset[str] = frozenset({
    "ALIGN",    # runs the encoder alignment procedure; turns the motor
    "CERRLG",   # clears the error log
    "DCMDZ",    # re-zeros the analog command input
    "ESTORE",   # writes motor data to the smart encoder
    "PSET",     # establishes absolute position
    "RESET",    # reboots the drive
    "RFS",      # returns the drive to factory settings
})

#: Modes in which the drive acts on the analog command input the moment it is
#: energised. In these, a non-zero reading on TANI means the motor will move on
#: enable, with no further command needed.
ANALOG_COMMAND_MODES = (2, 4)


# -- connector pinouts (Rev G, Chapter 3 "Electrical Installation") ---------
#
# Two separate connectors, and their pin numbers collide - pin 15 is AIN- on
# the DRIVE I/O connector but Thermal- on the MOTOR FEEDBACK connector. Always
# check which connector is meant.

#: 26-pin DRIVE I/O connector (Rev G, Table 29).
DRIVE_IO_PINOUT: dict[int, str] = {
    1: "ENABLE+ - drive enable input anode",
    2: "DGND - digital ground",
    3: "ENC A+ - encoder A channel out",
    4: "ENC A- - encoder A channel out",
    5: "ENC B+ - encoder B channel out",
    6: "ENC B- - encoder B channel out",
    7: "ENC Z+ - encoder Z channel out (index +)",
    8: "ENC Z- - encoder Z channel out (index -)",
    9: "FAULT+ - fault output collector",
    10: "STEP+ - 5V differential position command",
    11: "STEP- - position command return",
    12: "DIRECTION+ - 5V differential direction command",
    13: "DIRECTION- - direction command return",
    14: "AIN+ - analog +/-10V command",
    15: "AIN- - +/-10V return",
    16: "FAULT- - fault output emitter",
    17: "DGND - digital ground",
    18: "RESET+ - drive reset input anode",
    19: "DGND - digital ground",
    20: "DGND - digital ground",
    21: "ENABLE- - drive enable input cathode",
    22: "DGND - digital ground",
    23: "RESET- - drive reset input cathode",
    24: "DGND - digital ground",
    25: "RS-232 Rx / RS-485+ (half duplex)",
    26: "RS-232 Tx / RS-485- (half duplex)",
}

#: 15-pin MOTOR FEEDBACK connector, encoder version (Rev G, Table 24). The
#: resolver option uses a different map - see :data:`MOTOR_FEEDBACK_RESOLVER`.
MOTOR_FEEDBACK_PINOUT: dict[int, str] = {
    1: "ENC Z+ / Data+ - encoder Z channel in",
    2: "ENC Z- / Data- - encoder Z channel in",
    3: "DGND - encoder power return",
    4: "+5 VDC - encoder power",
    5: "+5 VDC - hall power",
    6: "DGND - hall power return",
    7: "ENC A- / SIN- - encoder A channel in",
    8: "ENC A+ / SIN+ - encoder A channel in",
    9: "Hall 1 / SCLK+ - hall 1 input",
    10: "Thermal+ - motor thermal switch/thermistor",
    11: "ENC B- / COS- - encoder B channel in",
    12: "ENC B+ / COS+ - encoder B channel in",
    13: "Hall 2 / SCLK- - hall 2 input",
    14: "Hall 3 - hall 3 input",
    15: "Thermal- - motor thermal switch/thermistor",
}

#: 15-pin MOTOR FEEDBACK connector, resolver option (Rev G, Table 26). Note
#: Thermal- moves to pins 3 and 6, and pin 15 becomes Reference-.
MOTOR_FEEDBACK_RESOLVER: dict[int, str] = {
    3: "Thermal- - motor thermal switch/thermistor",
    4: "Reference+ - resolver excitation",
    6: "Thermal- - motor thermal switch/thermistor",
    7: "SIN- - resolver feedback",
    8: "SIN+ - resolver feedback",
    10: "Thermal+ - motor thermal switch/thermistor",
    11: "COS- - resolver feedback",
    12: "COS+ - resolver feedback",
    15: "Reference- - resolver excitation",
}

#: Electrical limits for the ENABLE and RESET inputs (Rev G, Table 30).
#:
#: These are **opto-isolated LED inputs, not dry contacts**: the anode and
#: cathode are on separate pins and current has to flow through them. Simply
#: jumpering ENABLE+ to ENABLE- shorts the LED and does nothing. Current is
#: limited internally, so 5-24 V logic can drive the pins directly with no
#: external resistor.
ENABLE_INPUT_SPEC: dict[str, str] = {
    "type": "optically isolated, anode and cathode on separate pins",
    "logic": "5 to 24 V, current limited internally",
    "guaranteed_on": ">= 4 VDC",
    "guaranteed_off": "<= 2 VDC",
    "forward_current": "3 to 12 mA",
    "max_forward_voltage": "30 VDC",
    "max_reverse_voltage": "-30 VDC",
    "switching_time": "1 ms on, 1 ms off",
}

#: Motor thermal switch input limits (Rev G, Table 25).
THERMAL_INPUT_SPEC: dict[str, str] = {
    "current": "2 mA",
    "max_supplied_voltage": "15 V",
    "pins": "MOTOR FEEDBACK 10 (Thermal+) and 15 (Thermal-), encoder version",
}
