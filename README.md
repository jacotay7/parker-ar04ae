# parker-ar04ae

Python control library for the **Parker Hannifin ARIES AR-04AE** servo drive over RS-232.

A thin, typed wrapper around the serial link: it owns the framing (CR terminators,
command echo, the `>` prompt, multi-line reports), turns replies into parsed values,
and raises on the drive's error tokens. Command methods are named wrappers over that;
anything not wrapped can still be sent with `raw()`.

## Install

```bash
python -m pip install -e .        # pulls in pyserial
python -m pip install pytest      # for the test suite
```

## Hardware path

Mac USB-C → USB-A → USB/RS-232 adapter → the drive's RS-232 port.

Use the **`/dev/cu.*`** device node, not `/dev/tty.*` — `tty.*` blocks on open
waiting for carrier detect, which an adapter without full handshaking never asserts.

Defaults are 9600 baud, 8N1, no flow control. If the drive stays silent, the usual
culprit is a straight-through cable where a null-modem is needed (or vice versa).

### No serial port appears

`ports` listing only `debug-console` and `Bluetooth-Incoming-Port` means the adapter
has no driver bound to it. Check whether macOS sees the USB device at all:

```bash
ioreg -p IOUSB -w0 -l | grep -iE '"USB (Product|Vendor) Name"|idVendor|idProduct'
ioreg -rc IOSerialBSDClient -w0 | grep IOCalloutDevice    # ports that do exist
```

If the adapter shows up in the first command but not the second, the device is
enumerating and only the driver is missing.

macOS ships drivers for FTDI and USB CDC-ACM devices only. The common Prolific
**PL2303** and WCH **CH340/CH341** bridges are vendor-specific USB devices, so
nothing built in claims them and no `/dev/cu.*` node is created. Prolific's current
G-series parts (`0x067B`/`0x23A3` = PL2303GC, and siblings `0x23B3`…`0x23F3`) need
[PL2303 Serial](https://apps.apple.com/us/app/pl2303-serial/id1624835354?mt=12) from
the Mac App Store — a DriverKit extension. After installing, **open the app once and
approve the extension** in System Settings → General → Login Items & Extensions →
Driver Extensions, then replug.

The port then appears under the driver's own name, e.g. `/dev/cu.PL2303G-USBtoUART110`
— not `/dev/cu.usbserial-*`. `ports` and `probe` recognise the naming used by all the
common bridge drivers.

Older `0x067B`/`0x2303` chips are a different situation: many are counterfeit PL2303HXA
or XA parts that Prolific's current driver deliberately refuses to bind to. If you have
one of those, the practical fix is a different adapter — an FTDI FT232-based one works
with no driver install at all.

## Bring-up

```bash
python -m parker_ar04ae ports            # what serial devices exist
python -m parker_ar04ae probe            # sweep ports x baud rates until TREV answers
python -m parker_ar04ae info -p /dev/cu.usbserial-1420
python -m parker_ar04ae info -p /dev/cu.usbserial-1420 --stat   # full TSTAT page
python -m parker_ar04ae term -p /dev/cu.usbserial-1420          # type commands directly
python -m parker_ar04ae monitor -p /dev/cu.usbserial-1420       # poll position/velocity
python -m parker_ar04ae probe -v         # add -v anywhere to log the raw bytes
```

`probe` is the one to start with — it reports the exact `AriesDrive(...)` call to use.

## Library use

```python
from parker_ar04ae import AriesDrive

with AriesDrive("/dev/cu.usbserial-1420") as drive:
    print(drive.revision())            # TREV
    print(drive.position())            # TPE, as an int
    print(drive.velocity())            # TVEL, as a float
    print(drive.drive_fault())         # any TER bit set?

    status = drive.axis_status()       # TAS
    print(status.as_bits())            # '0000...' with the underscores removed
    print(status.bit(1))               # bit numbering matches the manual (1-based)

    drive.raw("DMTR", "BE231FJ")       # -> DMTRBE231FJ
    drive.raw("SOMECMD", 42)           # anything not wrapped
```

Errors surface as exceptions by default:

```python
from parker_ar04ae import CommandError

try:
    drive.raw("NOSUCHCOMMAND")
except CommandError as exc:
    print(exc.code)                    # 'UNDEFINED_COMMAND'

drive.raw("NOSUCHCOMMAND", strict=False).is_error   # or handle it inline
```

Daisy-chained units take an address, which prefixes every command as `2_TREV`:

```python
AriesDrive("/dev/cu.usbserial-1420", address=2)
```

## Testing without hardware

`parker_ar04ae.testing.FakePort` answers from a lookup table, so the whole stack
above the wire runs offline:

```python
from parker_ar04ae import AriesDrive
from parker_ar04ae.testing import FakePort

port = FakePort({"TREV": "*TREV 92-016966-01-5"})
drive = AriesDrive(byte_port=port).connect()
assert drive.revision() == "92-016966-01-5"
assert port.written == ["TREV"]        # what actually went on the wire
```

```bash
python -m pytest                          # 58 tests, no hardware needed
python examples/basic_test.py --demo      # the bring-up script against the fake
```

## Layout

| File | Role |
| --- | --- |
| [transport.py](parker_ar04ae/transport.py) | `BytePort` (pyserial / fake) and `SerialTransport` line framing |
| [response.py](parker_ar04ae/response.py) | Reply parsing: values, typed accessors, status bits, error detection |
| [drive.py](parker_ar04ae/drive.py) | `AriesDrive` — the command wrappers |
| [testing.py](parker_ar04ae/testing.py) | `FakePort`, `demo_drive()` |
| [cli.py](parker_ar04ae/cli.py) | `ports` / `probe` / `info` / `term` / `monitor` |

## Status — verify the command set against your manual

The transport, parsing and error handling are exercised by the test suite. **The
command names themselves are not yet confirmed against hardware**, and are drawn
from the Parker ARIES/Gemini serial command set. Before relying on any wrapper,
check it against the manual for your unit and firmware revision — `term` and
`info` will show you quickly which commands your drive actually recognises
(unsupported ones answer `*UNDEFINED_COMMAND`).

Two specifics worth confirming:

- **The AR-04AE is the drive-only ARIES variant.** It follows step/direction or
  ±10 V analog command from an external controller; RS-232 is for configuration and
  diagnostics. The motion methods (`go`, `home`, `set_distance`, …) belong to the
  ARIES *Controller* (AR-xxCE) and are expected to return `*UNDEFINED_COMMAND`
  here. They are included so a CE unit works with the same class, and are marked
  as such in their docstrings.
- **Configuration persistence.** No "save to NVRAM" command is wrapped, because
  the mechanism is not confirmed. Check how your unit stores parameters before
  assuming a `DMTR`/`ERES` change survives a power cycle.

`enable()` energises the motor and it will hold position — make sure the axis is
clear first. `kill()` is a motion abort, not a safety function; it is not a
substitute for the hardware enable or an E-stop circuit.
