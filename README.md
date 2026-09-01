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
python -m parker_ar04ae check   -p ...    # pre-enable safety check
python -m parker_ar04ae errors  -p ...    # active errors, decoded
python -m parker_ar04ae status  -p ... --log   # STATUS report, plus TERRLG
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

### Queries answer; writes do not

Sending a command bare reads it; appending a value writes it. The two behave
differently on the wire, which is the single most important thing to know here:

| | echoes | ENQ | reply |
| --- | --- | --- | --- |
| `SGI` (query) | ✅ | ✅ 0.02 s | `0.000` |
| `SGI0.1` (write) | ✅ | ❌ never | nothing |

**A write is never acknowledged.** It echoes and goes silent — no value, no ENQ, no
error even when the drive ignores it entirely. Two consequences the library handles
for you:

- Waiting for an ENQ after a write blocks for the full timeout. `raw()` treats a bare
  command as a query and one with arguments as a write; pass `expect_reply=False`
  explicitly for writes that carry the value in the name, like `DRIVE1`.
- A refused write is indistinguishable from an accepted one, so **the only way to
  confirm a write is to read it back**. `set()`, `enable()` and `disable()` do that
  and raise `VerificationError` if the value did not take.

```python
drive.set("gain_i", 0.1)      # writes SGI0.1, reads SGI back, returns '0.100'
drive.set("gain_i", 0.1, verify=False)   # fire and forget
```

Parameters are stored by the drive itself and **survive a reboot** — verified by
writing `ERRLVL3`, resetting, confirming the link actually dropped, and reading `3`
back. There is no save command to call.

```python
drive.reset()      # returns ~2.3 - seconds until the drive answered again
```

`reset()` waits for the link to both drop *and* recover, so you cannot read stale
values off a drive that has not finished rebooting.

## Command set

84 parameters in `PARAMETERS`, plus the text reports. Each is tagged by source:
**hw** = confirmed against an AR-04AE running Aries OS 3.30, **doc** = taken from the
Rev G manual in [manuals/](manuals/) but not yet seen on hardware. `info` marks the
manual-only ones, and `snapshot()` reports anything the firmware rejects as `None`
rather than failing.

| Group | Commands |
| --- | --- |
| identity | `TREV` `DMTR` `ADDR` `ECHO` `ERRLVL` |
| status | `DRIVE` `TAS` `TIN` `TOUT` |
| feedback | `TPE` `TPC` `TPER` `TVEL` `TVELA` `TTRQ` `TANI` · *doc:* `TVER` `TTRQA` `TCI` `THALL` |
| power | `TVBUS` `TDTEMP` `TMTEMP` · *doc:* `TDICNT` `TDIMAX` `TSSPD` |
| runtime | *doc:* `TDHRS` `TDMIN` `TDSEC` |
| drive config | `DMODE` `ERES` `DRES` `SFB` `DIFOLD` `DTHERM` `DPWM` · *doc:* `CMDDIR` `DMPSCL` `IANI` `ANICDB` `FLTDSB` `FLTSTP` `ENCFLT` `ENCOFF` `ENCPOL` `SHALL` `OHALL` `P163` |
| motor config | `DMTIC` `DMTLIM` `DMTW` `DMTKE` `DMTRES` `DMTIND` `DPOLE` `DMTJ` `DMTD` `DMEPIT` · *doc:* `DMTIP` `DMTINF` `DMTSCL` `DMVSCL` `DMVLIM` `DMTAMB` `DMTMAX` `DMTRWC` `DMTTCM` `DMTTCW` `DMTSWT` `DMTICD` |
| servo gains | `SGP` `SGI` `SGV` `SGVF` `SGAF` `SMPER` · *doc:* `SGILIM` `SMVER` `SMAV` `PGAIN` `IGAIN` `DIBW` `IAUTO` `LJRAT` |

Text reports: `ERROR`, `STATUS`, `TERRLG`, `CERRLG`, `CONFIG`.

```python
drive.active_errors()   # [('E46', 'No hardware enable - ... pins 1 and 21 - is open')]
drive.status()          # STATUS full-text report, as lines
drive.error_log()       # TERRLG - last ten errors or power cycles
drive.drive_mode_name() # 'Velocity Control'
drive.feedback_type()   # 'smart encoder (OS 2.10+)'
```

