#!/usr/bin/env python3
"""scratch_peak2.py — the scratchpad peak at 27B / 35B-A3B against the CURRENT
allocator (post-G3.1, 65,536 words).

evidence/qwen_next/feas/scratch_peak.py mirrored the PRE-G3.1 allocator and
carried `SCRATCH_MAX = 32768` plus its own `fix_sca` branch.  Both moved:

  * `ref/gen_layer_script.py:425-426` is now `SCRATCH_MAX = 65536` /
    `ISA_SADDR_MAX = 65536`, backed by `rtl/layer_chan.sv:503-504`'s
    `smem_a [65536]` / `smem_b [65536]` and 16-bit `sa_addr`/`sb_addr`.
  * the `fix_sca` branch WAS ADOPTED: `ref/gen_layer_script.py:125-133` is the
    `max(32, ...)` tile map, and `:200` is `STG = SCA + max(1024, SCA_SZ)`.

So this script mirrors `ref/gen_layer_script.py:92-242` as it stands at HEAD,
line for line, and validates by reproducing (a) `_LEGACY_MAP`'s frozen 0.8B
literals at `:244-251` EXACTLY and (b) the 9B peaks the committed study
derived (PEAK_DN 33,824 / PEAK_ATTN 37,920 / PEAK_MLP 50,208).
"""
SCRATCH_MAX = 65536      # ref/gen_layer_script.py:425
CHUNK = 2048             # ref/gen_layer_script.py:92


