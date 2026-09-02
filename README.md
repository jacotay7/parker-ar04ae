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

84 parameters in `PARAMETERS`, plus the text reports. **All 84 read back on Aries OS
3.30** — every command taken from the Rev G manual was confirmed present on hardware.

| Group | Commands |
| --- | --- |
| identity | `TREV` `DMTR` `ADDR` `ECHO` `ERRLVL` |
| status | `DRIVE` `TAS` `TIN` `TOUT` |
| feedback | `TPE` `TPC` `TPER` `TVEL` `TVELA` `TVER` `TTRQ` `TTRQA` `TCI` `TANI` `THALL` |
| power | `TVBUS` `TDTEMP` `TMTEMP` `TDICNT` `TDIMAX` `TSSPD` |
| runtime | `TDHRS` `TDMIN` `TDSEC` |
| drive config | `DMODE` `ERES` `DRES` `SFB` `DIFOLD` `DTHERM` `DPWM` `CMDDIR` `DMPSCL` `IANI` `ANICDB` `FLTDSB` `FLTSTP` `ENCFLT` `ENCOFF` `ENCPOL` `SHALL` `OHALL` `P163` |
| motor config | `DMTIC` `DMTLIM` `DMTIP` `DMTW` `DMTKE` `DMTRES` `DMTIND` `DMTINF` `DPOLE` `DMTJ` `DMTD` `DMEPIT` `DMTSCL` `DMVSCL` `DMVLIM` `DMTAMB` `DMTMAX` `DMTRWC` `DMTTCM` `DMTTCW` `DMTSWT` `DMTICD` |
| servo gains | `SGP` `SGI` `SGV` `SGVF` `SGAF` `SGILIM` `SMPER` `SMVER` `SMAV` `PGAIN` `IGAIN` `DIBW` `IAUTO` `LJRAT` |

Text reports, all confirmed: `ERROR`, `STATUS`, `TERRLG`, `CERRLG`, `CONFIG`.

```python
drive.active_errors()   # [('E39', 'Drive disabled...'), ('E46', 'No hardware enable...')]
drive.status()          # STATUS full-text report, as lines
drive.error_log()       # TERRLG - last ten errors or power cycles
drive.drive_mode_name() # 'Velocity Control'
drive.feedback_type()   # 'standard encoder (OS 2.10+)'
```

### Commands that act when sent bare

Most commands report a value when sent with no argument. A few **do something
instead**, and reading them as if they were parameters changes the drive:

`ALIGN` · `CERRLG` · `DCMDZ` · `ESTORE` · `PSET` · `RESET` · `RFS`

`get()` and `snapshot()` refuse these; see `ACTION_COMMANDS` in
[reference.py](parker_ar04ae/reference.py).

`DCMDZ` is the trap. Its Response field in the manual is `N/A` — there is **no
read-back form** — and sending it bare re-zeros the analog command input against
whatever voltage happens to be present. There is then no way to recover the previous
zero point from the drive. Note the current `TANI` reading before calling
`zero_command_offset()` if you might need to put it back.

`TANI` reports the voltage *after* the zero point is applied, which is the only
visible evidence of what `DCMDZ` is set to.

### Firmware is newer than the manual

Rev G documents Aries OS 1.0–3.10; this drive reports **OS 3.30**. `TAS`, `TIN` and
`ERRLVL` work on the drive but appear **nowhere** in Rev G, while `TSTAT` — which I
originally guessed at — does not exist; the full-text report is `STATUS`. Treat
[reference.py](parker_ar04ae/reference.py) as the manual's account, not a guarantee
about a given unit.

### Command syntax

- Line limit is **32 characters**, enforced by `raw()`.
- Bare command reads; appending a value writes (`SGP2.0`).
- `DCMDZ` uses `=` (`DCMDZ=0.5`), hence its own method.
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
python -m pytest                          # 119 tests, no hardware needed
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

## State of this drive

From `status` and `info` on the bench unit:

```
OS Revision: 3.30          Power Level: 400W        Bus Voltage: 163V
Motor Name: OTHER=R200D    Motor Type: ROTARY       Feedback: STANDARD ENCODER
Feedback Resolution: 944000                         Operating hours: 1642
```

Two settings worth knowing:

- `FLTSTP` is **5.000 V**, not the 10 V default — a command voltage above 5 V when the
  drive is enabled will fault it. The present 0.94 V is well under.
