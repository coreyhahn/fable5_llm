#!/usr/bin/env python3
"""Emit RTL ROM init files from fixedpoint.py's own tables (single source).
Run from ref/: python3 gen_roms.py   -> writes ../rtl/roms/*.hex
"""
import numpy as np
import fixedpoint as fp


def wr(path, vals, width_bits):
    mask = (1 << width_bits) - 1
    with open(path, "w") as f:
        for v in np.asarray(vals).reshape(-1):
            f.write(f"{int(v) & mask:0{(width_bits + 3) // 4}x}\n")


def pairs(tab, fw):
    """rom[i] = {tab[i+1], tab[i]} with field width fw, for 1-read interp."""
    t = np.asarray(tab, dtype=np.int64)
    m = (1 << fw) - 1
    return [((int(t[i + 1]) & m) << fw) | (int(t[i]) & m)
            for i in range(len(t) - 1)]


fp.recip_q(3, 0)
fp.sigmoid_q(0)
fp.softplus_q(0)
fp.exp2_frac_q16(0)

wr("../rtl/roms/rsqrt_rom.hex", fp._rsqrt_lut(), 16)            # 512x16
wr("../rtl/roms/recip_rom.hex", fp._RECIP_LUT, 16)              # 256x16
wr("../rtl/roms/exp2_rom.hex", fp._exp2_lut(), 18)              # 257x18
wr("../rtl/roms/sigmoid_rom.hex", fp._SIGMOID_TAB, 16)          # 257x16
wr("../rtl/roms/softplus_rom.hex", fp._SOFTPLUS_TAB, 17)        # 257x17
wr("../rtl/roms/sigmoid_pair_rom.hex", pairs(fp._SIGMOID_TAB, 16), 32)   # 256x32
wr("../rtl/roms/softplus_pair_rom.hex", pairs(fp._SOFTPLUS_TAB, 17), 34) # 256x34
wr("../rtl/roms/exp2_pair_rom.hex", pairs(fp._exp2_lut(), 18), 36)       # 256x36
print("roms written")
