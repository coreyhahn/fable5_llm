#!/usr/bin/env python3
"""resource_budget.py — what the 32-layer / 32-value-head banking costs on the VU9P.

The 2B migration's three walls were all FIELD WIDTHS.  The 4B/9B walls are
mostly CAPACITY, and the binding resource is URAM.

AS-BUILT (rtl/layer_chan.sv):
  DN recurrent state   9 banks : `for (gd = 0; gd < 9) ... logic [2047:0] mem [4096]`
                       (:423-424) = 36,864 rows = 18 DN slots x 16 heads x 128 rows
  KV cache             3 banks : `for (gk = 0; gk < 3) ... logic [2047:0] mem [4096]`
                       (:475-477) = 12,288 rows = 6 GQA slots x 2 kv heads x 2 (k,v)
                       x 512 t
  conv weights/state  18 banks : `logic [63:0] wm [6144]; logic [47:0] sm [6144]`
                       (:512-514), one per DN slot, depth = CONV_DIM
  scratch              2 replicas x 32,768 x 16 b (:280-281)

MEASURED device totals for the RESIDENT build_035 (evidence/qwen2b/rc/TIMING_035.md
:340-347, :850-851): URAM 348 of 960 (36.25 %), Block RAM Tile 576.5 of 2160,
DSP48E2 1858 of 6840, CLB LUTs 299,076 of 1,182,240 (25.30 %).
348 = 9 DN banks + 3 KV banks = 12 banks x 29 URAM288 each
(a 2048-bit row over a 72-bit-wide URAM288 needs ceil(2048/72) = 29).

Per-SLR capacity (evidence/qwen2b/ra/util_resident.md): 320 URAM, ~720 BRAM
tiles, 2280 DSP, 49,260 CLB per SLR.  TIMING_035.md:629-630 already records
that `layer_0` at 348 URAM CANNOT sit in one SLR.
"""
import json
import sys

URAM_TOTAL, URAM_PER_SLR = 960, 320
BRAM_TOTAL = 2160
URAM_ROWS, URAM_W = 4096, 72
RAMB36_BITS = 36 * 1024

MEAS_BUILD035 = dict(uram=348, bram=576.5, dsp=1858, lut=299076)