- `DMVSCL` is **1.000**, so full-scale 10 V is only 1 rev/s. That is why the standing
  command works out to a slow creep rather than a runaway.

The error log holds ten power cycles and no faults.

## Wiring

Pin data is in [reference.py](parker_ar04ae/reference.py) as `DRIVE_IO_PINOUT`,
`MOTOR_FEEDBACK_PINOUT`, `ENABLE_INPUT_SPEC` and `THERMAL_INPUT_SPEC`.

**Pin numbers collide between the two connectors** — pin 15 is `AIN-` on DRIVE I/O
but `Thermal-` on MOTOR FEEDBACK. Always check which connector is meant.

### Enable input — DRIVE I/O pins 1 and 21

| | |
| --- | --- |
| ENABLE+ | pin **1** (anode) |
| ENABLE− | pin **21** (cathode) |

> The drive Enable and Reset inputs are **optically isolated** inputs. Current is
> limited internally for input voltage control of 5 to 24 volt logic. The Anode (+)
> and Cathode (−) are on separate connector pins.

This is the part that trips people up: **it is an opto-isolated LED, not a dry
contact.** Jumpering pin 1 to pin 21 shorts the LED and does nothing. Current has to
*flow through* it — e.g. +24 V to pin 1, pin 21 to 24 V return, with the interlock
switch in that loop. Current is limited internally, so no external resistor is needed
anywhere in 5–24 V.

| | |
| --- | --- |
| Guaranteed on | ≥ 4 VDC |
| Guaranteed off | ≤ 2 VDC |
| Forward current | 3–12 mA |
| Max forward / reverse | 30 V / −30 V |
| Switching time | 1 ms on, 1 ms off |

`RESET+` / `RESET−` on pins **18** and **23** work the same way.

**There is no supply pin on the DRIVE I/O connector.** Table 29 lists only `DGND`
(pins 2, 17, 19, 20, 22, 24) — no +5 V and no +24 V. The enable current has to come
from somewhere else.

A common half-finished state is **pin 2 shorted to pin 21**, which ties `ENABLE−` to
digital ground. That is the *return* half and does nothing on its own; the LED still
needs current fed into `ENABLE+` on pin 1. To complete it, bring +5 to +24 V through
your interlock switch to pin 1, with the supply return at `DGND`. No series resistor:
current is limited internally across the whole 5–24 V range.

```
  +5..24 V ──[ interlock switch ]── pin 1  (ENABLE+)
  supply return ───────────────────  pin 21 (ENABLE−) ── pin 2 (DGND)
```

For a bench bring-up with no 24 V rail to hand, the MOTOR FEEDBACK connector has
+5 VDC on pins **4** and **5** (rated 250 mA; the enable draws 3–12 mA), and its
`DGND` on pins **3** and **6** is the same ground. That works, but it powers the opto
from the drive's own supply and so gives up the optical isolation — reasonable on a
bench, not in a machine.

**Zero the analog command input before you close the interlock.** Per the `DRIVE`
entry, "if the hardware enable input is closed on power-up, the drive is automatically
enabled (generates a `DRIVE1` command)" — no serial command involved. With a standing
command on `AIN+`, the drive would energise and start moving at the next power-up
before anything could intervene.

Per the manual, if the enable input is closed at power-up the drive enables itself
(`DRIVE1`) without a serial command.

### Fault output — DRIVE I/O pins 9 and 16

`FAULT+` is pin **9** (collector), `FAULT−` is pin **16** (emitter). An opto-isolated
transistor, not a relay contact and **not a power source** — it can only pass current
supplied from elsewhere. Max 30 V blocking, **10 mA continuous**.

| Drive condition | Fault output |
| --- | --- |
| Enabled, no faults | closed (conducting) |
| Faulted | open |
| Not enabled, or no AC on L1/L2 | open |

Note the third row: **the fault output is open whenever the drive is not enabled.** So
it cannot by itself supply the enable input — with the drive disabled there would be no
path to start current flowing, and the circuit could never bootstrap. Any scheme that
routes the fault output to `ENABLE+` needs a separate momentary path (a start button in
parallel) to get going, and its holding current would sit right at the 10 mA output
limit against the enable's 3–12 mA draw.

### Motor thermal switch — MOTOR FEEDBACK pins 10 and 15

