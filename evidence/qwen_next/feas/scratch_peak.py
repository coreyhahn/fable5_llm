#!/usr/bin/env python3
"""scratch_peak.py — re-derive the scratchpad peak at 4B / 9B with the REAL
head geometry, using the as-built allocator's algebra.

The allocator is `ref/gen_layer_script.py:78-142` (module-level constants,
parameterized only through `ref/layer_ref.py:25-41`, which reads text_config).
It cannot simply be imported at 4B/9B because of TWO latent assumptions that
the 0.8B and 2B checkpoints happen to satisfy and the 4B/9B ones do not:

  W-REF-1  ref/layer_ref.py:38  `LKD = LNH * LDK` with `LNH =
           linear_num_value_heads`.  This silently assumes
           linear_num_key_heads == linear_num_value_heads.  True at 0.8B/2B
           (16/16); FALSE at 4B/9B (16 key heads, 32 value heads), where it
           over-states CONV_DIM as 12288 instead of the checkpoint's 8192.

  W-REF-2  ref/gen_layer_script.py:93-102  the nine DeltaNet scalar tiles are
           placed on hard-coded 32-word strides inside a 992-word SCA block:
           B16 @ +0 (LNH words), A16 @ +32 (2*LNH), GD @ +64 (2*LNH).  At
           LNH=16 each fits its 32-word slot exactly.  At LNH=32 A16 needs 64
           words in a 32-word slot and GD needs 64 in a 32-word slot: the
           tiles COLLIDE.  The block must grow by 64 words.

So this script re-implements the same algebra with both corrected, validates it
by reproducing the committed 0.8B and 2B numbers exactly, and only then
evaluates 4B and 9B.  Every formula carries the gen_layer_script line it mirrors.

Calibration: evidence/qwen2b/ra/scratch_probe.log measured PEAK == derived PEAK
at both 0.8B (16384) and 2B (25600).
"""
import json
import sys

SCRATCH_MAX = 32768   # ref/gen_layer_script.py:231 (ISA ceiling, 15-bit saddr)
CHUNK = 2048          # ref/gen_layer_script.py:79