def derive(H, FFN, NQ, NKV, HD, LNKH, LNVH, LDK, LDV, nc=1):
    """ref/gen_layer_script.py:92-242, with the gate/up pair chunked `nc` ways.

    `nc` is NOT in the allocator: it is the mitigation the 4B/9B study priced
    (its 2.2), where the gate/up stage becomes `STG + 3*C` with C = FFN/nc and
    the down stage `STG + 2*C + STGCH + H`.  nc=1 is the allocator verbatim.
    """
    LKD = LNKH * LDK                    # ref/layer_ref.py:46
    LVD = LNVH * LDV                    # ref/layer_ref.py:47
    CONV_DIM = 2 * LKD + LVD
    STGCH = 2 * min(CHUNK, H)           # :93
    X0, XN, X8, SCA = 0, H, 2 * H, 3 * H          # :97-100
    tiles = (("B16", max(32, LNVH)), ("A16", max(32, 2 * LNVH)),
             ("GD", max(32, 2 * LNVH)), ("QN", LDK), ("QNS", LDK),
             ("KN", LDK), ("DO32", 2 * LDV), ("OH", LDV), ("NH", LDV))
    T, o = {}, 0
    for n, sz in tiles:
        T[n] = SCA + o
        o += sz
    SCA_SZ = o
    STG = SCA + max(1024, SCA_SZ)       # :200
    STG_SZ = LVD + STGCH                # :201
    BIG = STG + STG_SZ                  # :202
    NQH, KVH = NQ * HD, NKV * HD        # :209

    DN_QKV = BIG
    DN_Z16 = DN_QKV + CONV_DIM
    PEAK_DN = DN_Z16 + LVD              # :237

    AT_QG = BIG
    AT_K16 = AT_QG + 2 * NQH
    AT_V16 = AT_K16 + KVH
    AT_QR = AT_V16 + KVH
    AT_KR = AT_QR + NQH
    AT_AO32 = STG
    AT_OG = AT_AO32 + 2 * HD
    AT_GATED = AT_OG + HD
    AT_GX8 = AT_GATED + NQH + 64
    AT_OSTG = BIG + H
    AT_ODST = AT_OSTG + STGCH + H
    PEAK_ATTN = max(AT_KR + KVH, AT_ODST + H, AT_GX8 + NQH)     # :238

    C = -(-FFN // nc)
    ML_GP = STG
    ML_SG = ML_GP + 2 * C
    ML_DDST = ML_SG + STGCH
    PEAK_MLP = max(ML_SG + C, ML_DDST + H)                      # :239

    PEAK = max(PEAK_DN, PEAK_ATTN, PEAK_MLP)                    # :240
    return dict(X0=X0, XN=XN, X8=X8, SCA=SCA, SCA_SZ=SCA_SZ, STG=STG,
                STG_SZ=STG_SZ, BIG=BIG, CONV_DIM=CONV_DIM, LVD=LVD,
                PEAK_DN=PEAK_DN, PEAK_ATTN=PEAK_ATTN, PEAK_MLP=PEAK_MLP,
                PEAK=PEAK, SCRATCH=1 << max(14, (PEAK - 1).bit_length()),
                **{k: T[k] for k in T})


#            H     FFN   NQ NKV  HD LNKH LNVH LDK LDV
GEOM = {
    "0.8B": (1024,  3584,  8, 2, 256, 16, 16, 128, 128),
    "2B":   (2048,  6144,  8, 2, 256, 16, 16, 128, 128),
    "9B":   (4096, 12288, 16, 4, 256, 16, 32, 128, 128),
    "27B":  (5120, 17408, 24, 4, 256, 16, 48, 128, 128),
    # the MoE's MLP body is ONE EXPERT at a time (moe_intermediate 512).  The
    # second row stages all k+1 active experts' intermediates at once, which
    # is the other way the body could be written.  Both are shown because the
    # emitter for it does not exist and the choice is open.
    "35B-A3B/1expert":  (2048, 512, 16, 2, 256, 16, 32, 128, 128),
    "35B-A3B/9experts": (2048, 9 * 512, 16, 2, 256, 16, 32, 128, 128),
}
LEGACY = {"X0": 0, "XN": 1024, "X8": 2048, "SCA": 3072, "SCA_SZ": 992,
          "STG": 4096, "STG_SZ": 4096, "BIG": 8192, "B16": 3072, "A16": 3104,
          "GD": 3136, "QN": 3168, "QNS": 3296, "KN": 3424, "DO32": 3552,
          "OH": 3808, "NH": 3936, "PEAK_DN": 16384, "PEAK_ATTN": 15872,
          "PEAK_MLP": 14848, "SCRATCH": 16384}

if __name__ == "__main__":
    print("=" * 78)
    print("VALIDATION 1 — the frozen 0.8B map (ref/gen_layer_script.py:244-251)")
    print("=" * 78)
    d = derive(*GEOM["0.8B"])
    bad = [(k, v, d[k]) for k, v in LEGACY.items() if d[k] != v]
    for k in sorted(LEGACY):
        print(f"  {k:10s} {d[k]:8d}  want {LEGACY[k]:8d}  "
              f"{'OK' if d[k] == LEGACY[k] else '*** MISMATCH ***'}")
    assert not bad, bad

    print()
    print("=" * 78)
    print("VALIDATION 2 — the 9B peaks the committed study derived (its 2.2)")
    print("=" * 78)
    d9 = derive(*GEOM["9B"])
    for k, want in (("PEAK_DN", 33824), ("PEAK_ATTN", 37920),
                    ("PEAK_MLP", 50208)):
        print(f"  {k:10s} {d9[k]:8d}  want {want:8d}  "
              f"{'OK' if d9[k] == want else '*** MISMATCH ***'}")
        assert d9[k] == want

    print()
    print("=" * 78)
    print(f"THE PEAKS, against the CURRENT array of {SCRATCH_MAX:,} words")
    print("=" * 78)
    print(f"{'model':20s} {'SCA_SZ':>7s} {'STG':>7s} {'BIG':>7s} "
          f"{'PEAK_DN':>8s} {'PEAK_ATTN':>10s} {'PEAK_MLP':>9s} {'PEAK':>8s} "
          f"{'spare':>8s} {'verdict':>8s}")
    for name in ("0.8B", "2B", "9B", "27B", "35B-A3B/1expert",
                 "35B-A3B/9experts"):
        d = derive(*GEOM[name])
        sp = SCRATCH_MAX - d["PEAK"]
        print(f"{name:20s} {d['SCA_SZ']:7d} {d['STG']:7d} {d['BIG']:7d} "
              f"{d['PEAK_DN']:8d} {d['PEAK_ATTN']:10d} {d['PEAK_MLP']:9d} "
              f"{d['PEAK']:8d} {sp:8d} "
              f"{'PASS' if sp >= 0 else 'FAIL':>8s}")

    print()
    print("=" * 78)
    print("THE 27B's MITIGATION — chunking the gate/up pair, as the 4B/9B")
    print("study priced it (its 2.2: the DOWN stage takes over as the peak)")
    print("=" * 78)
    print(f"{'chunks':>7s} {'gate/up':>9s} {'down':>9s} {'PEAK_MLP':>9s} "
          f"{'PEAK':>8s} {'spare':>8s}")
    for nc in (1, 2, 3, 4):
        d = derive(*GEOM["27B"], nc=nc)
        C = -(-GEOM["27B"][1] // nc)
        gu = d["STG"] + 3 * C
        dn = d["STG"] + 2 * C + 2 * min(CHUNK, GEOM["27B"][0]) + GEOM["27B"][0]
        print(f"{nc:7d} {gu:9d} {dn:9d} {d['PEAK_MLP']:9d} {d['PEAK']:8d} "
              f"{SCRATCH_MAX - d['PEAK']:8d}")
    print()
    print("  Note PEAK_ATTN does NOT move with chunking: at 27B it is "
          f"{derive(*GEOM['27B'])['PEAK_ATTN']:,} words, and that is the floor "
          "any MLP")
    print("  chunking can reach.  The DN body's floor is "
          f"{derive(*GEOM['27B'])['PEAK_DN']:,}.")
