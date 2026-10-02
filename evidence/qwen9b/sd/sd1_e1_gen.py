#!/usr/bin/env python3
"""sd1_e1_gen.py — Task SD1 fix round 1, E1: per-KEY layer-census probe scripts.

  FABLE5_MODEL=9b python evidence/qwen9b/sd/sd1_e1_gen.py <outdir> [seeds...]

Writes one tiny host-driven `.txt` script per (seed, command key) for the
Task 14-A layer census (evidence/qwen9b/g4/tb_layer_census.sv, the instrument
the 46.161 ms comparand came from).  Each script holds NINST instances of ONE
command key — (command, ALU sub-op / VN mode, element count) exactly as
sd1_common.key_of classifies them — so the census's per-opcode row for that
command IS that key's per-command cost.  Every key of BOTH lists (the .txt's
and the .e4's, 22 ALU + 5 VN) is covered.

The scripts are produced by `ref/gen_layer_script.Mach` itself (W / W32 / C /
R / E records, with its bit-exact model behind every R check), so a census
run is also a correctness run.  The two ops Mach does not model — DYNQ16
(ALU sub 12) and VN EPS-NORM — and the op-8 PROBE are written as raw C
records and modelled here with ref/layer_fixed's frozen specs, exactly as
ref/seq_model.py executes them.  Nothing under ref/, rtl/ or tb/ changes;
the only output is <outdir>/s<seed>_<key>.txt plus a sha256 manifest on
stdout.  Data: numpy default_rng(seed * 1000 + key index), fixed.
"""
import hashlib
import os
import sys

import numpy as np

import sd1_common as C
from sd1_common import SF, GLS, LR
import layer_fixed as LF

I64 = np.int64
NINST = 4
A, B, D, WT = 0x0000, 0x4000, 0x8000, 0xC000     # src, srcb, dst, VNW weights

# (name, kind, sub/mode, n, p0-or-None).  p0 None -> drawn per instance.
KEYS = [
    ("ALU", "DYNQ8", 0, 4096), ("ALU", "DYNQ8", 0, 12288),
    ("ALU", "SHIFT32", 1, 2048), ("ALU", "SHIFT32", 1, 1024),
    ("ALU", "SHIFT32", 1, 128), ("ALU", "SHIFT32", 1, 32),
    ("ALU", "SHIFT32W", 9, 2048),
    ("ALU", "SCALE", 2, 2048), ("ALU", "SCALE", 2, 128),
    ("ALU", "EMUL", 3, 128), ("ALU", "ADD", 4, 4096),
    ("ALU", "SILU16", 5, 128), ("ALU", "SILU32", 6, 2048),
    ("ALU", "SILU32", 6, 1024), ("ALU", "SIGM16", 7, 256),
    ("ALU", "EMUL32", 8, 256), ("ALU", "EMUL32", 8, 2048),
    ("ALU", "EMUL32", 8, 4096), ("ALU", "EMUL32-probe", 8, 4096),
    ("ALU", "AMAX32", 10, 2048), ("ALU", "AMAX32", 10, 512),
    ("ALU", "DYNQ16", 12, 128),
    ("VN", "rmsnorm0", 0, 4096), ("VN", "rmsnorm0", 0, 256),
    ("VN", "rmsnorm1", 1, 4096), ("VN", "l2norm", 2, 128),
    ("VN", "EPS-NORM", 2, 128),
]


def key_tuple(k):
    """The sd1_common.key_of tuple this probe measures."""
    kind, name, _sub, n = k
    if name == "EMUL32-probe":
        return ("ALU", "EMUL32", n, "probe")
    return (kind, name, n)


def fname(k):
    return "_".join(str(x) for x in key_tuple(k))


def x32(rng, n):
    """int32 pair data at a random magnitude (2^8 .. 2^26)."""
    mag = float(2 ** rng.integers(8, 27))
    return np.clip(np.round(rng.normal(0, mag, n)), -(1 << 30),
                   (1 << 30)).astype(I64)


def x16(rng, n, mag=None):
    mag = float(2 ** rng.integers(6, 14)) if mag is None else mag
    return np.clip(np.round(rng.normal(0, mag, n)), -32768, 32767).astype(I64)


