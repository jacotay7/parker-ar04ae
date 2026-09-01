# Manuals

Parker Hannifin ARIES documentation, kept here so the library's command set can be
checked against the source. Four unique documents; duplicates and downsampled copies
have been removed.

| File | Document | Part no. | Pages | Date |
| --- | --- | --- | --- | --- |
| [aries-user-guide-rev-g-2008.pdf](aries-user-guide-rev-g-2008.pdf) | Aries User Guide, **Revision G** | 88-021610-01G | 208 | 2008 |
| [aries-user-guide-rev-f-2005.pdf](aries-user-guide-rev-f-2005.pdf) | Aries User Guide, **Revision F** | 88-021610-01F | 208 | 2005 |
| [aries-quick-reference-guide-rev-d-2005.pdf](aries-quick-reference-guide-rev-d-2005.pdf) | Aries Quick Reference Guide, Revision D | 88-021594-01D | 2 | June 2005 |
| [aries-servo-drive-datasheet-2006.pdf](aries-servo-drive-datasheet-2006.pdf) | Aries Servo Drive datasheet / brochure | — | 4 | 2006 |

All cover the full range: AR-01xE, 02xE, **04xE**, 08xE and AR-13xE.

**Start with Revision G** — it is the newest, and its change summary states it
supersedes 88-021610-1F. Rev F is kept because the two differ substantially: 151 of
208 pages have materially different content, not merely a different scan. If Rev G is
unclear on something, Rev F is worth a second look rather than a duplicate.

The User Guide's command reference is the authority for the serial command set in
[../parker_ar04ae/drive.py](../parker_ar04ae/drive.py). Its index lists commands this
library has not wrapped — `STATUS` (full text report), `TERRLG` (error log) and
`TVER` among them — so the wrapped set is not yet complete.

## What was removed

- `79949749.pdf` — byte-identical to the Quick Reference Guide (same MD5).
- `54d809…_optim.pdf`, `93c21de…_optim.pdf` — the same Quick Reference Guide
  re-optimised in 2024. Identical extracted text to each other, but their images are
  downsampled to roughly half resolution (192×74 → 92×35), so the originals were kept
  for legibility of the wiring diagrams.
