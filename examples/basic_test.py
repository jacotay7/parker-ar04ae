#!/usr/bin/env python3
"""Bring-up check for an ARIES drive over RS-232.

Read-only: it queries the drive and prints what comes back. Nothing here
enables the drive or commands motion.

    python examples/basic_test.py /dev/cu.usbserial-1420
    python examples/basic_test.py --demo          # no hardware needed

Find the port first with `python -m parker_ar04ae ports`.
"""

import argparse
import sys

from parker_ar04ae import AriesDrive, AriesError

def run(drive) -> int:
    print("== link ==")
    if not drive.ping():
        print("  drive did not answer. Check power, cable and baud rate,")
        print("  or run: python -m parker_ar04ae probe")
        return 1
    print(f"  {drive.revision()}\n")

    print("== live readings ==")
    for label, getter in [
        ("bus voltage", lambda: f"{drive.bus_voltage():.1f} V"),
        ("drive temp", lambda: f"{drive.drive_temperature():.2f} C"),
        ("motor temp", lambda: f"{drive.motor_temperature():.2f} C"),
        ("motor", drive.motor),
        ("mode", lambda: f"DMODE{drive.drive_mode()} ({drive.drive_mode_name()})"),
        ("feedback", drive.feedback_type),
        ("enabled", lambda: "yes" if drive.is_enabled() else "no"),
        ("position", lambda: f"{drive.position()} counts"),
        ("following err", lambda: f"{drive.position_error()} counts"),
        ("velocity", lambda: f"{drive.actual_velocity():.3f}"),
        ("torque", lambda: f"{drive.torque():.3f}"),
        ("analog in", lambda: f"{drive.analog_input():.3f} V"),
    ]:
        try:
            print(f"  {label:<14} {getter()}")
        except AriesError as exc:
            print(f"  {label:<14} unavailable ({exc})")

    print("\n== status bits ==")
    for label, resp in [
        ("axis (TAS)", drive.axis_status()),
        ("inputs (TIN)", drive.input_states()),
        ("outputs (TOUT)", drive.output_states()),
    ]:
        bits = resp.set_bits()
        print(f"  {label:<14} {resp.value}   set: {bits or 'none'}")

    print("\n== configuration ==")
    snap = drive.snapshot(groups=["drive_config", "motor_config", "servo_gains"])
    for group, entries in snap.items():
        print(f"  [{group}]")
        for name, value in entries.items():
            if value is not None:
                print(f"    {name:<20} {value}")

    print("\n== active errors ==")
    try:
        active = drive.active_errors()
        if not active:
            print("  none")
        for code, desc in active:
            print(f"  {code}  {desc}")
    except AriesError as exc:
        print(f"  ERROR command unavailable ({exc})")

    print("\n== safe to enable? ==")
    try:
        will_move, why = drive.will_move_on_enable()
        print(f"  {'NO - ' if will_move else 'yes - '}{why}")
        if will_move:
            print("  Short AIN+ to AIN- on the DRIVE I/O connector and run DCMDZ")
            print("  to zero the command input before enabling.")
    except AriesError as exc:
        print(f"  could not evaluate ({exc})")

    print("\nRead-only check complete. Nothing was enabled or commanded to move.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("port", nargs="?", help="e.g. /dev/cu.usbserial-1420")
    ap.add_argument("-b", "--baud", type=int, default=9600)
    ap.add_argument("--demo", action="store_true", help="run against the in-memory fake")
    args = ap.parse_args()

    if args.demo:
        from parker_ar04ae.testing import demo_drive

        print("(demo mode: replies come from a fake, not from hardware)\n")
        return run(demo_drive())

    if not args.port:
        ap.error("give a port, or --demo")

    try:
        with AriesDrive(args.port, baudrate=args.baud) as drive:
            return run(drive)
    except AriesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
