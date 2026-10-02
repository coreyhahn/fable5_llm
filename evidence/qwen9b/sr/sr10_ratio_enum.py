#!/usr/bin/env python3
"""sr10_ratio_enum.py — Task SR10: an arithmetic cross-check of the MIG sweep
(n1002), NOT the evidence itself (the evidence is Vivado's own validation).

The MIG's MMCM makes the UI clock (= 4 tCK at PhyClockRatio 4:1) from the
3332 ps DIMM refclk as  UI_ps = 3332 * D * O / M  (integer M = CLKFBOUT_MULT,
D = DIVCLK_DIVIDE, O = CLKOUT0_DIVIDE — the IP declares all three as integers,
component.xml C0.DDR4_CLKFBOUT_MULT / DIVCLK_DIVIDE / CLKOUT0_DIVIDE, format
"long").  Constraints used:
  * CLKIN/D >= 70 MHz — the IP's own rule, printed by Vivado in n1003
    ("[IP_Flow 19-3478] ... CLKIN/D value should be >= 70MHz"), so D <= 4;
  * VCO = CLKIN*M/D in 800..1600 MHz — ASSUMED (the MMCME4 range as recalled
    from the UltraScale+ data sheet, not read here); n1002's accepted 937 ps
    runs its VCO at 800.3 MHz, consistent with the 800 floor.
A period P is predicted legal when 3332 is floor or ceil of 4P*M/(D*O) for
some (M, D, O) — the IP's valid-refclk lists come in such floor/ceil pairs
(n1001: 834 ps lists 3335, 3336 = 4*834).  Prints every predicted-legal
integer P in 833..1071 with its cut and M/D/O, for comparison with n1002's
measured list (833 877 937 in 833..940).
"""
import math
import sys

REF = 3332
FIN_MHZ = 1e6 / REF
LO, HI = 833, 1071

hits = {}
for D in range(1, 5):
    if FIN_MHZ / D < 70.0:
        continue
    for M in range(2, 129):
        vco = FIN_MHZ * M / D
        if not (800.0 <= vco <= 1600.0):
            continue
        for O in range(1, 129):
            for P in range(LO, HI + 1):
                clkin = 4.0 * P * M / (D * O)
                if REF in (math.floor(clkin), math.ceil(clkin)):
                    hits.setdefault(P, []).append((M, D, O, round(vco, 1)))

print(f"ENUM: D<=4 (CLKIN/D>=70MHz), VCO 800..1600 MHz (assumed), P {LO}..{HI}")
for P in sorted(hits):
    cut = 100.0 * (1.0 - 833.0 / P)
    print(f"ENUM_LEGAL: P={P} cut={cut:.3f}% UI_mmcm={REF*hits[P][0][1]*hits[P][0][2]/hits[P][0][0]:.3f}ps "
          f"MDO={hits[P][:4]}")
print("ENUM_LIST_833_940:", " ".join(str(p) for p in sorted(hits) if p <= 940))
print("ENUM_LIST_ALL:", " ".join(str(p) for p in sorted(hits)))
sys.exit(0)