| | |
| --- | --- |
| Thermal+ | pin **10** |
| Thermal− | pin **15** *(encoder version)* |

2 mA sense current, 15 V maximum supplied. This drive reports `STANDARD ENCODER`
(`SFB 2`), so the encoder pinout applies.

**On the resolver option the map differs** — `Thermal−` moves to pins **3 and 6**, and
pin 15 becomes `Reference−`. Wiring a thermal switch to pin 15 on a resolver unit puts
it on the resolver excitation line.

### Analog command — DRIVE I/O pins 14 and 15

`AIN+` is pin **14**, `AIN−` is pin **15**. To zero the command offset, short 14 to 15
(or command 0 V), then call `zero_command_offset()`.

## Faults latch, and they mask each other

Two behaviours worth knowing before chasing any fault:

- **Faults latch.** Correcting the cause does not clear the error. Per the manual,
  "correct the specified fault, then reset the drive or cycle power to it."
  `reset()` does this.
- **Faults mask each other.** `ERROR` reports what currently prevents enabling;
  clearing one can expose others the drive never got far enough to check. Expect to
  work through them in rounds rather than seeing the full list up front.

## Motor thermal switch: not fitted

MOTOR FEEDBACK pins 10 and 15 are unwired on this setup, so there is no thermal switch
to read and `E36` was raised permanently. `DTHERM1` disables thermal-switch faults,
which is the manual's own recommendation when "no thermal switch is present on the
motor". Applied, and it survives a reset.

```python
drive.set("thermal_mode", 1)   # DTHERM1 - disable thermal-switch faults
drive.reset()                  # clears the latched E36
drive.set("thermal_mode", 0)   # DTHERM0 - re-enable, if a switch is ever fitted
```

**What protection this gives up.** The hardware over-temperature trip is gone. Motor
protection now rests entirely on the drive's **thermal model** — `E35`, computed from
`DMTIC`, `DMTRWC`, `DMTTCM`, `DMTMAX` and `DMTAMB`. Those parameters describe a
third-party motor (`DMTR` reports `OTHER=R200D`) and have not been checked against its
datasheet, so the model's accuracy is unverified. Worth confirming them before running
the motor hard or unattended.

## Feedback: reconnect, then reset

The MOTOR FEEDBACK connector had come unplugged, which produced
`NO FEEDBACK DETECTED`, `SFB 0`, `THALL 0` and the pair `E37`/`E38`.

Reconnecting it is not enough on its own. `SFB` auto-detection runs at power-up, and
the faults latch, so the drive keeps reporting the old state until it restarts:

```python
drive.reset()   # re-runs feedback detection and clears the latched faults
```

After that: `Feedback Type: STANDARD ENCODER`, `SFB 2`, `THALL 5` — a valid hall state,
the manual's Table 51 listing 1–6 as the valid ones — and `E26`, `E37`, `E38` all gone.

## Remaining work

Both items are wiring, not serial.

1. **Zero the analog command input** — do this *first*. It sits at ~0.92 V, which in
   `DMODE4` scales to about +0.088 rev/s. Short `AIN+` (pin **14**) to `AIN-`
   (pin **15**), or command 0 V from the controller, *then* call
   `zero_command_offset()`. Doing it with the input floating would bake the floating
   voltage in as the zero point, and `DCMDZ` has no read-back to recover from that.
   It has to come first because a closed interlock auto-enables the drive at
   power-up.
2. **Complete the enable circuit.** `ENABLE-` (pin 21) is already tied to `DGND`
   (pin 2); `ENABLE+` (pin 1) still needs 5–24 V through the interlock. See
   [Wiring](#wiring). Until then `E46` stands and `DRIVE1` is refused.

`python -m parker_ar04ae check` must report *safe to enable* before going further.
Then `enable()`, motor unloaded. Nothing has ever been commanded to move.

## Still unconfirmed

- **Motion.** The drive has never enabled, so nothing has been commanded to move.
- **Write coverage.** `ERRLVL`, `SGI` and `DCMDZ` were written and restored. The
  mechanism is identical for the rest, but some parameters may be rejected while
  enabled, and several (`DRES`, `IANI`) are documented as requiring a reset to take
  effect.
- **`TAS` bit meanings.** The axis status word reads back but is undocumented in
  Rev G, so individual bits are not decoded.
