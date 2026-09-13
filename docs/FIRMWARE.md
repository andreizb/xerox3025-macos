# Firmware boundary

This repository does not contain firmware files or an automatic updater. Scanner
and toner installers do not change printer firmware or network settings.

The accepted local BI device was non-Tag-29 and was updated separately with an
official matching package to V3.50.03.06. Its network version remained V6.01.19.
That result is not a recommendation to flash the same image on another unit.
The BI/NI variant and wireless hardware tag must be matched to Xerox's official
release documentation before selecting firmware. Tag-29 packages are not a
universal update for older wireless hardware. Preserve Wi-Fi configuration and
avoid factory resets as part of driver installation.