def uram_for_bank(rows, width):
    """URAM288s for a `rows x width` bank, as the RTL infers it."""
    depth_units = -(-rows // URAM_ROWS)
    width_units = -(-width // URAM_W)
    return depth_units * width_units


def ramb36_for(rows, width):
    return -(-(rows * width) // RAMB36_BITS)


GEOM = {
    #          L   nDN nGQA  H    FFN   LNVH LNKH LDK LDV  NQ NKV  HD  CONV_DIM
    "0.8B": (24, 18, 6, 1024, 3584, 16, 16, 128, 128, 8, 2, 256, 6144),
    "2B":   (24, 18, 6, 2048, 6144, 16, 16, 128, 128, 8, 2, 256, 6144),
    "4B":   (32, 24, 8, 2560, 9216, 32, 16, 128, 128, 16, 4, 256, 8192),
    "9B":   (32, 24, 8, 4096, 12288, 32, 16, 128, 128, 16, 4, 256, 8192),
}
T_MAX = 512          # a51bc8e:rtl/attn_core.sv:13 "T <= 512" -- the tree
                     # this study was written against; S2 (SEQ ISA v2.1)
                     # took it to "T <= 4096" (rtl/attn_core.sv:13), which
                     # only makes the KV numbers below CONSERVATIVE.
SCRATCH_PEAK = {"0.8B": 16384, "2B": 25600, "4B": 36384, "9B": 50208}


def budget(name):
    (L, nDN, nGQA, H, FFN, LNVH, LNKH, LDK, LDV, NQ, NKV, HD, CONV) = GEOM[name]

    # --- DN recurrent state: per VALUE head a dk x dv state, stored as
    #     LDK rows of LDV x 16 b = 2048 b.  rtl/dn_step.sv:12.
    dn_rows = nDN * LNVH * LDK
    dn_banks = -(-dn_rows // URAM_ROWS)
    dn_uram = dn_banks * uram_for_bank(URAM_ROWS, 2048)

    # --- KV cache: per GQA slot, per kv head, k and v, T rows of 2048 b
    kv_rows = nGQA * NKV * 2 * T_MAX
    kv_banks = -(-kv_rows // URAM_ROWS)
    kv_uram = kv_banks * uram_for_bank(URAM_ROWS, 2048)

    # --- conv: one wm/sm bank per DN slot, depth CONV_DIM
    conv_bram = nDN * (ramb36_for(CONV, 64) + ramb36_for(CONV, 48))

    # --- scratch: next power of two above the peak, x2 replicas, 16 b
    peak = SCRATCH_PEAK[name]
    scratch_words = 1 << max(14, (peak - 1).bit_length())
    scratch_bram = 2 * ramb36_for(scratch_words, 16)

    return dict(name=name, dn_rows=dn_rows, dn_banks=dn_banks, dn_uram=dn_uram,
                kv_rows=kv_rows, kv_banks=kv_banks, kv_uram=kv_uram,
                uram=dn_uram + kv_uram, conv_bram=conv_bram,
                scratch_words=scratch_words, scratch_bram=scratch_bram,
                conv_dim=CONV, peak=peak,
                dn_state_bytes=nDN * LNVH * LDK * LDV * 2)


if __name__ == "__main__":
    rows = [budget(n) for n in ("0.8B", "2B", "4B", "9B")]

    print("=" * 78)
    print("VALIDATION — the model must reproduce build_035's measured 348 URAM")
    print("=" * 78)
    b2 = budget("2B")
    print(f"    2B  DN {b2['dn_banks']} banks x 29 = {b2['dn_uram']} URAM"
          f"   KV {b2['kv_banks']} banks x 29 = {b2['kv_uram']} URAM"
          f"   total {b2['uram']}")
    print(f"    measured on build_035 (TIMING_035.md:347/:851): "
          f"{MEAS_BUILD035['uram']}   "
          f"{'OK' if b2['uram'] == MEAS_BUILD035['uram'] else '*** MISMATCH ***'}")
    print(f"    2B  DN banks as declared: 8138d66:rtl/layer_chan.sv:457 `gd < 9`  -> "
          f"model {b2['dn_banks']}  "
          f"{'OK' if b2['dn_banks'] == 9 else '*** MISMATCH ***'}")
    print(f"    2B  KV banks as declared: 8138d66:rtl/layer_chan.sv:522 `gk < 3`  -> "
          f"model {b2['kv_banks']}  "
          f"{'OK' if b2['kv_banks'] == 3 else '*** MISMATCH ***'}")

    print()
    print("=" * 78)
    print("URAM — the binding resource")
    print("=" * 78)
    print(f"    {'model':6s} {'DN rows':>10s} {'banks':>6s} {'DN URAM':>8s} "
          f"{'KV rows':>8s} {'banks':>6s} {'KV URAM':>8s} {'TOTAL':>7s} "
          f"{'of 960':>8s} {'SLRs needed':>12s}")
    for r in rows:
        slrs = -(-r["uram"] // URAM_PER_SLR)
        print(f"    {r['name']:6s} {r['dn_rows']:10,} {r['dn_banks']:6d} "
              f"{r['dn_uram']:8d} {r['kv_rows']:8,} {r['kv_banks']:6d} "
              f"{r['kv_uram']:8d} {r['uram']:7d} "
              f"{100*r['uram']/URAM_TOTAL:7.1f}% {slrs:12d}"
              + ("   *** OVER DEVICE ***" if r["uram"] > URAM_TOTAL else ""))
    print()
    print("    The 4B and 9B DeltaNet state is IDENTICAL (both are 24 DN layers")
    print("    x 32 value heads x 128x128), so this wall is the same size at both")
    print("    targets: it is a HEAD-COUNT wall, not a hidden-size wall.")

    print()
    print("=" * 78)
    print("BRAM — conv banks (depth = CONV_DIM) and the scratchpad")
    print("=" * 78)
    print(f"    {'model':6s} {'CONV_DIM':>9s} {'conv banks':>11s} {'conv RAMB36':>12s} "
          f"{'scratch words':>14s} {'scratch RAMB36':>15s}")
    for r in rows:
        nDN = GEOM[r["name"]][1]
        print(f"    {r['name']:6s} {r['conv_dim']:9d} {nDN:11d} "
              f"{r['conv_bram']:12d} {r['scratch_words']:14,} {r['scratch_bram']:15d}")
    d2 = budget("2B")
    for r in rows:
        if r["name"] in ("0.8B", "2B"):
            continue
        dbram = (r["conv_bram"] - d2["conv_bram"]) + (r["scratch_bram"] - d2["scratch_bram"])
        tot = MEAS_BUILD035["bram"] + dbram
        print(f"    {r['name']}: conv {r['conv_bram']-d2['conv_bram']:+d} + scratch "
              f"{r['scratch_bram']-d2['scratch_bram']:+d} RAMB36 -> device "
              f"{MEAS_BUILD035['bram']:.1f} + {dbram} = {tot:.1f} of {BRAM_TOTAL} "
              f"({100*tot/BRAM_TOTAL:.1f} %)   "
              f"{'OK' if tot <= BRAM_TOTAL else 'OVER'}")
    print("    -> BRAM is NOT the wall at either target.  URAM is.")

    print()
    print("=" * 78)
    print("THE URAM ESCAPE — spilling the DeltaNet state to DDR, costed")
    print("=" * 78)
    print("    The DN state is touched ONCE per token per layer, so streaming it")
    print("    from DDR costs 2x its size in traffic per token (read + write).")
    print(f"    {'model':6s} {'state MiB':>10s} {'traffic MiB/tok':>16s} "
          f"{'weights MiB (W8)':>17s} {'as % of weights':>16s}")
    W8_MIB = {"2B": 1847.2, "4B": 4104.2, "9B": 7686.2}
    W4_MIB = {"2B": 950.1, "4B": 2099.2, "9B": 3902.2}
    for r in rows:
        if r["name"] == "0.8B":
            continue
        st = r["dn_state_bytes"] / 2**20
        print(f"    {r['name']:6s} {st:10.1f} {2*st:16.1f} "
              f"{W8_MIB[r['name']]:17.1f} {100*2*st/W8_MIB[r['name']]:15.1f} %"
              f"   (W4: {100*2*st/W4_MIB[r['name']]:.1f} %)")
    print("    -> the BANDWIDTH cost of spilling is small; the cost is a new DMA")
    print("       path in dn_step/layer_chan and a state-coherency protocol, which")
    print("       is a large RTL project, not a parameter change.")

    print()
    print("=" * 78)
    print("THE OTHER URAM LEVER — narrowing the DN state element from int16")
    print("=" * 78)
    print("    The DN state row is 2048 b = 128 columns x 16 b "
          "(8138d66:rtl/layer_chan.sv:458, rtl/dn_step.sv:12).")
    print("    The KV cache next to it is ALREADY 8 b/element "
          "(2048 b / 256 head_dim).")
    print("    At int8 two state rows pack into one 2048-bit URAM row, halving")
    print("    the bank count.  This is a FIDELITY change with no measurement")
    print("    anywhere in this repo — it is named as a lever, not proposed.")
    for r in rows:
        if r["name"] not in ("4B", "9B"):
            continue
        dn16 = r["dn_uram"]
        dn8 = -(-(r["dn_rows"] // 2) // URAM_ROWS) * uram_for_bank(URAM_ROWS, 2048)
        for lab, dn in (("int16 (as built)", dn16), ("int8", dn8)):
            tot = dn + r["kv_uram"]
            print(f"    {r['name']:4s} DN state {lab:16s} DN {dn:4d} + KV "
                  f"{r['kv_uram']:3d} = {tot:4d} URAM  "
                  f"{100*tot/URAM_TOTAL:5.1f}% of 960  "
                  f"{-(-tot // URAM_PER_SLR)} SLRs")

    print()
    print("=" * 78)
    print("CONV COUNT FIELDS — over by exactly one")
    print("=" * 78)
    # CLASS B, PINNED to the tree that carries the quotations: 1204 and
    # 1251 are their lines at d2d774b (8ef57a8^), the tree BEFORE G3.1.
    # Task 10 fix round 2 called them "the 8138d66 line numbers"; they are
    # not (8138d66 already carries the 14-bit form at 1271 / 1318), and S3
    # fix round 3 re-pinned them.  The QUOTATIONS had ALREADY died by then:
    # `git log -S "cvi == arg0[25:13]"` and `-S "wi + 1'b1 == arg0[27:15]"`
    # both land on 8ef57a8 (G3.1), which took the CONV/CONVW channel FIELDS
    # to 14 bits -- 8138d66:rtl/layer_chan.sv:882 already reads
    # `logic [13:0] cvi, cvj;`.  So this is drift the G3.4 gate INHERITED,
    # not drift it caused; what G3.4 changed is the conv BANKS behind the
    # fields (18 x 6144 -> 24 x 8192) and the refusal of nch == 0.
    # Post-G3.4 sites:
    #   rtl/layer_chan.sv:1870  `if (cvi == arg0[27:14]) st <= CV_D;`
    #   rtl/layer_chan.sv:1917 and rtl/layer_chan.sv:1933
    #                           `if (wi + 1'b1 == arg0[29:16]) st <= DONE_S;`
    # (2026-09-02, Task 10 fix round 2 -- evidence/qwen9b/g3/G3_4_LAYER.md 5.3)
    print("    d2d774b:rtl/layer_chan.sv:1204  `if (cvi == arg0[25:13])`  13-bit")
    print("    d2d774b:rtl/layer_chan.sv:1251  `if (wi + 1'b1 == arg0[27:15])`  13-bit")
    print("      [class B: G3.1 made both fields 14-bit and G3.4 grew the")
    print("       banks -- see the note above this print in the source]")
    print(f"    field max = {(1<<13)-1}")
    for r in rows:
        print(f"    {r['name']:6s} CONV_DIM {r['conv_dim']:6d}  "
              f"{'FITS' if r['conv_dim'] <= (1<<13)-1 else 'OVER by ' + str(r['conv_dim']-((1<<13)-1))}"
              f"   conv memory depth 6144 -> "
              f"{'ok' if r['conv_dim'] <= 6144 else 'must grow to ' + str(r['conv_dim'])}")

    json.dump(rows, open(sys.argv[1], "w") if len(sys.argv) > 1 else sys.stderr,
              indent=1, sort_keys=True)