def emit(M, k, rng):
    kind, name, sub, n = k
    if kind == "VN":
        mode = sub
        if name == "EPS-NORM":
            o = x32(rng, n)
            M.W32(A, o)
            M.C(11, GLS.enc_alu_a0(SF.ALU_DYNQ16, n, 0), GLS.enc_a1(A),
                GLS.enc_alu_a2(0, D))                       # k -> XRF[1]
            y, kk = LF.dynq16_fx(M.pairs(A, n))
            M.mem[D:D + n] = np.asarray(y, dtype=I64)
            nlog2 = n.bit_length() - 1
            M.C(1, SF.VN_EPSNORM_MODE | (nlog2 << 2) | (LF.S_F << 6)
                | (LF.DN_NORM_F << 10), GLS.enc_a1(D, D),
                SF.VN_ARG2_EPS | (SF.XRF_K_DN << SF.VN_ARG2_XRF_SHIFT))
            M.mem[D:D + n] = np.asarray(
                LF.eps_norm_fx(M.mem[D:D + n].copy(), kk, LF.S_F,
                               LF.DN_NORM_F, note=False), dtype=I64)
            M.R(D, n)
            return
        if mode in (0, 1):
            M.W(WT, x16(rng, n, 2.0 ** 12))
            M.vnw_(WT, n)
        inf = GLS.QKV_F if (mode == 2 or n == 256) else GLS.RS_F
        outf = GLS.NRM_F if mode == 2 else inf
        M.W(A, x16(rng, n))
        M.vn(mode, n, inf, outf, A, D)
        M.R(D, n)
        return
    # ---- ALU ----
    if name == "DYNQ16":
        M.W32(A, x32(rng, n))
        M.C(11, GLS.enc_alu_a0(sub, n, 0), GLS.enc_a1(A),
            GLS.enc_alu_a2(0, D))
        y, _k = LF.dynq16_fx(M.pairs(A, n))
        M.mem[D:D + n] = np.asarray(y, dtype=I64)
        M.R(D, n)
        return
    if name == "EMUL32-probe":
        M.W32(A, x32(rng, n) >> 12)
        M.W(B, x16(rng, n, 2.0 ** 12))
        M.C(11, GLS.enc_alu_a0(8, n, SF.ALU_PROBE_BIT),
            GLS.enc_a1(A, B), GLS.enc_alu_a2(SF.ALU_PROBE_BIT, D))
        prod = M.pairs(A, n) * M.mem[B:B + n]          # shift p0[5:0] = 0
        M.mem[D:D + n] = np.clip(prod, -32768, 32767)
        M.R(D, n)
        return
    pairs = sub in (1, 6, 8, 9, 10)
    if pairs:
        M.W32(A, x32(rng, n) >> (12 if sub == 8 else 0))
    else:
        M.W(A, x16(rng, n))
    if sub in (3, 4, 8):
        M.W(B, x16(rng, n, 2.0 ** 12))
    p0 = {0: 0, 1: int(rng.integers(-10, 15)), 2: int(rng.integers(6000, 30000)),
          3: 14, 4: 0, 5: int(rng.integers(0, 3)), 6: int(rng.integers(0, 12)),
          7: int(rng.integers(0, 3)), 8: int(rng.integers(8, 13)),
          9: int(rng.integers(6, 13)), 10: 1}[sub]
    M.alu(sub, n, p0, A, B, D)
    if sub == 10:
        M.A()
    elif sub == 0:
        M.R(D, n)
        M.E()
    else:
        M.R(D, 2 * n if sub == 9 else n)


def main():
    out = sys.argv[1]
    seeds = [int(s) for s in sys.argv[2:]] or [1, 2, 3, 4]
    os.makedirs(out, exist_ok=True)
    os.environ.pop("SEQ_EMIT", None)
    for s in seeds:
        for i, k in enumerate(KEYS):
            p = os.path.join(out, f"s{s}_{fname(k)}.txt")
            rng = np.random.default_rng(s * 1000 + i)
            with open(p, "w") as f:
                M = GLS.Mach(f)
                for _ in range(NINST):
                    emit(M, k, rng)
                print("Q", file=f)
            h = hashlib.sha256(open(p, "rb").read()).hexdigest()
            print(f"E1GEN seed={s} key={'|'.join(map(str, key_tuple(k)))} "
                  f"file={p} sha256={h}")


if __name__ == "__main__":
    main()
