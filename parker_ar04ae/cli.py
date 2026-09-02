"""Command-line tools for bringing up and poking at an ARIES drive.

    python -m parker_ar04ae ports
    python -m parker_ar04ae probe
    python -m parker_ar04ae info    -p /dev/cu.usbserial-1420
    python -m parker_ar04ae term    -p /dev/cu.usbserial-1420
    python -m parker_ar04ae monitor -p /dev/cu.usbserial-1420
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from .drive import BAUD_RATES, PARAMETERS, AriesDrive
from .reference import DRIVE_MODES
from .errors import AriesError


#: Ports macOS always provides that are never a USB adapter.
BUILTIN_PORTS = ("Bluetooth-Incoming-Port", "debug-console")

#: Name fragments used by the common USB-serial bridge drivers. PL2303G parts
#: appear as ``cu.PL2303G-*``, Silicon Labs as ``cu.SLAB_USBtoUART``, CH34x as
#: ``cu.wchusbserial*`` - none of which contain "usbserial".
ADAPTER_HINTS = (
    "usbserial", "usbmodem", "pl2303", "slab_usbtouart",
    "wchusbserial", "ftdi", "usb-serial", "prolific",
)


def list_ports() -> list:
    try:
        from serial.tools import list_ports as lp
    except ImportError:
        print("pyserial is not installed; run: pip install pyserial", file=sys.stderr)
        return []
    return list(lp.comports())


def is_builtin(device: str) -> bool:
    return any(b in device for b in BUILTIN_PORTS)


def looks_like_adapter(device: str) -> bool:
    return any(h in device.lower() for h in ADAPTER_HINTS)


def cmd_ports(args) -> int:
    ports = list_ports()
    if not ports:
        print("No serial ports found.")
        print("Plug the RS-232 adapter in and check that its driver is loaded.")
        return 1
    for p in ports:
        tag = "  <- built in" if is_builtin(p.device) else ""
        print(f"{p.device:32} {p.description}{tag}")

    candidates = [p.device for p in ports if "cu." in p.device and not is_builtin(p.device)]
    likely = [d for d in candidates if looks_like_adapter(d)] or candidates
    if likely:
        print(f"\nLikely adapter: {likely[0]}")
    else:
        print("\nNo USB adapter found - only built-in ports are present.")
        print("The adapter may be plugged in but have no driver bound to it; see")
        print("the 'No serial port appears' section of the README.")
        return 1
    return 0


def _candidate_ports(explicit: str | None) -> list[str]:
    if explicit:
        return [explicit]
    ports = [p.device for p in list_ports() if "cu." in p.device and not is_builtin(p.device)]
    # Try the ones that look like a USB adapter first, but fall back to the rest.
    return sorted(ports, key=lambda d: not looks_like_adapter(d))


def cmd_probe(args) -> int:
    """Try each candidate port and baud rate until the drive answers TREV."""
    ports = _candidate_ports(args.port)
    if not ports:
        print("No candidate ports. Run `ports` first.")
        return 1
    bauds = [args.baud] if args.baud else list(BAUD_RATES)

    for port in ports:
        for baud in bauds:
            print(f"trying {port} @ {baud:>6} ... ", end="", flush=True)
            try:
                drive = AriesDrive(port, baudrate=baud, timeout=args.timeout)
                with drive:
                    resp = drive.raw("TREV", strict=False)
            except AriesError as exc:
                print(f"skip ({exc})")
                continue
            if resp.empty:
                print("no response")
                continue
            print("OK")
            print(f"\nDrive answered on {port} at {baud} baud:")
            for line in resp.lines:
                print(f"  {line}")
            print(f"\n  AriesDrive({port!r}, baudrate={baud})")
            return 0

    print("\nNothing answered. Things to check:")
    print("  - the drive is powered up")
    print("  - the adapter has a driver bound (see README: 'No serial port appears')")
    print("  - a null-modem vs straight-through RS-232 cable (try the other)")
    print("  - the drive's own baud rate setting")
    print("  - you are using the /dev/cu.* node, not /dev/tty.*")
    return 1


def cmd_info(args) -> int:
    """Read every known parameter and print it grouped."""
    groups = [args.group] if args.group else None
    with AriesDrive(args.port, baudrate=args.baud or 9600, timeout=args.timeout) as d:
        snap = d.snapshot(groups=groups)
    unsupported = []
    for group, entries in snap.items():
        print(f"\n[{group}]")
        for name, value in entries.items():
            cmd, _desc, source = PARAMETERS[group][name]
            tag = "" if source == "hw" else "  (manual only)"
            if value is None:
                unsupported.append(cmd)
                if args.all:
                    print(f"  {name:<24} {cmd:<8} -{tag}")
            else:
                print(f"  {name:<24} {cmd:<8} {value}{tag}")
    if unsupported:
        print(f"\nNot supported by this unit: {', '.join(unsupported)}")
    return 0


def cmd_monitor(args) -> int:
    """Poll position, velocity and torque until interrupted."""
    fields = [("position", "TPE"), ("velocity", "TVELA"), ("torque", "TTRQ"),
              ("pos.error", "TPER"), ("bus V", "TVBUS")]
    with AriesDrive(args.port, baudrate=args.baud or 9600, timeout=args.timeout) as d:
        print("  ".join(f"{label:>12}" for label, _ in fields) + "   (ctrl-C to stop)")
        try:
            while True:
                row = [d.raw(cmd, strict=False).value or "-" for _, cmd in fields]
                print("\r" + "  ".join(f"{v:>12}" for v in row), end="", flush=True)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print()
    return 0


def cmd_errors(args) -> int:
    """Show the drive's active errors, decoded."""
    with AriesDrive(args.port, baudrate=args.baud or 9600, timeout=args.timeout) as d:
        try:
            active = d.active_errors()
        except AriesError as exc:
            print(f"could not read ERROR: {exc}")
            return 1
        if not active:
            print("no active errors")
            return 0
        for code, desc in active:
            print(f"  {code}  {desc}")
    return 1


