# SpliX comparison

[OpenPrinting SpliX](https://github.com/OpenPrinting/splix) explicitly lists the
Xerox WorkCentre 3025. It converts print jobs for SPL2/SPLc/QPDL printers; it is
not a scanner backend or eSCL/ICA bridge.

The [3025 model definition](https://github.com/OpenPrinting/splix/blob/4854286334346059e7fec6f5f2328a23fa5fa774/ppd/xerox.drv.in#L158-L204)
inherits toner-save and toner-density controls, declares 1200 dpi printing and
manual duplex. These are source declarations, not results on this Mac. Manual
duplex does not add an automatic duplex unit. The README says development is
discontinued; inspect upstream state before deciding future support.

SpliX might be useful as an optional print-only alternative if additional print
controls justify it. No native build, physical print, quality comparison, toner
UI fix or driver-selection test has been done for SpliX here. It is not installed,
vended or selected by this project. Keep the working AirPrint path and scanner
service until a separate, reversible comparison demonstrates an improvement.