def derive(name, H, FFN, NQ, NKV, HD, LNKH, LNVH, LDK, LDV, fix_sca=True):
    """Mirror of ref/gen_layer_script.py:78-140, with W-REF-1 / W-REF-2 fixed."""
    # ref/layer_ref.py:38-41, corrected: key dim uses KEY heads
    LKD = LNKH * LDK              # total key/query width  (ref: LNH*LDK)
    LVD = LNVH * LDV              # total value width
    CONV_DIM = 2 * LKD + LVD      # ref/layer_ref.py:41

    STGCH = 2 * min(CHUNK, H)     # :59

    # ---- SCA block (:72-81).  As-built strides are 32/32/32 then 128s.
    # B16 = LNH, A16 = 2*LNH, GD = 2*LNH, then QN/QNS/KN = LDK(=128 per head),
    # DO32 = 2*LDV, OH = LDV, NH = LDV  (per-HEAD dims, head-count independent).
    if fix_sca:
        s = 0
        B16_off = s; s += max(32, LNVH)
        A16_off = s; s += max(32, 2 * LNVH)
        GD_off = s;  s += max(32, 2 * LNVH)
        QN_off = s;  s += LDK
        QNS_off = s; s += LDK
        KN_off = s;  s += LDK
        DO32_off = s; s += 2 * LDV
        OH_off = s;  s += LDV
        NH_off = s;  s += LDV
        SCA_SZ = s
    else:                          # verbatim as-built literals (:72-81)
        B16_off, A16_off, GD_off = 0, 32, 64
        QN_off, QNS_off, KN_off = 96, 224, 352
        DO32_off, OH_off, NH_off = 480, 736, 864
        SCA_SZ = 992

    X0 = 0                         # :62
    XN = H                         # :63
    X8 = 2 * H                     # :64
    SCA = 3 * H                    # :65
    STG = SCA + max(1024, SCA_SZ)  # :67  (as-built literal 1024 >= SCA_SZ 992)
    STG_SZ = LVD + STGCH           # :68
    BIG = STG + STG_SZ             # :69

    NQH, KVH = NQ * HD, NKV * HD   # :87

    DN_QKV = BIG                                  # :89
    DN_Z16 = DN_QKV + CONV_DIM                    # :90
    DN_OUTSTG = STG + LVD                         # :92
    DN_OUTDST = BIG                               # :93

    AT_QG = BIG                                   # :95
    AT_K16 = AT_QG + 2 * NQH                      # :96
    AT_V16 = AT_K16 + KVH                         # :97
    AT_QR = AT_V16 + KVH                          # :98
    AT_KR = AT_QR + NQH                           # :99
    AT_AO32 = STG                                 # :100
    AT_OG = AT_AO32 + 2 * HD                      # :101
    AT_GATED = AT_OG + HD                         # :102
    AT_GX8 = AT_GATED + NQH + 64                  # :103
    AT_OSTG = BIG + H                             # :104
    AT_ODST = AT_OSTG + STGCH + H                 # :105

    ML_GP = STG                                   # :107
    ML_SG = ML_GP + 2 * FFN                       # :108
    ML_DSTG = ML_SG                               # :109
    ML_DDST = ML_SG + STGCH                       # :110

    PEAK_DN = DN_Z16 + LVD                                        # :116
    PEAK_ATTN = max(AT_KR + KVH, AT_ODST + H, AT_GX8 + NQH)       # :117
    PEAK_MLP = max(ML_SG + FFN, ML_DDST + H)                      # :118
    PEAK = max(PEAK_DN, PEAK_ATTN, PEAK_MLP)                      # :119
    SCRATCH = 1 << max(14, (PEAK - 1).bit_length())               # :121

    return dict(
        name=name, H=H, FFN=FFN, NQ=NQ, NKV=NKV, HD=HD,
        LNKH=LNKH, LNVH=LNVH, LKD=LKD, LVD=LVD, CONV_DIM=CONV_DIM,
        NQH=NQH, KVH=KVH, SCA_SZ=SCA_SZ, STGCH=STGCH, STG=STG,
        STG_SZ=STG_SZ, BIG=BIG,
        SCA_tiles=dict(B16=B16_off, A16=A16_off, GD=GD_off, QN=QN_off,
                       QNS=QNS_off, KN=KN_off, DO32=DO32_off, OH=OH_off,
                       NH=NH_off),
        PEAK_DN=PEAK_DN, PEAK_ATTN=PEAK_ATTN, PEAK_MLP=PEAK_MLP,
        PEAK=PEAK, SCRATCH=SCRATCH,
        fits_isa=PEAK <= SCRATCH_MAX,
        over_by=max(0, PEAK - SCRATCH_MAX),
    )


# ---- the four geometries, EVERY field taken from the checkpoint census in
# evidence/qwen_next/feas/geometry_raw.json (safetensors headers + config.json)
MODELS = [
    # name        H     FFN    NQ NKV  HD  LNKH LNVH LDK LDV
    ("0.8B",     1024,  3584,   8,  2, 256,  16,  16, 128, 128),
    ("2B",       2048,  6144,   8,  2, 256,  16,  16, 128, 128),
    ("4B",       2560,  9216,  16,  4, 256,  16,  32, 128, 128),
    ("9B",       4096, 12288,  16,  4, 256,  16,  32, 128, 128),
]

