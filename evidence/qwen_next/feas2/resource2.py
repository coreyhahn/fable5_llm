#!/usr/bin/env python3
"""resource2.py — the URAM cost of the state caches at the new geometries.

The shipped design's caches are declared in rtl/layer_chan.sv:
  DN   slot  logic [2047:0] mem [4096]   :772     2 slots
  KV   slot  logic [2047:0] mem [8192]   :836     2 slots (+ emem [8192] x 8 b)
  CV   slot  8192 rows x 112 b           :365 CVD = 8192, :891/:892 wm/sm
and the amendment's own totals are URAM 182 of 960
(docs/superpowers/specs/2026-09-04-qwen35-9b-state-spill-design.md 3).

A URAM288 is 4096 x 72 b.  A W-bit row costs ceil(W/72) tiles ACROSS and
ceil(rows/4096) ranks DEEP; the product is the slot's tile count.  This script
reproduces the shipped 182 from those declarations before it sizes anything.
"""
import math

URAM_W, URAM_D = 72, 4096
URAM_TOTAL, URAM_PER_SLR = 960, 320
SHIPPED = 182          # NEXT_SESSION.md 9, OOC9B_URAM


def tiles(rows, width):
    return math.ceil(width / URAM_W) * math.ceil(rows / URAM_D)


def cost(name, ndn, ngqa, lnvh, nkvh, t_max, conv_dim):
    dn_rows = lnvh * 128                  # 128 rows of dk per value head
    kv_rows = 2 * t_max                   # K and V for ONE kvhead
    cv_rows = conv_dim                    # one row per conv channel
    dn = 2 * tiles(dn_rows, 2048)
    kv = 2 * tiles(kv_rows, 2048)
    cv = 2 * tiles(cv_rows, 112)
    return dict(name=name, dn_rows=dn_rows, kv_rows=kv_rows, cv_rows=cv_rows,
                dn=dn, kv=kv, cv=cv, tot=dn + kv + cv)


GEOM = [
    # name        nDN nGQA LNVH NKVH  T_MAX CONV_DIM
    ("9B",         24,  8,  32,   4,  4096,  8192),
    ("27B",        48, 16,  48,   4,  4096, 10240),
    ("35B-A3B",    30, 10,  32,   2,  4096,  8192),
]

if __name__ == "__main__":
    print("=" * 78)
    print("VALIDATION — the shipped 9B cache array, from the declarations")
    print("=" * 78)
    c = cost(*GEOM[0])
    print(f"  DN  2 slots x {c['dn_rows']:5d} rows x 2048 b = {c['dn']:4d} URAM288")
    print(f"  KV  2 slots x {c['kv_rows']:5d} rows x 2048 b = {c['kv']:4d} URAM288")
    print(f"  CV  2 slots x {c['cv_rows']:5d} rows x  112 b = {c['cv']:4d} URAM288")
    print(f"  total {c['tot']:d}  want {SHIPPED:d}  "
          f"{'OK' if c['tot'] == SHIPPED else '*** MISMATCH ***'}")
    assert c["tot"] == SHIPPED

    print()
    print("=" * 78)
    print(f"THE CACHE ARRAY at each geometry, of {URAM_TOTAL} URAM288 "
          f"({URAM_PER_SLR}/SLR)")
    print("=" * 78)
    print(f"{'model':10s} {'DN rows':>8s} {'DN':>5s} {'KV rows':>8s} {'KV':>5s} "
          f"{'CV rows':>8s} {'CV':>5s} {'total':>6s} {'% 960':>7s} "
          f"{'one SLR?':>9s} {'vs 9B':>7s}")
    for g in GEOM:
        c = cost(*g)
        print(f"{c['name']:10s} {c['dn_rows']:8d} {c['dn']:5d} "
              f"{c['kv_rows']:8d} {c['kv']:5d} {c['cv_rows']:8d} {c['cv']:5d} "
              f"{c['tot']:6d} {100.0*c['tot']/URAM_TOTAL:7.1f} "
              f"{('YES' if c['tot'] <= URAM_PER_SLR else 'no'):>9s} "
              f"{c['tot']-SHIPPED:+7d}")
    print()
    print("  Every row assumes the slot COUNT stays at 2 per kind "
          "(rtl/layer_chan.sv:382 N_SLOT = 2) and T_MAX stays 4096")
    print("  (rtl/layer_chan.sv:385 KV_AW = 13).  The DN growth at 27B is a")
    print("  SECOND RANK, not a wider row: 6,144 rows do not fit 4,096, and the")
    print("  2,048 unused rows of the second rank cannot be reclaimed because a")
    print("  URAM288's aspect ratio is fixed.")
    print()
    print("  For comparison the PRE-SPILL 9B array was 928 of 960 "
          "(docs/QWEN35_NEXT_FEASIBILITY.md 7.1), which is the design the")
    print("  state-spill amendment replaced; none of these rows is near that.")
