#!/usr/bin/env python3
"""preamble_equiv.py — the guard on S3's "the retired preamble is equivalent".

S3 deletes the 120 CONVW and the 768 DNZ the pre-S3 preamble emitted (spec
2026-09-04-qwen35-9b-state-spill-design.md 6.4) and replaces them with a
HOST UPLOAD: zeros into the DN region, the conv images into the conv region.
That claim is only as good as the bytes, so this compares them.

  OLD  a `Mach` whose conv slot is filled by the retired preamble itself --
       W(STG, taps) + convw(c, 2048, STG) x3 + convz(0, CONV_DIM) -- and
       whose DN slot is zeroed by 32 DNZ, then SERIALISED into a DDR block
       through `Mach._sdma_copy` (the store side of an SST).
  NEW  the block `Mach.seed_conv` puts in the image at emission time, which
       is what `dump_state` writes to <prefix>.state.bin and to
       <prefix>_cv<L>.bin, and what the host uploads.

Byte equality per block, both kinds.  Run at the 9B geometry:

  FABLE5_MODEL=9b FABLE5_RS_F=7 python evidence/qwen9b/s3/preamble_equiv.py

  rc 0  PREAMBLE_EQUIV: PASS
  rc 1  a difference, with the first differing byte named

`--perturb` is the NEGATIVE CONTROL: it flips ONE byte of the new conv image
and one word of the new DN block, and the run must FAIL.  An instrument that
cannot fail proves nothing.
"""
import io
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "..", "ref"))
import gen_layer_script as G                                   # noqa: E402
import layer_ref as LR                                         # noqa: E402
import layer_fixed as LF                                       # noqa: E402

NLAYER = 3                       # three distinct weight sets is enough


def old_conv_block(taps, layer):
    """The retired preamble, run for real, then serialised as an SST would."""
    M = G.Mach(io.StringIO())
    M.layer(0, 0, 0, 0)
    for c in range(0, LR.CONV_DIM, 2048):
        M.W(G.STG, taps[c:c + 2048].reshape(-1))
        M.convw(c, 2048, G.STG)                  # the RETIRED weight load
    M.convz(0, LR.CONV_DIM)                      # the RETIRED state zero
    M.slot_id[G.K_CV][0] = (layer, 0)
    M._sdma_copy(G.K_CV, 0, layer, 0, to_slot=False)
    return M.img.get((G.K_CV, layer, 0), G._CV_BLOCK)


def old_dn_block(layer):
    """The retired 32 DNZ, serialised as an SST would."""
    M = G.Mach(io.StringIO())
    M.layer(0, 0, 0, 0)
    for h in range(LR.LNH):
        M.dnz(h)                                 # the RETIRED state zero
    M.slot_id[G.K_DN][0] = (layer, 0)
    M._sdma_copy(G.K_DN, 0, layer, 0, to_slot=False)
    return M.img.get((G.K_DN, layer, 0), G._DN_BLOCK)


def report(what, a, b):
    if np.array_equal(a, b):
        print(f"  OK  {what}: {len(a)} bytes identical")
        return True
    d = np.nonzero(np.asarray(a) != np.asarray(b))[0]
    print(f"  FAIL {what}: {len(d)} of {len(a)} bytes differ, first at "
          f"{int(d[0])} ({int(a[d[0]])} vs {int(b[d[0]])})")
    return False


def main():
    perturb = "--perturb" in sys.argv[1:]
    rng = np.random.default_rng(20260904)
    ok = True
    print(f"preamble_equiv: FABLE5_MODEL={os.environ.get('FABLE5_MODEL')} "
          f"CONV_DIM={LR.CONV_DIM} LNH={LR.LNH} LDK={LR.LDK} LDV={LR.LDV}")
    for L in range(NLAYER):
        wf = LR.init_layer_weights(rng, "linear_attention")
        taps = LF.quant_layer(wf)["dn"]["conv_w"]

        # NEW: the image the emitter seeds and the host uploads
        M = G.Mach(io.StringIO())
        new_cv = M.seed_conv(L, taps).copy()
        # NEW: the DN region the host memsets to zero
        new_dn = np.zeros(G._DN_BLOCK, dtype=np.uint8)
        if perturb:
            new_cv[7] ^= 0x01                    # one weight tap byte
            new_dn[G.LR.LDV * 2 * 3] = 0x01      # one DN state word

        ok &= report(f"conv block L={L} (CONVW+CONVZ vs seed_conv)",
                     old_conv_block(taps, L), new_cv)
        ok &= report(f"DN block   L={L} (32 x DNZ vs the host's zero fill)",
                     old_dn_block(L), new_dn)
    if perturb:
        print("PREAMBLE_EQUIV --perturb: CAUGHT" if not ok
              else "PREAMBLE_EQUIV --perturb: NOT CAUGHT (the instrument is "
                   "blind)")
        return 0 if not ok else 1
    print("PREAMBLE_EQUIV: PASS" if ok else "PREAMBLE_EQUIV: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