### Firmware is newer than the manual

Rev G documents Aries OS 1.0–3.10; this drive reports **OS 3.30**. That cuts both ways:
`TAS`, `TIN` and `ERRLVL` work on the drive but appear **nowhere** in Rev G, while
`TSTAT` — which I originally guessed at — does not exist. The manual's full-text
report is `STATUS`. Treat [reference.py](parker_ar04ae/reference.py) as the manual's
account, not a guarantee about a given unit.

### Command syntax

- Line limit is **32 characters**, enforced by `raw()`.
- Bare command reads; appending a value writes (`SGP2.0`).
- `DCMDZ` is the exception — it uses `=` (`DCMDZ=0.5`), so it has its own method,
  `zero_command_offset()`.
- On **RS-485** every response is prefixed `*` and units need an address
  (`2_TREV`); on RS-232 replies are bare. Set `address=` for a multi-drop network.

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
python -m pytest                          # 112 tests, no hardware needed
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
| [reference.py](parker_ar04ae/reference.py) | Lookup tables transcribed from the Rev G manual |
| [testing.py](parker_ar04ae/testing.py) | `FakePort`, `DEMO_REPLIES`, `demo_drive()` |
| [cli.py](parker_ar04ae/cli.py) | `ports` / `probe` / `info` / `term` / `monitor` |

## Why this drive will not enable

`DRIVE1` is accepted silently and `DRIVE` still reads `0`. The manual gives the check
and the answer:

> To verify the hardware enable input is open, query the ERROR command for
> **E46 – Hardware Enable**. `0 = Hardware Enable (Drive I/O Pin 1 and 21)`,
> `1 = No Hardware Enable`

So the hardware enable interlock across **Drive I/O pins 1 and 21** must be closed.
`enable()` now reports the drive's own reason rather than a guess:

```
VerificationError: 'DRIVE1' did not take effect: expected True, read back False.
the drive refused to enable: E46 No hardware enable - the hardware enable input
(Drive I/O pins 1 and 21) is open
```

Per the manual, if that input is closed at power-up the drive enables itself.

## The motor will move the moment it enables

`DMODE 4` is confirmed as **Velocity Control** — "direct control of rotary or linear
motor velocity". The drive acts on the analog command input as soon as it is
energised; there is no separate "go". With `TANI` sitting at a steady ~0.93 V, a zero
point of 0.00 V and a 0.04 V deadband, that is a live velocity command.

Check before energising:

```bash
python -m parker_ar04ae check -p /dev/cu.PL2303G-USBtoUART110
```

```
UNSAFE TO ENABLE: DMODE4 (Velocity Control): input is 0.940 V, 0.940 V from the
0.000 V zero point and outside the 0.040 V deadband - the motor will move on enable
```

The fix, from the `DCMDZ` entry: short **AIN+ to AIN-** on the DRIVE I/O connector (or
command 0 V from the controller), then call `zero_command_offset()` — bare `DCMDZ`
takes the present input voltage as the new zero.

`will_move_on_enable()` is a best-effort aid that reads three parameters over a serial
link. It is **not an interlock** and cannot see what the controller does next. Nothing
here substitutes for the hardware enable or an E-stop.

## Next session at the drive

In order:

1. `python -m parker_ar04ae info --all` — confirms which *doc* commands exist on
   OS 3.30. Anything showing `-` is absent.
2. `python -m parker_ar04ae status --log` — first look at `STATUS` and `TERRLG`.
   Neither has run against hardware.
3. `python -m parker_ar04ae errors` — expected to report `E46`, confirming the
   enable-input diagnosis.
4. Close the enable interlock across Drive I/O pins 1 and 21.
5. `python -m parker_ar04ae check` — must say *safe to enable* before going further.
   If not, zero the command input first.
6. Only then `enable()`, with the motor still free of any load.

## Still unconfirmed

- Every **doc**-tagged command above, and all the text reports — read from the manual,
  not yet seen on this firmware.
- **Motion.** Nothing has been commanded to move; the drive has never enabled.
- **Write coverage.** `ERRLVL` and `SGI` were written and restored. The mechanism is
  identical for the rest, but some parameters may be rejected while enabled, and
  several (`DRES`, `IANI`) are documented as requiring a reset to take effect.