# ---- committed calibration points (evidence/qwen2b/ra/scratch_probe.log,
#      docs/QWEN2B_SCRATCH_MAP.md).  MEASURED == DERIVED at both.
GOLD = {
    "0.8B": dict(PEAK_DN=16384, PEAK_ATTN=15872, PEAK_MLP=14848, PEAK=16384,
                 SCRATCH=16384, STG=4096, STG_SZ=4096, BIG=8192),
    # 2B STG_SZ = LVD + STGCH = 2048 + 4096 = 6144, which is what BIG - STG
    # = 13312 - 7168 forces; docs/QWEN2B_SCRATCH_MAP.md carries BIG and STG.
    "2B":   dict(PEAK_DN=21504, PEAK_ATTN=23552, PEAK_MLP=25600, PEAK=25600,
                 SCRATCH=32768, STG=7168, STG_SZ=6144, BIG=13312),
}

if __name__ == "__main__":
    rows = [derive(*m) for m in MODELS]

    print("### VALIDATION — the corrected algebra must reproduce the committed "
          "0.8B / 2B numbers exactly")
    ok = True
    for r in rows:
        if r["name"] not in GOLD:
            continue
        for k, v in GOLD[r["name"]].items():
            match = (r[k] == v)
            ok &= match
            print(f"    {r['name']:5s} {k:10s} derived {r[k]:6d}  committed {v:6d}"
                  f"  {'OK' if match else '*** MISMATCH ***'}")
    print(f"    VALIDATION: {'PASS' if ok else 'FAIL'}")
    assert ok, "corrected algebra does not reproduce the committed 0.8B/2B maps"

    print()
    print("### DERIVED GEOMETRY")
    fields = ["H", "FFN", "NQ", "NKV", "LNKH", "LNVH", "LKD", "LVD",
              "CONV_DIM", "NQH", "KVH", "SCA_SZ", "STGCH", "STG", "STG_SZ", "BIG"]
    print(f"    {'field':10s}" + "".join(f"{r['name']:>10s}" for r in rows))
    for f in fields:
        print(f"    {f:10s}" + "".join(f"{r[f]:>10d}" for r in rows))

    print()
    print("### SCRATCH PEAK vs THE 32,768-WORD ISA CEILING "
          "(ref/gen_layer_script.py:231 SCRATCH_MAX)")
    print(f"    {'body':10s}" + "".join(f"{r['name']:>10s}" for r in rows))
    for f in ["PEAK_DN", "PEAK_ATTN", "PEAK_MLP", "PEAK", "SCRATCH"]:
        print(f"    {f:10s}" + "".join(f"{r[f]:>10d}" for r in rows))
    print(f"    {'fits ISA':10s}" + "".join(
        f"{('YES' if r['fits_isa'] else 'NO'):>10s}" for r in rows))
    print(f"    {'over by':10s}" + "".join(f"{r['over_by']:>10d}" for r in rows))
    print(f"    {'headroom':10s}" + "".join(
        f"{max(0, SCRATCH_MAX - r['PEAK']):>10d}" for r in rows))

    print()
    print("### WHICH BODY BINDS, and the MLP driver STG + 3*FFN")
    for r in rows:
        binder = max([("DN", r["PEAK_DN"]), ("ATTN", r["PEAK_ATTN"]),
                      ("MLP", r["PEAK_MLP"])], key=lambda kv: kv[1])
        print(f"    {r['name']:5s} binds on {binder[0]:4s} = {binder[1]:6d}"
              f"   (STG+3*FFN = {r['STG'] + 3 * r['FFN']:6d})")

    print()
    print("### W-REF-2: the SCA scalar-tile collision at LNVH=32")
    for m in MODELS:
        fixed = derive(*m, fix_sca=True)
        asis = derive(*m, fix_sca=False)
        LNVH = m[7]
        collide = (2 * LNVH > 32)
        print(f"    {m[0]:5s} LNVH={LNVH:3d}  A16 needs {2*LNVH:3d} words in a "
              f"32-word slot -> {'COLLIDES' if collide else 'fits'}; "
              f"SCA_SZ as-built {asis['SCA_SZ']} -> corrected {fixed['SCA_SZ']}")

    print()
    print("### W-REF-1: CONV_DIM under the as-built LKD = LNVH*LDK")
    for m in MODELS:
        name, H, FFN, NQ, NKV, HD, LNKH, LNVH, LDK, LDV = m
        real = 2 * (LNKH * LDK) + LNVH * LDV
        asbuilt = 2 * (LNVH * LDK) + LNVH * LDV
        print(f"    {name:5s} checkpoint CONV_DIM {real:6d}   "
              f"ref/layer_ref.py:38 would compute {asbuilt:6d}   "
              f"{'OK' if real == asbuilt else '*** WRONG ***'}")

    print()
    print("### MITIGATION — how many bodies must be restructured to fit 32,768")
    print("    (the ISA cannot grow: docs/SEQ_ISA.md:828-837 — DNST ARG0 is")
    print("     exactly full and ALU ARG2 has one spare bit already spent on")
    print("     dst[14], so there is no home for a 16th scratch address bit.)")
    for r in rows:
        if r["fits_isa"]:
            print(f"    {r['name']:5s} FITS as-is (headroom "
                  f"{SCRATCH_MAX - r['PEAK']} words) — no restructuring")
            continue
        bad = [b for b in ("DN", "ATTN", "MLP") if r[f"PEAK_{b}"] > SCRATCH_MAX]
        print(f"    {r['name']:5s} over: {', '.join(bad)}  "
              f"(DN {r['PEAK_DN']}, ATTN {r['PEAK_ATTN']}, MLP {r['PEAK_MLP']})")
        # MLP chunking.  ref/gen_layer_script.py:139 is
        #     PEAK_MLP = max(ML_SG + FFN, ML_DDST + H)
        # and BOTH terms must be carried.  Chunking gate/up into nc pieces of
        # C shrinks only the FIRST term; the second is
        #     ML_DDST + H = STG + 2*C + STGCH + H
        # which shrinks HALF as fast, so it takes over as the peak.  An earlier
        # revision of this study reported STG + 3*C alone and therefore
        # over-stated the headroom.  docs/QWEN2B_SCRATCH_MAP.md:161,:171-177
        # warns exactly this: chunking destroys the domination condition.
        for nc in (2, 3, 4):
            c = -(-r["FFN"] // nc)
            t1 = r["STG"] + 3 * c                       # ML_SG + C
            t2 = r["STG"] + 2 * c + r["STGCH"] + r["H"]  # ML_DDST + H
            p = max(t1, t2)
            which = "gate/up" if t1 >= t2 else "down-stage"
            print(f"          MLP in {nc} chunks of {c:5d}: "
                  f"gate/up {t1:6d} | down-stage {t2:6d} -> peak {p:6d} "
                  f"({which} binds)"
                  f"  {'fits, spare ' + str(SCRATCH_MAX - p) if p <= SCRATCH_MAX else 'OVER by ' + str(p - SCRATCH_MAX)}")
        if r["PEAK_ATTN"] > SCRATCH_MAX:
            print(f"          ATTN peak {r['PEAK_ATTN']} is set by "
                  f"AT_ODST+H = {r['BIG'] + r['H'] + r['STGCH'] + r['H'] + r['H']}"
                  f" / AT_GX8+NQH; it needs its own restructuring")
        if r["PEAK_DN"] > SCRATCH_MAX:
            print(f"          DN peak {r['PEAK_DN']} = BIG + CONV_DIM + LVD"
                  f" = {r['BIG']} + {r['CONV_DIM']} + {r['LVD']};"
                  f" it needs its own restructuring")

    print()
    print("### ATTN HEADROOM — thin margins worth stating")
    for r in rows:
        print(f"    {r['name']:5s} PEAK_ATTN {r['PEAK_ATTN']:6d}  "
              f"margin vs 32768 = {SCRATCH_MAX - r['PEAK_ATTN']:+7d}")

    json.dump([{k: v for k, v in r.items() if k != "SCA_tiles"} for r in rows],
              open(sys.argv[1], "w") if len(sys.argv) > 1 else sys.stderr, indent=1)
