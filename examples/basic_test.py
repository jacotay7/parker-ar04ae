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

QUERIES = [
    ("revision", "TREV"),
    ("motor", "DMTR"),
    ("drive mode", "DMODE"),
    ("encoder res.", "ERES"),
    ("enabled", "DRIVE"),
    ("axis status", "TAS"),
    ("ext. status", "TASX"),
    ("error status", "TER"),
    ("position", "TPE"),
    ("velocity", "TVEL"),
    ("current", "TCMD"),
    ("temperature", "TDTEMP"),
]


def run(drive) -> int:
    print("== link ==")
    if not drive.ping():
        print("  drive did not answer. Check power, cable and baud rate,")
        print("  or run: python -m parker_ar04ae probe")
        return 1
    print("  drive is answering\n")

    print("== queries ==")
    unsupported = []
    for label, cmd in QUERIES:
        resp = drive.raw(cmd, strict=False)
        if resp.empty:
            print(f"  {label:<14} (no response)")
        elif resp.is_error:
            print(f"  {label:<14} {resp.error_code}")
            unsupported.append(cmd)
        else:
            print(f"  {label:<14} {resp.value}")

    print("\n== fault check ==")
    ter = drive.raw("TER", strict=False)
    if ter.empty or ter.is_error:
        print("  TER unavailable, cannot judge fault state")
    elif "1" in ter.as_bits():
        bits = [i + 1 for i, b in enumerate(ter.as_bits()) if b == "1"]
        print(f"  FAULT: TER bits set: {bits}")
    else:
        print("  no faults reported")

    if unsupported:
        print(f"\nNot recognised by this unit: {', '.join(unsupported)}")
        print("Cross-check those against the manual for your firmware revision.")
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