def cmd_status(args) -> int:
    """Print the STATUS full-text report, and the error log with --log."""
    with AriesDrive(args.port, baudrate=args.baud or 9600, timeout=args.timeout) as d:
        for line in d.raw("STATUS", timeout=4.0, strict=False).lines:
            print(f"  {line}")
        if args.log:
            print("\n--- error log (TERRLG) ---")
            for line in d.raw("TERRLG", timeout=5.0, strict=False).lines:
                print(f"  {line}")
    return 0


def cmd_check(args) -> int:
    """Pre-enable safety check: would enabling command motion right now?"""
    with AriesDrive(args.port, baudrate=args.baud or 9600, timeout=args.timeout) as d:
        print(f"  {d.revision()}")
        mode = d.raw("DMODE", strict=False)
        if not mode.empty:
            m = mode.as_int()
            print(f"  mode          DMODE{m} ({DRIVE_MODES.get(m, ('unknown',))[0]})")
        # DCMDZ is deliberately absent: sending it bare re-zeros the input.
        for label, cmd in [("analog input", "TANI"), ("deadband", "ANICDB"),
                           ("velocity scale", "DMVSCL"), ("enabled", "DRIVE"),
                           ("bus voltage", "TVBUS")]:
            r = d.raw(cmd, strict=False)
            print(f"  {label:<13} {r.value if not r.empty else '(not supported)'}")

        try:
            active = d.active_errors()
        except AriesError:
            active = None
        print("\n  active errors:")
        if active is None:
            print("    (ERROR not supported on this firmware)")
        elif not active:
            print("    none")
        else:
            for code, desc in active:
                print(f"    {code}  {desc}")

        try:
            will_move, why = d.will_move_on_enable()
        except AriesError as exc:
            print(f"\n  could not evaluate: {exc}")
            return 1
        print()
        if will_move:
            print(f"  UNSAFE TO ENABLE: {why}")
            print("  Zero the command input (short AIN+ to AIN-, then DCMDZ) first.")
            return 1
        print(f"  safe to enable: {why}")
    return 0


def cmd_term(args) -> int:
    """Type commands straight at the drive; blank line or ctrl-D to quit."""
    with AriesDrive(args.port, baudrate=args.baud or 9600, timeout=args.timeout,
                    strict=False) as d:
        print(f"Connected to {args.port}. Blank line or ctrl-D to quit.")
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                break
            resp = d.raw(line)
            if resp.empty:
                print("  (no response)")
            for out in resp.lines:
                print(f"  {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aries", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log serial traffic")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def with_port(p, port_required=True):
        p.add_argument("-p", "--port", required=port_required, help="e.g. /dev/cu.usbserial-1420")
        p.add_argument("-b", "--baud", type=int, help="default 9600")
        p.add_argument("-t", "--timeout", type=float, default=1.0)
        return p

    sub.add_parser("ports", help="list serial ports").set_defaults(func=cmd_ports)

    p = with_port(sub.add_parser("probe", help="find the drive's port and baud rate"), False)
    p.set_defaults(func=cmd_probe, timeout=0.6)

    p = with_port(sub.add_parser("info", help="read every known parameter"))
    p.add_argument("-g", "--group", choices=sorted(PARAMETERS), help="just one group")
    p.add_argument("--all", action="store_true", help="also list unsupported commands")
    p.set_defaults(func=cmd_info)

    p = with_port(sub.add_parser("monitor", help="poll position/velocity/torque"))
    p.add_argument("-i", "--interval", type=float, default=0.25)
    p.set_defaults(func=cmd_monitor)

    with_port(sub.add_parser("errors", help="show active errors, decoded")).set_defaults(func=cmd_errors)

    p = with_port(sub.add_parser("status", help="STATUS full-text report"))
    p.add_argument("--log", action="store_true", help="also print the TERRLG error log")
    p.set_defaults(func=cmd_status)

    with_port(sub.add_parser("check", help="pre-enable safety check")).set_defaults(func=cmd_check)

    with_port(sub.add_parser("term", help="interactive command terminal")).set_defaults(func=cmd_term)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return args.func(args)
    except AriesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
