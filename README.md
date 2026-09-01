# parker-ar04ae

Python control library for the **Parker Hannifin ARIES AR-04AE** servo drive over RS-232.

A thin, typed wrapper around the serial link: it owns the framing, turns replies into
parsed values, and raises on the drive's error messages. Command methods are named
wrappers over that; anything not wrapped can still be sent with `raw()`.

Verified end to end against an AR-04AE running **Aries OS 3.30** on macOS.

## Install

```bash
python -m pip install -e .        # pulls in pyserial
python -m pip install pytest      # for the test suite
```

## macOS setup

The full path that worked, start to finish. Steps 2–4 are one-time.

**1. Wiring.** Mac USB-C → USB-A → USB/RS-232 adapter → the drive's RS-232 port.
9600 baud, 8N1, no flow control.

**2. Check the adapter enumerates.**

```bash
ioreg -p IOUSB -w0 -l | grep -iE '"USB (Product|Vendor) Name"|idVendor|idProduct'
```

Ours reported `USB-Serial Controller` / `Prolific Technology Inc.`, `idVendor 1659`
(`0x067B`), `idProduct 9123` (`0x23A3`) — a **PL2303GC**, a current G-series part.

**3. Install the driver.** macOS ships drivers for FTDI and USB CDC-ACM devices only.
The Prolific **PL2303** and WCH **CH340/CH341** bridges are vendor-specific USB
devices, so nothing built in claims them and no `/dev/cu.*` node is created. Install
[PL2303 Serial](https://apps.apple.com/us/app/pl2303-serial/id1624835354?mt=12) from
the Mac App Store.

**4. Approve the driver extension.** Installing is not enough, and this is the step
that is easy to miss. Open `/Applications/PL2303Serial.app` once, then:

```bash
open "x-apple.systempreferences:com.apple.LoginItems-Settings.extension"
```

Under **Driver Extensions**, toggle the Prolific entry on and authenticate. Then
replug the adapter. Verify:

```bash
systemextensionsctl list
```

```
enabled  active  teamID      bundleID                              [state]
   *       *     2MP849R8J5  com.prolific.cdc.PLCdcFSDriver        [activated enabled]
```

Before approval it reads `[activated waiting for user]` with a **blank `enabled`
column** — that is the symptom. Some Macs need a reboot for the toggle to take effect.

**5. Confirm the port.**

```bash
python -m parker_ar04ae ports
```

```
/dev/cu.PL2303G-USBtoUART10      USB-Serial Controller
```

Note the name: the driver uses its own prefix, **not** `/dev/cu.usbserial-*`. Use the
`/dev/cu.*` node, never `/dev/tty.*` — `tty.*` blocks on open waiting for carrier
detect, which an adapter without full handshaking never asserts.

**6. Talk to the drive.**

```bash
python -m parker_ar04ae probe
```

### If no port appears

```bash
ioreg -rc IOSerialBSDClient -w0 | grep IOCalloutDevice   # ports that exist
ls /Library/DriverExtensions                             # installed dexts
```

Only `debug-console` and `Bluetooth-Incoming-Port` means no driver is bound. If the
adapter shows under step 2 but not here, it is enumerating and only the driver is
missing — go back to steps 3 and 4.

Older `0x067B`/`0x2303` chips are a different case: many are counterfeit PL2303HXA/XA
parts that Prolific's driver deliberately refuses to bind to. There the practical fix
is a different adapter — an FTDI FT232 works with no driver install at all.

## Bring-up

```bash
python -m parker_ar04ae ports             # what serial devices exist
python -m parker_ar04ae probe             # sweep ports x baud rates until TREV answers
python -m parker_ar04ae info    -p /dev/cu.PL2303G-USBtoUART10
python -m parker_ar04ae info    -p ... -g servo_gains      # one group
python -m parker_ar04ae info    -p ... --all               # include unsupported commands
python -m parker_ar04ae monitor -p ...    # poll position/velocity/torque
python -m parker_ar04ae term    -p ...    # type commands directly
```

Add `-v` to any of them to log the raw bytes. `probe` prints the exact
`AriesDrive(...)` call to use.

## Library use

```python
from parker_ar04ae import AriesDrive

with AriesDrive("/dev/cu.PL2303G-USBtoUART10") as drive:
    print(drive.revision())          # 'Aries OS Revision 3.30'
    print(drive.bus_voltage())       # 162.6
    print(drive.drive_temperature()) # 33.04
    print(drive.position())          # 0
    print(drive.is_enabled())        # False

    status = drive.axis_status()     # TAS
    print(status.value)              # '0000_0000_0000_0000'
    print(status.set_bits())         # [] - one-based, as the manual numbers them
    print(status.bit(3))             # False
```

Parameters are also reachable by name, and `snapshot()` reads everything at once:

```python
drive.get("gain_p").as_float()       # 2.0
drive.set("gain_p", 2.5)             # sends SGP2.5
drive.snapshot(groups=["power"])     # {'power': {'bus_voltage': '162.6', ...}}
```

Errors surface as exceptions by default:

```python
from parker_ar04ae import CommandError

try:
    drive.raw("TASX")
except CommandError as exc:
    print(exc.message)               # 'Unknown Command'

drive.raw("TASX", strict=False).is_error   # or handle it inline
```

Daisy-chained units take an address, which prefixes every command as `2_TREV`:

```python
AriesDrive("/dev/cu.PL2303G-USBtoUART10", address=2)
```

## The wire protocol

Captured from the drive, and the reason the framing looks the way it does:

```
>>> TREV\r
<<< b'TREV\r\n\x11\r\nAries OS Revision 3.30\r\n\x05\r\n'
     |____|      |______________________|      |
     echo         value                        ENQ = end of response
```

- Commands are ASCII terminated by **CR**; the drive echoes them back (`ECHO` is 1).
- **ENQ (0x05)** ends every reply. Reads stop there, so they are deterministic and
  fast rather than waiting out a silence timeout. **DC1 (0x11)** appears as a lead
  marker on some replies. Both are stripped.
- Values come back **bare** — no `*` prefix, and the command name is not repeated.
- Errors are plain text: `ERROR: Unknown Command`.
- Software flow control must stay **off**, or pyserial would consume the DC1/ENQ
  markers as XON/XOFF.

Sending a command bare reads it (`SGP` → `2.000`); appending a value writes it
(`SGP2.5`).

## Verified command set

Everything in `PARAMETERS` was confirmed against Aries OS 3.30. `python -m
parker_ar04ae info` reads the lot.

| Group | Commands |
| --- | --- |
| identity | `TREV` `DMTR` `ADDR` `ECHO` `ERRLVL` |
| status | `DRIVE` `TAS` `TIN` `TOUT` |
| feedback | `TPE` `TPC` `TPER` `TVEL` `TVELA` `TTRQ` `TANI` |
| power | `TVBUS` `TDTEMP` `TMTEMP` |
| drive config | `DMODE` `ERES` `DRES` `DIFOLD` `DTHERM` `DPWM` |
| motor config | `DMTIC` `DMTLIM` `DMTW` `DMTKE` `DMTRES` `DMTIND` `DPOLE` `DMTJ` `DMTD` `DMEPIT` |
| servo gains | `SGP` `SGI` `SGV` `SGVF` `SGAF` `SFB` `SMPER` |

**Not present on this firmware** (they return `ERROR: Unknown Command`): `TSTAT`,
`TASX`, `TER`, `TCMD`, `TFB`, `HELP`, `?`. There is no command that enumerates the
command set, and no dedicated fault-status query was found — fault state appears to
live in the `TAS` bits.

## Testing without hardware

`parker_ar04ae.testing.FakePort` reproduces the real wire format — echo, DC1, ENQ —
so the whole stack above the wire runs offline:

```python
from parker_ar04ae import AriesDrive
from parker_ar04ae.testing import FakePort

port = FakePort({"TREV": "Aries OS Revision 3.30"})
drive = AriesDrive(byte_port=port).connect()
assert drive.revision() == "Aries OS Revision 3.30"
assert port.written == ["TREV"]        # what actually went on the wire
```

`DEMO_REPLIES` holds values captured from the real drive.

```bash
python -m pytest                          # 71 tests, no hardware needed
python examples/basic_test.py --demo      # the bring-up script against the fake
python examples/basic_test.py /dev/cu.PL2303G-USBtoUART10
```

## Layout

| File | Role |
| --- | --- |
| [protocol.py](parker_ar04ae/protocol.py) | The wire format, documented in one place |
| [transport.py](parker_ar04ae/transport.py) | `BytePort` (pyserial / fake) and `SerialTransport` framing |
| [response.py](parker_ar04ae/response.py) | Reply parsing: values, typed accessors, status bits, errors |
| [drive.py](parker_ar04ae/drive.py) | `AriesDrive` and the `PARAMETERS` registry |
| [testing.py](parker_ar04ae/testing.py) | `FakePort`, `DEMO_REPLIES`, `demo_drive()` |
| [cli.py](parker_ar04ae/cli.py) | `ports` / `probe` / `info` / `term` / `monitor` |

## Caveats

- **Only reads have been exercised.** Every query above was run against the drive.
  Writes (`set()`, `enable()`, `disable()`, `reset()`) are implemented from the same
  documented syntax but were not run. Verify with `get()` after writing.
- **Persistence is unconfirmed.** No save-to-NVRAM command is wrapped, because the
  mechanism was not established. Check whether a changed parameter survives a power
  cycle before relying on it.
- **No motion commands are wrapped.** The AR-04AE is the drive-only ARIES variant: it
  follows step/direction or ±10 V analog command from an external controller, and
  RS-232 is for configuration and diagnostics. This unit reports `DMODE 4`.
- `enable()` energises the motor and it will hold position — make sure the axis is
  clear first. Nothing here is a safety function or a substitute for the hardware
  enable or an E-stop circuit.
